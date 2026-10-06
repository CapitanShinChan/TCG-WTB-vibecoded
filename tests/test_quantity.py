"""Quantity changes use an isolated database and never run app startup."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.db import Base, get_session
from app.models import BuylistItem, CardList


class QuantityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        with self.factory() as db:
            db.add_all([CardList(id=1, name="Dani"), CardList(id=2, name="Current list")])
            db.add(BuylistItem(id=1, game="test", card_identifier="card", card_name="Card",
                              printing_id="print", printing_label="Print", list_id=2, quantity=2))
            db.commit()
        def session():
            with self.factory() as db:
                yield db
        self.enterContext(patch.dict(main.app.dependency_overrides, {get_session: session}))
        self.enterContext(patch("app.main.is_authorized", return_value=True))
        self.http = TestClient(main.app)
        self.addCleanup(self.http.close)

    def test_quantity_form_redirect_preserves_selected_scope(self):
        for scope in ("2", "general", "all"):
            with self.subTest(scope=scope):
                response = self.http.post("/buylist/qty", data={"item_id": 1, "delta": -1, "scope": scope}, follow_redirects=False)
                self.assertEqual(response.status_code, 303)
                self.assertEqual(response.headers["location"], f"/buylist?scope={scope}")
                page = self.http.get(response.headers["location"])
                self.assertEqual(page.status_code, 200)
                self.assertIn(f'value="{scope}" selected', page.text)

    def test_quantity_forms_include_the_current_scope(self):
        response = self.http.get("/buylist?scope=2")
        self.assertEqual(response.text.count('name="scope" value="2"'), 2)

    def test_missing_item_is_an_explicit_error(self):
        response = self.http.post("/buylist/qty", headers={"Accept": "application/json"},
                                  data={"item_id": 999, "delta": -1}, follow_redirects=False)
        self.assertEqual(response.status_code, 404)

    def test_scope_cannot_redirect_off_site(self):
        response = self.http.post("/buylist/qty", data={"item_id": 1, "delta": -1, "scope": "//other.test/path"}, follow_redirects=False)
        self.assertEqual(response.headers["location"], "/buylist?scope=%2F%2Fother.test%2Fpath")

    def test_json_quantity_response_does_not_redirect_and_keeps_list(self):
        for delta, expected in [(-1, 1), (-1, 1), (1, 2)]:
            response = self.http.post("/buylist/qty", headers={"Accept": "application/json"},
                                      data={"item_id": 1, "delta": delta}, follow_redirects=False)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"item_id": 1, "quantity": expected})
            with self.factory() as db:
                item = db.get(BuylistItem, 1)
                self.assertEqual((item.quantity, item.list_id), (expected, 2))


if __name__ == "__main__":
    unittest.main()
