"""HTTP regression tests with an in-memory DB and synthetic CDN responses."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main
from app.db import Base, get_session
from app.fabrary.client import FabraryClient
from app.models import BuylistItem
from test_catalogue import CARD, response


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.getenv("CARD_INVENTORY_TEST_TMP"))
        self.addCleanup(self.tmp.cleanup)
        self.catalogue = FabraryClient(cache_path=Path(self.tmp.name) / "catalogue.json")
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        def session():
            with Session(self.engine, autoflush=False) as db:
                yield db
        main.app.dependency_overrides[get_session] = session
        self.addCleanup(main.app.dependency_overrides.clear)
        for target, value in [
            ("app.main.catalogue", self.catalogue),
            ("app.providers.flesh_and_blood.fabrary", self.catalogue),
            ("app.fabrary.compat.client", self.catalogue),
            ("app.main.is_authorized", lambda _: True),
        ]:
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)
        # No lifespan context: do NOT run startup against the user's DB/logs.
        self.http = TestClient(main.app)
        self.addCleanup(self.http.close)

    def test_search_printings_import_and_catalogue_status(self):
        with patch("app.fabrary.client.logged_request", side_effect=[
            response({"latestCardsVersion": "5.2.3"}), response({"cards": [CARD]}),
        ]) as network:
            for q in ["doom", "doomsaying"]:
                r = self.http.get("/api/search", params={"game": "flesh-and-blood", "q": q})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["results"][0]["name"], "Doomsaying")
            r = self.http.get("/api/printings", params={"game": "flesh-and-blood", "id": "doomsaying-red"})
            self.assertEqual(len(r.json()["printings"]), 2)
            r = self.http.post("/api/import/preview", json={"game": "flesh-and-blood", "text": "2x RF Doomsaying"})
            line = r.json()["lines"][0]
            self.assertEqual(line["status"], "matched")
            r = self.http.post("/api/import/commit", json={"game": "flesh-and-blood", "items": [line, line]})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json(), {"added": 1, "updated": 1})
            with Session(self.engine) as db:
                self.assertEqual(db.scalars(select(BuylistItem)).one().quantity, 4)
            r = self.http.get("/api/catalogue-status")
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["version"], "5.2.3")
            self.assertFalse(r.json()["stale"])
            for url in ["/", "/import", "/buylist", "/lists", "/export"]:
                page = self.http.get(url)
                self.assertEqual(page.status_code, 200, page.text)
                self.assertIn('id="catalogue-warning"', page.text)
            self.assertEqual(network.call_count, 2)


if __name__ == "__main__":
    unittest.main()
