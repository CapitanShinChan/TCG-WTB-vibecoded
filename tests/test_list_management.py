"""List-management integration checks against an isolated in-memory database."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.db import Base, get_session
from app.models import BuylistItem, CardList


class ListManagementTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.factory = sessionmaker(bind=engine)
        with self.factory() as db:
            db.add_all([CardList(id=1, name="Dani"), CardList(id=2, name="My deck"), CardList(id=3, name="Empty")])
            for ident, list_id, printing, qty in [(1, 1, "same", 2), (2, 2, "same", 3), (3, None, "same", 4), (4, 2, "other", 1)]:
                db.add(BuylistItem(id=ident, game="flesh-and-blood", list_id=list_id,
                                  card_identifier=printing, printing_id=printing, card_name=printing,
                                  printing_label="Test", quantity=qty, price=2.0, currency="USD",
                                  price_history=[{"price": 2.0, "at": None, "currency": "USD"}]))
            db.commit()
        def session():
            with self.factory() as db:
                yield db
        self.enterContext(patch.dict(main.app.dependency_overrides, {get_session: session}))
        self.enterContext(patch("app.main.is_authorized", return_value=True))
        self.enterContext(patch.object(main.catalogue, "get_card", side_effect=AssertionError("No provider calls allowed")))
        self.http = TestClient(main.app)  # No lifespan/startup against the real DB.
        self.addCleanup(self.http.close)

    def test_rename_preserves_list_identity_and_cards(self):
        response = self.http.post("/lists/rename", data={"list_id": 2, "name": " Updated deck "}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        with self.factory() as db:
            self.assertEqual(db.get(CardList, 2).name, "Updated deck")
            self.assertEqual([(row.id, row.quantity) for row in db.scalars(select(BuylistItem).where(BuylistItem.list_id == 2))], [(2, 3), (4, 1)])
        for name, expected in [("Dani", 409), ("   ", 400)]:
            response = self.http.post("/lists/rename", data={"list_id": 2, "name": name}, follow_redirects=False)
            self.assertEqual(response.status_code, expected)
        with self.factory() as db:
            self.assertEqual(db.get(CardList, 2).name, "Updated deck")

    def test_full_delete_removes_list_and_all_its_entries_only(self):
        response = self.http.post("/lists/delete", data={"list_id": 2, "mode": "delete"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        with self.factory() as db:
            self.assertIsNone(db.get(CardList, 2))
            self.assertIsNotNone(db.get(CardList, 1))
            remaining = list(db.scalars(select(BuylistItem).order_by(BuylistItem.id)))
            self.assertEqual([(row.id, row.list_id, row.quantity) for row in remaining], [(1, 1, 2), (3, None, 4)])
            self.assertTrue(all(row.price_history[0]["price"] == 2.0 for row in remaining))
        response = self.http.post("/lists/delete", data={"list_id": 3, "mode": "delete"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        with self.factory() as db:
            self.assertIsNone(db.get(CardList, 3))

    def test_management_controls_only_target_named_lists_including_empty(self):
        for url in ("/", "/buylist", "/partials/buylist"):
            for scope, count in [("all", 0), ("general", 0), ("2", 1), ("3", 1)]:
                with self.subTest(url=url, scope=scope):
                    response = self.http.get(url, params={"scope": scope})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.text.count("data-edit-buylist"), count)
                    self.assertEqual(response.text.count("data-delete-buylist"), count)


if __name__ == "__main__":
    unittest.main()
