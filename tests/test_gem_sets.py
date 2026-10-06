"""GEM pack classification from checked-in, source-backed card-code assignments."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app import main
from app.models import BuylistItem, CardList
from app.providers.flesh_and_blood import FleshAndBloodProvider

FIXTURE = json.loads((Path(__file__).parent / "fixtures/gem_pack_codes.json").read_text(encoding="utf-8"))


def card_with_printings(codes):
    return {
        "cardIdentifier": "fixture-card", "name": "Fixture Card", "sets": ["GEM"],
        "printings": [{"identifier": code, "print": code + "-Rainbow-Extended Art",
                       "set": "GEM", "foiling": "Rainbow", "treatments": ["Extended Art"],
                       "tcgplayer": {"productId": "123"}} for code in codes],
    }


class GemProviderTests(unittest.TestCase):
    def test_search_and_import_use_pack_labels_without_mutating_catalogue(self):
        import copy
        from app.importer import parse_list, resolve_list

        card = card_with_printings(["GEM141", "GEM002", "GEM196", "GEM141"])
        card["sets"] = ["GEM", "Monarch"]
        original = copy.deepcopy(card)
        with patch("app.providers.flesh_and_blood.fabrary") as catalogue:
            catalogue.get_card.return_value = card
            catalogue.search_cards.return_value = [card]
            provider = FleshAndBloodProvider()
            self.assertEqual(provider.search("Fixture")[0].sets, ["GEM1", "GEM5", "GEM6", "Monarch"])
            line = resolve_list(parse_list("1x RF EA Fixture Card"), provider)[0]
            self.assertEqual(line.printing["set_code"], "GEM5")
            self.assertTrue(line.printing["printing_label"].startswith("GEM5 "))
        self.assertEqual(card, original)

    def test_unknown_and_malformed_ids_are_not_guessed(self):
        from app.providers.fab_sets import gem_set_code

        for ident in (None, "", "GEM000", "GEM220", "GEM999", "GEM1", "GEM1410", "gem141", " GEM141", "GEM141-", "GEM141\n", "PEN097"):
            with self.subTest(identifier=ident):
                self.assertIsNone(gem_set_code(ident))
        for ident in ("GEM141", "GEM141-CF", "fab:GEM141-Cold-Full Art"):
            self.assertEqual(gem_set_code(ident), "GEM5")

    def test_all_source_backed_codes_have_the_correct_set_without_changing_identity(self):
        provider = FleshAndBloodProvider()
        for product in FIXTURE["products"] + FIXTURE["supplements"]:
            card = card_with_printings(product["codes"])
            with self.subTest(set=product["set"], source=product["source"]), \
                    patch("app.providers.flesh_and_blood.fabrary") as catalogue:
                catalogue.get_card.return_value = card
                printings = provider.printings("fixture-card")
                self.assertEqual([p.set_code for p in printings], [product["set"]] * len(product["codes"]))
                self.assertEqual([p.identifier for p in printings],
                                 ["fab:" + code + "-Rainbow-Extended Art" for code in product["codes"]])
                self.assertTrue(all(p.label.startswith(product["set"] + " ") for p in printings))
                self.assertTrue(all(p.price_source_id == "123" for p in printings))


class GemInventoryTests(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from app.db import Base

        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, autoflush=False)
        self.addCleanup(self.db.close)

    def test_startup_corrects_old_sets_and_labels_without_changing_other_fields(self):
        from sqlalchemy import select
        from app import db as database
        from app.models import BuylistItem, CardList

        self.db.add(CardList(id=1, name="Deck"))
        cases = [("GEM032", "GEM1"), ("fab:GEM033-Rainbow", "GEM2"),
                 ("GEM104", "GEM3"), ("fab:GEM105-Cold", "GEM4"),
                 ("GEM183", "GEM5"), ("fab:GEM219-Cold-Full Art", "GEM6"),
                 ("GEM220", "GEM"), ("PEN097", "GEM")]
        for ident, (printing, _) in enumerate(cases, start=1):
            self.db.add(BuylistItem(id=ident, game="flesh-and-blood", card_identifier="card" + str(ident),
                card_name="Card", printing_id=printing, printing_label="GEM Extended Art Rainbow",
                set_code="GEM", list_id=1 if ident % 2 else None, quantity=3,
                price=1.25, suggested_price=1.0, currency="USD", price_sample_size=7,
                tcgplayer_product_id="123", image_url="https://example.test/card.webp",
                price_history=[{"price": 1.25, "at": None, "currency": "USD"}]))
        self.db.add(BuylistItem(id=99, game="other-game", card_identifier="other", card_name="Other",
            printing_id="GEM141", printing_label="GEM Rainbow", set_code="GEM", quantity=1))
        self.db.commit()
        fields = [c.name for c in BuylistItem.__table__.columns if c.name not in ("set_code", "printing_label")]
        before = {item.id: tuple(getattr(item, name) for name in fields)
                  for item in self.db.scalars(select(BuylistItem))}
        with patch.object(database, "ENGINE", self.engine):
            database.init_db()
            database.init_db()
        self.db.expire_all()
        for ident, (_, expected) in enumerate(cases, start=1):
            item = self.db.get(BuylistItem, ident)
            self.assertEqual(item.set_code, expected)
            self.assertEqual(item.printing_label, expected + " Extended Art Rainbow")
        self.assertEqual(self.db.get(BuylistItem, 99).set_code, "GEM")
        after = {item.id: tuple(getattr(item, name) for name in fields)
                 for item in self.db.scalars(select(BuylistItem))}
        self.assertEqual(after, before)

    def test_corrected_metadata_reaches_table_export_groups_and_filters(self):
        from sqlalchemy import select
        from app import db as database, export

        for ident, printing in [(1, "GEM010"), (2, "fab:GEM196-Rainbow")]:
            self.db.add(BuylistItem(id=ident, game="flesh-and-blood", card_identifier=str(ident),
                card_name="Card " + str(ident), printing_id=printing, printing_label="GEM Rainbow",
                set_code="GEM", quantity=1, suggested_price=2.0))
        self.db.commit()
        with patch.object(database, "ENGINE", self.engine):
            database.init_db()
        self.db.expire_all()
        items = list(self.db.scalars(select(BuylistItem).order_by(BuylistItem.id)))
        self.assertEqual(main._export_filter_options(items)[0], ["GEM1", "GEM2", "GEM3", "GEM4", "GEM5", "GEM6"])
        self.assertEqual([it.id for it in export.filter_items(items, sets={"GEM6"})], [2])
        self.assertIn("GEM1", export.discord_text(items))
        self.assertIn("GEM6", export.discord_text(items))
        html = main.templates.env.get_template("_buylist_table.html").render(items=items, scope="all", lists=[])
        self.assertIn('data-sort="GEM1">GEM1</td>', html)
        self.assertIn('data-sort="GEM6">GEM6</td>', html)

    def test_metadata_normalization_does_not_rewrite_nonprefix_labels(self):
        from app.providers.fab_sets import normalize_gem_metadata

        self.assertEqual(normalize_gem_metadata("fab:GEM141-Cold", "GEM1", "GEM1 Cold"), ("GEM5", "GEM5 Cold"))
        self.assertEqual(normalize_gem_metadata("GEM141", None, "Custom GEM art"), ("GEM5", "Custom GEM art"))
        self.assertEqual(normalize_gem_metadata("GEM220", "GEM", "GEM Cold"), ("GEM", "GEM Cold"))

    def test_stale_add_payload_and_readding_existing_card_use_correct_set(self):
        from sqlalchemy import select
        from app import main
        from app.models import BuylistItem

        card = card_with_printings(["GEM141"])
        args = dict(game="flesh-and-blood", card_identifier="fixture-card", card_name="Fixture Card",
                    printing_id="fab:GEM141-Rainbow-Extended Art", printing_label="GEM Extended Art Rainbow",
                    set_code="GEM", foiling="Rainbow", quantity=2)
        with patch.object(main.catalogue, "get_card", return_value=card):
            self.assertTrue(main._upsert_buylist_item(self.db, **args))
            self.db.commit()
            item = self.db.scalars(select(BuylistItem)).one()
            self.assertEqual(item.set_code, "GEM5")
            self.assertEqual(item.printing_label, "GEM5 Extended Art Rainbow")
            item.set_code = "GEM"
            item.printing_label = "GEM Extended Art Rainbow"
            self.db.commit()
            self.assertFalse(main._upsert_buylist_item(self.db, **args))
            self.db.commit()
            self.assertEqual(item.set_code, "GEM5")
            self.assertEqual(item.printing_label, "GEM5 Extended Art Rainbow")
            self.assertEqual(item.quantity, 4)


if __name__ == "__main__":
    unittest.main()
