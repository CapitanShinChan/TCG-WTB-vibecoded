"""In-memory database tests; the user's inventory.db is never opened."""
import copy
import datetime as dt
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.db import Base
from app.models import BuylistItem, CardList
from app.main import _upsert_buylist_item, lists_delete
from app.fabrary import client as client_module
from app.fabrary.compat import reconcile_items
from test_catalogue import CARD


class BuylistCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_general_game_printing "
                "ON buylist_items (game, printing_id) WHERE list_id IS NULL"
            ))
        self.db = Session(self.engine, autoflush=False)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.catalogue = patch.object(client_module.client, "get_card", return_value=copy.deepcopy(CARD))
        self.catalogue.start()
        self.addCleanup(self.catalogue.stop)

    def add(self, printing_id="fab:PEN097-Rainbow", foiling="Rainbow", list_id=None):
        return _upsert_buylist_item(self.db, game="flesh-and-blood", card_identifier="doomsaying-red",
            card_name="Doomsaying", printing_id=printing_id, printing_label="Compendium of Rathe",
            foiling=foiling, image_url="https://content.fabrary.net/cards/PEN097-RF.webp" if foiling else
            "https://content.fabrary.net/cards/PEN097.webp", quantity=2, list_id=list_id)

    def legacy(self, list_id=None):
        item = BuylistItem(game="flesh-and-blood", card_identifier="doomsaying-red", card_name="Doomsaying",
            printing_id="PEN097", printing_label="Compendium of Rathe Rainbow", foiling="Rainbow",
            image_url="https://content.fabrary.net/cards/PEN097-RF.webp", quantity=3, list_id=list_id,
            price=1.25)
        self.db.add(item)
        self.db.commit()
        return item

    def test_priced_legacy_snapshot_survives_unpriced_canonical_merge(self):
        self.add()
        self.db.flush()
        target = self.db.scalars(select(BuylistItem)).one()
        target_id = target.id
        source = self.legacy()
        fields = ("price", "suggested_price", "price_sample_size", "price_updated_at", "currency")
        snapshot = (1.25, None, 7, dt.datetime(2026, 1, 2, 12), "USD")
        for field, value in zip(fields, snapshot):
            setattr(source, field, value)
        # Metadata on an unpriced row must not be mixed into the source snapshot.
        target.price_sample_size = 99
        target.currency = "EUR"
        source.tcgplayer_product_id = "677622"
        source.tcgplayer_url = "https://www.tcgplayer.com/product/677622"
        target.tcgplayer_product_id = None
        target.tcgplayer_url = None
        self.db.commit()

        reconcile_items(self.db, "doomsaying-red", None)
        self.db.commit()
        self.db.expire_all()

        survivor = self.db.scalars(select(BuylistItem)).one()
        self.assertEqual(survivor.id, target_id)
        self.assertEqual(survivor.quantity, 5)
        self.assertEqual(tuple(getattr(survivor, field) for field in fields), snapshot)
        self.assertEqual(survivor.tcgplayer_product_id, "677622")
        self.assertEqual(survivor.tcgplayer_url, "https://www.tcgplayer.com/product/677622")

    def test_merge_selects_whole_snapshot_by_price_then_timestamp(self):
        earlier = dt.datetime(2026, 1, 1, 12)
        later = dt.datetime(2026, 1, 2, 12)
        utc = dt.timezone.utc
        plus_two = dt.timezone(dt.timedelta(hours=2))
        cases = [
            ("newer source", later, earlier, 2.5, 1.25, True),
            ("newer target", earlier, later, 2.5, 1.25, False),
            ("known source", later, None, 2.5, 1.25, True),
            ("known target", None, earlier, 2.5, 1.25, False),
            ("equal timestamps", later, later, 2.5, 1.25, False),
            ("both unknown", None, None, 2.5, 1.25, False),
            ("aware source newer", later.replace(tzinfo=utc), earlier, 2.5, 1.25, True),
            ("aware target older", later, earlier.replace(tzinfo=utc), 2.5, 1.25, True),
            ("offset source older", earlier.replace(hour=13, tzinfo=plus_two), earlier, 2.5, 1.25, False),
            ("same instant tie", earlier.replace(hour=14, tzinfo=plus_two),
             earlier.replace(tzinfo=utc), 2.5, 1.25, False),
            ("suggested-only source", None, later, None, None, True),
            ("zero source price", None, later, 0.0, None, True),
            ("only target priced", later, None, None, 1.25, False),
        ]
        fields = ("price", "suggested_price", "price_sample_size", "price_updated_at", "currency")
        for label, source_at, target_at, source_price, target_price, use_source in cases:
            with self.subTest(policy=label):
                self.add()
                self.db.flush()
                target = self.db.scalars(select(BuylistItem)).one()
                source = self.legacy()
                source_snapshot = (source_price, 2.0 if label == "suggested-only source" else None,
                                   None, source_at, None)
                target_snapshot = (target_price, None, 11, target_at, "EUR")
                # Do not commit here: SQLite reloads timestamps as naive; exercise
                # actual aware/naive values together in the session identity map.
                for field, value in zip(fields, source_snapshot):
                    setattr(source, field, value)
                for field, value in zip(fields, target_snapshot):
                    setattr(target, field, value)
                expected = source_snapshot if use_source else target_snapshot

                reconcile_items(self.db, "doomsaying-red", None)
                survivor = self.db.scalars(select(BuylistItem)).one()
                self.assertIs(survivor, target)
                self.assertEqual(survivor.quantity, 5)
                actual = tuple(getattr(survivor, field) for field in fields)
                self.db.delete(survivor)
                self.db.commit()
                self.assertEqual(actual, expected)

    def test_merge_fills_only_missing_compatible_product_references(self):
        source_url = "https://www.tcgplayer.com/product/677622"
        cases = [
            ("677622", None, "677622", source_url),
            (None, "https://www.tcgplayer.com/product/677622?existing=1",
             "677622", "https://www.tcgplayer.com/product/677622?existing=1"),
            ("different-product", None, "different-product", None),
        ]
        for product_id, url, expected_id, expected_url in cases:
            with self.subTest(product_id=product_id, url=url):
                self.add()
                self.db.flush()
                target = self.db.scalars(select(BuylistItem)).one()
                source = self.legacy()
                source.tcgplayer_product_id = "677622"
                source.tcgplayer_url = source_url
                target.tcgplayer_product_id = product_id
                target.tcgplayer_url = url

                reconcile_items(self.db, "doomsaying-red", None)
                actual = (target.tcgplayer_product_id, target.tcgplayer_url)
                self.db.delete(target)
                self.db.commit()
                self.assertEqual(actual, (expected_id, expected_url))

    def test_readding_legacy_foil_merges_but_normal_stays_separate(self):
        old = self.legacy()
        old_id = old.id
        self.assertFalse(self.add())
        self.assertTrue(self.add("fab:PEN097", None))
        self.db.commit()
        rows = self.db.scalars(select(BuylistItem)).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(old.id, old_id)
        self.assertEqual(old.printing_id, "fab:PEN097-Rainbow")
        self.assertEqual(old.quantity, 5)
        self.assertEqual(old.price, 1.25)

    def test_legacy_image_rename_requires_matching_product_and_unique_variant(self):
        old = self.legacy()
        old.image_url = "https://content.fabrary.net/cards/PEN097.webp"
        old.tcgplayer_product_id = "677622"
        self.db.commit()
        self.assertFalse(self.add())
        self.assertEqual(old.printing_id, "fab:PEN097-Rainbow")
        self.assertEqual(old.quantity, 5)

    def test_repeated_import_rows_merge_before_commit(self):
        self.assertTrue(self.add())
        self.assertFalse(self.add())
        self.db.commit()
        self.assertEqual(self.db.scalars(select(BuylistItem)).one().quantity, 4)

    def test_ambiguous_legacy_mapping_is_rejected_without_modifying_row(self):
        old = self.legacy()
        card = copy.deepcopy(CARD)
        duplicate = copy.deepcopy(card["printings"][1])
        duplicate["print"] += "-Other"
        card["printings"].append(duplicate)
        with patch.object(client_module.client, "get_card", return_value=card):
            with self.assertRaises(HTTPException) as caught:
                self.add()
        self.assertEqual(caught.exception.status_code, 409)
        self.db.rollback()
        self.assertEqual(old.printing_id, "PEN097")
        self.assertEqual(old.quantity, 3)

    def test_delete_list_keep_cards_merges_legacy_with_canonical(self):
        lst = CardList(name="Deck")
        self.db.add(lst)
        self.db.commit()
        self.legacy(list_id=lst.id)
        self.add()
        self.db.commit()
        lists_delete(list_id=lst.id, mode="move", db=self.db)
        rows = self.db.scalars(select(BuylistItem)).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].quantity, 5)
        self.assertIsNone(rows[0].list_id)


if __name__ == "__main__":
    unittest.main()
