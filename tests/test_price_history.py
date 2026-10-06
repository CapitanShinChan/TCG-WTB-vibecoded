"""Price-history regression tests; only isolated SQLite databases are used."""
import datetime as dt
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import main
from app.db import Base
from app.models import BuylistItem
from app.pricing.tcgplayer import PricingResult


class PriceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.item = BuylistItem(
            game="flesh-and-blood", card_identifier="card", card_name="Card",
            printing_id="fab:TEST001", printing_label="Test", quantity=2,
            tcgplayer_product_id="123", price=1.0, currency="USD",
            price_updated_at=dt.datetime(2026, 1, 1),
        )
        self.db.add(self.item)
        self.db.commit()

    def refresh(self, value, currency="USD"):
        with patch("app.main.get_pricing", return_value=PricingResult(value, value, 10, currency)):
            self.assertTrue(main._refresh_price(self.item))
        self.db.commit()
        self.db.expire_all()
        return self.db.scalars(select(BuylistItem)).one()

    def test_existing_database_upgrade_is_additive_and_repeatable(self):
        from sqlalchemy import inspect, text
        from app import db as database

        self.db.close()
        with self.engine.begin() as connection:
            connection.execute(text("ALTER TABLE buylist_items DROP COLUMN price_history"))
        with patch.object(database, "ENGINE", self.engine):
            database.init_db()
            database.init_db()
        self.assertIn("price_history", {c["name"] for c in inspect(self.engine).get_columns("buylist_items")})
        with Session(self.engine) as db:
            item = db.scalars(select(BuylistItem)).one()
            self.assertEqual((item.quantity, item.price, item.currency), (2, 1.0, "USD"))
            self.assertIsNone(item.price_history)

    def test_missing_prices_do_not_add_points_and_zero_is_a_real_price(self):
        item = self.refresh(None)
        self.assertEqual([p["price"] for p in item.price_history], [1.0])
        item = self.refresh(0.0)
        self.assertEqual([p["price"] for p in item.price_history], [1.0, 0.0])
        item = self.refresh(0.0)
        self.assertEqual([p["price"] for p in item.price_history], [1.0, 0.0, 0.0])

    def test_invalid_prices_and_provider_failures_leave_snapshot_unchanged(self):
        from app.pricing.tcgplayer import TCGPlayerError

        self.refresh(2.0)
        before = list(self.item.price_history)
        for value in [float("nan"), float("inf"), -1.0]:
            with self.subTest(value=value), patch("app.main.get_pricing", return_value=PricingResult(value, 1.0, 1)):
                with self.assertRaises(TCGPlayerError):
                    main._refresh_price(self.item)
                self.assertEqual(self.item.price_history, before)
                self.assertEqual(self.item.price, 2.0)
        with patch("app.main.get_pricing", side_effect=TCGPlayerError("offline")):
            with self.assertRaises(TCGPlayerError):
                main._refresh_price(self.item)
        self.assertEqual(self.item.price_history, before)

    def test_currency_change_starts_a_comparable_history(self):
        item = self.refresh(2.0, "EUR")
        self.assertEqual([p["price"] for p in item.price_history], [2.0])
        self.assertEqual([p["currency"] for p in item.price_history], ["EUR"])

    def history_source(self, *, named_list=False):
        from app.models import CardList

        def point(value):
            return {"price": float(value), "at": dt.datetime(2026, 1, value, tzinfo=dt.timezone.utc).isoformat(), "currency": "USD"}
        self.item.price_history = [point(v) for v in range(1, 7)]
        self.item.price = 6.0
        self.item.price_updated_at = dt.datetime(2026, 1, 6)
        list_id = None
        if named_list:
            deck = CardList(name="Deck")
            self.db.add(deck)
            self.db.flush()
            list_id = deck.id
        source = BuylistItem(
            game=self.item.game, card_identifier=self.item.card_identifier, card_name="Card",
            printing_id="fab:TEST001" if named_list else "TEST001", printing_label="Test",
            quantity=3, list_id=list_id, price=12.0, currency="USD",
            price_updated_at=dt.datetime(2026, 1, 12),
            price_history=[point(v) for v in range(6, 13)],
        )
        self.db.add(source)
        self.db.commit()
        return source

    def assert_merged_history(self):
        self.db.expire_all()
        item = self.db.scalars(select(BuylistItem)).one()
        self.assertEqual([p["price"] for p in item.price_history], list(range(3, 13)))
        self.assertEqual((item.price, item.quantity), (12.0, 5))

    def test_legacy_reconciliation_preserves_combined_history(self):
        from app.fabrary.compat import reconcile_items

        self.history_source()
        reconcile_items(self.db, "card", None, card={"printings": [{"print": "TEST001", "identifier": "TEST001"}]})
        self.db.commit()
        self.assert_merged_history()

    def test_moving_list_into_general_preserves_combined_history(self):
        source = self.history_source(named_list=True)
        main.lists_delete(list_id=source.list_id, mode="move", db=self.db)
        self.assert_merged_history()

    def test_table_renders_accessible_history_between_price_columns(self):
        import re
        from xml.etree import ElementTree as ET

        self.refresh(2.0)
        html = main.templates.env.get_template("_buylist_table.html").render(items=[self.item], lists=[], scope="general")
        self.assertIn('class="price-sparkline', html)
        self.assertLess(html.index('>Current</th>'), html.index('>History</th>'))
        self.assertLess(html.index('>History</th>'), html.index('>Suggested</th>'))
        svg = ET.fromstring(re.search(r"<svg.*?</svg>", html, re.S).group())
        self.assertEqual(svg.attrib["role"], "img")
        self.assertIn("Data points: 2", svg.attrib["aria-label"])
        self.assertNotIn("USD", svg.attrib["aria-label"])
        self.assertEqual(len(svg.findall("circle")), 2)
        self.assertEqual(len(svg.findall(".//title")), 1, "Points must not override the concise graph tooltip")
        # XML parsers normalize attribute newlines; compare accessible content.
        self.assertEqual(" ".join(svg.find("title").text.split()), " ".join(svg.attrib["aria-label"].split()))
        self.assertRegex(svg.attrib["aria-label"], r"Last update: \d{4}/\d{2}/\d{2}$")

    def test_all_refresh_routes_persist_history_and_scoped_tables_render_it(self):
        from fastapi.testclient import TestClient
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from app.db import get_session
        from app.models import CardList

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        with factory() as db:
            deck = CardList(name="Deck")
            db.add(deck)
            db.flush()
            deck_id = deck.id
            item = BuylistItem(game="test", card_identifier="card", card_name="Card",
                              printing_id="print", printing_label="Test", quantity=1,
                              tcgplayer_product_id="123", list_id=deck_id)
            db.add(item)
            db.commit()
            item_id = item.id
        def session():
            with factory() as db:
                yield db
        main.app.dependency_overrides[get_session] = session
        self.addCleanup(main.app.dependency_overrides.clear)
        with patch("app.main.is_authorized", return_value=True), patch("app.main.SessionLocal", factory):
            # Deliberately no lifespan context: never open the real DB or logs.
            http = TestClient(main.app)
            self.addCleanup(http.close)
            for value, endpoint in enumerate(["refresh-price", "refresh-all", "refresh-all-stream"], start=1):
                with patch("app.main.get_pricing", return_value=PricingResult(float(value), 0.5, 10)):
                    response = http.post(f"/buylist/{endpoint}", data={"item_id": item_id}, follow_redirects=False)
                self.assertIn(response.status_code, (200, 303), response.text)
                with factory() as db:
                    history = db.get(BuylistItem, item_id).price_history
                    self.assertEqual([p["price"] for p in history], list(range(1, value + 1)))
            for url in ["/", "/buylist", "/partials/buylist"]:
                response = http.get(url, params={"scope": deck_id})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn('class="price-sparkline', response.text)
                self.assertIn("Data points: 3", response.text)

    def test_unpriced_item_and_unknown_legacy_date_do_not_invent_history(self):
        self.item.price = None
        self.refresh(None)
        self.assertEqual(self.item.price_history, [])
        self.item.price = 1.0
        self.item.price_updated_at = None
        self.refresh(2.0)
        self.assertIsNone(self.item.price_history[0]["at"])
        self.assertEqual([p["price"] for p in self.item.price_history], [1.0, 2.0])

    def test_refresh_persists_only_latest_ten_observations(self):
        item = self.refresh(2.0)
        history = getattr(item, "price_history", None)
        self.assertIsInstance(history, list, "Refresh must persist market-price history")
        self.assertEqual([p["price"] for p in history], [1.0, 2.0])
        self.assertEqual(history[0]["at"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(history[-1]["currency"], "USD")
        for value in range(3, 14):
            item = self.refresh(float(value))
        self.assertEqual([p["price"] for p in item.price_history], list(range(4, 14)))
        self.assertEqual(item.price, 13.0)
        self.assertEqual(item.quantity, 2)
        # Re-open the database session to prove this isn't transient Python state.
        with Session(self.engine) as db:
            self.assertEqual(db.get(BuylistItem, item.id).price_history, item.price_history)


class ConcurrentPriceHistoryTests(unittest.TestCase):
    def setUp(self):
        from sqlalchemy.orm import sessionmaker

        # File-backed SQLite gives each Session its own real connection/transaction.
        tmp = tempfile.TemporaryDirectory(
            dir=os.getenv("CARD_INVENTORY_TEST_TMP") or Path(__file__).resolve().parents[1],
        )
        self.addCleanup(tmp.cleanup)
        self.engine = create_engine(f"sqlite:///{Path(tmp.name) / 'prices.db'}")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, autoflush=False)
        with self.factory() as db:
            item = BuylistItem(
                game="test", card_identifier="card", card_name="Card",
                printing_id="print", printing_label="Test", quantity=2,
                tcgplayer_product_id="123", price=1.0, suggested_price=0.5,
                price_sample_size=10, currency="USD",
                price_updated_at=dt.datetime(2026, 1, 1),
                price_history=[{"price": 1.0, "at": "2026-01-01T00:00:00+00:00", "currency": "USD"}],
            )
            db.add(item)
            db.commit()
            self.item_id = item.id

    def http_client(self):
        from fastapi.testclient import TestClient
        from app.db import get_session

        def session():
            with self.factory() as db:
                yield db

        self.enterContext(patch.dict(main.app.dependency_overrides, {get_session: session}))
        self.enterContext(patch("app.main.SessionLocal", self.factory))
        self.enterContext(patch("app.main.is_authorized", return_value=True))
        # No lifespan: never open the real database or configure log files.
        http = TestClient(main.app)
        self.addCleanup(http.close)
        return http

    def test_bulk_routes_commit_each_item_before_fetching_next(self):
        with self.factory() as db:
            db.add(BuylistItem(
                game="test", card_identifier="other", card_name="Other",
                printing_id="other", printing_label="Other", quantity=1,
                tcgplayer_product_id="456",
            ))
            db.commit()
        http = self.http_client()
        for value, endpoint in enumerate(["refresh-all", "refresh-all-stream"], start=2):
            with self.subTest(endpoint=endpoint):
                seen = []

                def pricing(product_id, variant):
                    if seen:
                        # The next network call must not inherit the preceding
                        # item's SQLite write transaction (even for plain bulk).
                        with self.factory() as verify:
                            previous = verify.scalar(select(BuylistItem).where(
                                BuylistItem.tcgplayer_product_id == seen[-1],
                            ))
                            self.assertEqual(previous.price, value)
                            self.assertEqual(previous.price_history[-1]["price"], value)
                    seen.append(product_id)
                    return PricingResult(value, 0.5, 10)

                with patch("app.main.get_pricing", side_effect=pricing):
                    response = http.post(f"/buylist/{endpoint}", follow_redirects=False)
                self.assertIn(response.status_code, (200, 303), response.text)
                self.assertEqual(len(seen), 2)

    def test_overlapping_requests_serialize_writes_on_all_refresh_routes(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event, Lock, get_ident
        from sqlalchemy import event

        http = self.http_client()
        for index, endpoint in enumerate(["refresh-price", "refresh-all", "refresh-all-stream"]):
            with self.subTest(endpoint=endpoint):
                first_loaded, second_loaded = Event(), Event()
                first_committing, second_writing = Event(), Event()
                roles, role_lock = {}, Lock()
                first_value = 2 + index * 2

                def pricing(product_id, variant):
                    with role_lock:
                        role = "first" if not roles else "second"
                        roles[role] = get_ident()
                    # Both requests have loaded the same persisted history before
                    # either can record its mocked provider observation.
                    if role == "first":
                        first_loaded.set()
                        self.assertTrue(second_loaded.wait(5), "second request never loaded")
                        return PricingResult(first_value, first_value / 2, first_value)
                    second_loaded.set()
                    self.assertTrue(first_committing.wait(5), "first request never reached commit")
                    return PricingResult(first_value + 1, (first_value + 1) / 2, first_value + 1)

                def before_commit(db):
                    if db.bind is self.engine and get_ident() == roles.get("first"):
                        first_committing.set()
                        # Do not allow the first transaction to commit until the
                        # second request actually attempts a competing SQL write.
                        self.assertTrue(second_writing.wait(5), "second request never attempted a write")

                def before_sql(connection, cursor, statement, parameters, context, executemany):
                    if get_ident() == roles.get("second") and context.isupdate:
                        second_writing.set()

                event.listen(self.factory.class_, "before_commit", before_commit)
                event.listen(self.engine, "before_cursor_execute", before_sql)
                try:
                    with patch("app.main.get_pricing", side_effect=pricing), ThreadPoolExecutor(2) as pool:
                        first = pool.submit(http.post, f"/buylist/{endpoint}",
                                            data={"item_id": self.item_id}, follow_redirects=False)
                        self.assertTrue(first_loaded.wait(5), "first request never loaded")
                        second = pool.submit(http.post, f"/buylist/{endpoint}",
                                             data={"item_id": self.item_id}, follow_redirects=False)
                        for future in (first, second):
                            response = future.result(timeout=10)
                            self.assertIn(response.status_code, (200, 303), response.text)
                finally:
                    event.remove(self.factory.class_, "before_commit", before_commit)
                    event.remove(self.engine, "before_cursor_execute", before_sql)
                with self.factory() as verify:
                    saved = verify.get(BuylistItem, self.item_id)
                    self.assertEqual([p["price"] for p in saved.price_history], list(range(1, first_value + 2)))
                    self.assertEqual(
                        (saved.price, saved.suggested_price, saved.price_sample_size, saved.currency),
                        (first_value + 1, (first_value + 1) / 2, first_value + 1, "USD"),
                    )
                    self.assertEqual(saved.price_history[-1]["at"],
                                     saved.price_updated_at.replace(tzinfo=dt.timezone.utc).isoformat())

    def test_stale_snapshot_values_can_revert_without_losing_pending_edits(self):
        with self.factory() as first, self.factory() as second:
            first_item = first.get(BuylistItem, self.item_id)
            stale_item = second.get(BuylistItem, self.item_id)
            with patch("app.main.get_pricing", side_effect=[
                PricingResult(2.0, 1.0, 20), PricingResult(1.0, 0.5, 10),
            ]):
                main._refresh_price(first_item)
                first.commit()
                stale_item.quantity = 7
                main._refresh_price(stale_item)
                second.commit()
        with self.factory() as verify:
            saved = verify.get(BuylistItem, self.item_id)
            self.assertEqual([p["price"] for p in saved.price_history], [1.0, 2.0, 1.0])
            self.assertEqual((saved.price, saved.suggested_price, saved.price_sample_size), (1.0, 0.5, 10))
            self.assertEqual(saved.quantity, 7)

    def test_rollback_preserves_committed_history_and_whole_snapshot(self):
        fields = ("price_history", "price", "suggested_price", "price_sample_size", "price_updated_at", "currency")
        with self.factory() as first, self.factory() as second:
            first_item = first.get(BuylistItem, self.item_id)
            stale_item = second.get(BuylistItem, self.item_id)
            with patch("app.main.get_pricing", side_effect=[
                PricingResult(2.0, 1.0, 20), PricingResult(3.0, 1.5, 30),
            ]):
                main._refresh_price(first_item)
                first.commit()
                before = [getattr(first_item, field) for field in fields]
                main._refresh_price(stale_item)
                second.flush()
                # Even after flush, another connection sees neither half of the
                # uncommitted pricing snapshot/history update.
                with self.factory() as verify:
                    saved = verify.get(BuylistItem, self.item_id)
                    self.assertEqual([getattr(saved, field) for field in fields], before)
                second.rollback()
        with self.factory() as verify:
            saved = verify.get(BuylistItem, self.item_id)
            self.assertEqual([getattr(saved, field) for field in fields], before)
            self.assertEqual([p["price"] for p in saved.price_history], [1.0, 2.0])

    def test_interleaved_stale_sessions_keep_both_observations_and_latest_ten(self):
        for initial in ([1], list(range(1, 11))):
            with self.subTest(initial=initial):
                with self.factory() as seed:
                    item = seed.get(BuylistItem, self.item_id)
                    item.price = initial[-1]
                    item.price_history = [
                        {"price": value, "at": f"2026-01-{value:02d}T00:00:00+00:00", "currency": "USD"}
                        for value in initial
                    ]
                    seed.commit()
                with self.factory() as first, self.factory() as second:
                    first_item = first.get(BuylistItem, self.item_id)
                    stale_item = second.get(BuylistItem, self.item_id)
                    self.assertEqual(stale_item.price_history, first_item.price_history)
                    values = [initial[-1] + 1, initial[-1] + 2]
                    with patch("app.main.get_pricing", side_effect=[
                        PricingResult(value, value / 2, value, "USD") for value in values
                    ]):
                        self.assertTrue(main._refresh_price(first_item))
                        first.commit()
                        self.assertTrue(main._refresh_price(stale_item))
                        second.commit()
                with self.factory() as verify:
                    saved = verify.get(BuylistItem, self.item_id)
                    self.assertEqual([p["price"] for p in saved.price_history], (initial + values)[-10:])
                    self.assertEqual(
                        (saved.price, saved.suggested_price, saved.price_sample_size, saved.currency),
                        (values[-1], values[-1] / 2, values[-1], "USD"),
                    )
                    self.assertEqual(
                        saved.price_history[-1]["at"],
                        saved.price_updated_at.replace(tzinfo=dt.timezone.utc).isoformat(),
                    )


if __name__ == "__main__":
    unittest.main()
