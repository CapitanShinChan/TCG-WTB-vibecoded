"""Export resolves legacy GEM metadata without a restart migration or network."""
import re
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session

from app import export, main
from app.models import BuylistItem, CardList

PACKS = ["GEM1", "GEM2", "GEM3", "GEM4", "GEM5", "GEM6"]
PACK_ICONS = ["🔴", "🔵", "🔴🔵", "⚪", "🔵🟣", "🟣"]


def item(printing, *, game="flesh-and-blood", set_code="GEM", name="Card"):
    return BuylistItem(game=game, card_identifier=printing, card_name=name,
                       printing_id=printing, printing_label="GEM Rainbow",
                       set_code=set_code, foiling="Rainbow", quantity=2, suggested_price=3.0)


class GemExportTests(unittest.TestCase):
    def test_gem_inventory_offers_all_six_packs_even_without_cards_in_each(self):
        rows = [item("fab:GEM141-Rainbow")]
        self.assertEqual(main._export_filter_options(rows)[0], PACKS)
        self.assertEqual(export.filter_items(rows, sets={"GEM6"}), [])

    def test_unknown_codes_and_other_games_keep_their_original_sets(self):
        unknown = item("GEM220")
        other = item("GEM141", game="other-game")
        known = item("GEM141", set_code="GEM1")
        self.assertEqual(export.set_of(unknown), "GEM")
        self.assertEqual(export.set_of(other), "GEM")
        self.assertEqual(export.set_of(known), "GEM5")
        self.assertEqual(main._export_filter_options([unknown, known])[0], ["GEM"] + PACKS)
        self.assertEqual(export.filter_items([unknown, known], sets={"GEM"}), [unknown])
        self.assertEqual(main._export_filter_options([other])[0], ["GEM"])

    def test_empty_and_non_gem_inventory_do_not_get_extra_set_options(self):
        self.assertEqual(main._export_filter_options([]), ([], []))
        self.assertEqual(main._export_filter_options([item("PEN001", set_code="PEN")])[0], ["PEN"])

    def test_legacy_rows_group_and_filter_by_pack_without_being_modified(self):
        rows = [item(code, name=pack) for code, pack in zip(
            ["GEM001", "fab:GEM033-Rainbow", "GEM069", "fab:GEM105-Cold", "GEM141", "GEM219"], PACKS)]
        self.assertEqual([export.set_of(row) for row in rows], PACKS)
        for pack, icon, row in zip(PACKS, PACK_ICONS, rows):
            self.assertEqual(export.filter_items(rows, sets={pack}), [row])
            self.assertIn(icon + " " + pack + "\n", export.discord_text(rows))
        self.assertEqual([row.set_code for row in rows], ["GEM"] * 6)
        self.assertEqual([row.printing_label for row in rows], ["GEM Rainbow"] * 6)


class GemExportHttpTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        with self.factory() as db:
            db.add(CardList(id=2, name="GEMs"))
            for code, name, scope in [("GEM001", "Pack One", None), ("fab:GEM141-Rainbow", "Pack Five", 2),
                                      ("GEM184", "Pack Six", 2), ("PEN001", "Non GEM", 2)]:
                row = item(code, name=name, set_code="PEN" if code == "PEN001" else "GEM")
                row.list_id = scope
                db.add(row)
            db.commit()
        def session():
            with self.factory() as db:
                yield db
        self.enterContext(patch.dict(main.app.dependency_overrides, {get_session: session}))
        self.enterContext(patch("app.main.is_authorized", return_value=True))
        self.http = TestClient(main.app)  # No context manager: never run app startup.
        self.addCleanup(self.http.close)

    def test_export_page_renders_six_gem_checkboxes_for_unmigrated_rows(self):
        response = self.http.get("/export")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(re.findall(r'class="f-set" value="([^"]+)"', response.text), PACKS + ["PEN"])

    def test_api_and_download_filter_legacy_gem_rows_in_the_selected_list(self):
        params = {"sets": "GEM5", "lists": "2"}
        response = self.http.get("/api/export", params=params)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["count"], 1)
        self.assertIn("🔵🟣 GEM5\n2x RF Pack Five 3$", result["discord"])
        self.assertNotIn("Pack One", result["discord"])
        self.assertNotIn("Pack Six", result["discord"])
        self.assertEqual(result["reimport"], "2x RF Pack Five")
        for fmt, expected in [("discord", result["discord"]), ("reimport", result["reimport"])]:
            download = self.http.get("/export/download", params={**params, "fmt": fmt})
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.text, expected)
        with self.factory() as db:
            self.assertEqual([row.set_code for row in db.scalars(select(BuylistItem).order_by(BuylistItem.id))],
                             ["GEM", "GEM", "GEM", "PEN"])

    def test_api_and_download_adjust_zero_only_without_changing_saved_rows(self):
        params = {"sets": "GEM5", "lists": "2"}
        for value, suffix in [(0.0, " 0.5$"), (None, ""), (0.25, " 0.25$"), (3.0, " 3$")]:
            with self.subTest(value=value):
                with self.factory() as db:
                    row = db.scalar(select(BuylistItem).where(BuylistItem.card_name == "Pack Five"))
                    row.suggested_price = value
                    db.commit()
                    before = {column.name: getattr(row, column.name) for column in BuylistItem.__table__.columns}
                response = self.http.get("/api/export", params=params)
                self.assertEqual(response.status_code, 200)
                result = response.json()
                self.assertEqual(result["count"], 1)
                self.assertIn("🔵🟣 GEM5\n2x RF Pack Five" + suffix, result["discord"])
                self.assertEqual(result["discord"].splitlines()[-1], "2x RF Pack Five" + suffix)
                self.assertEqual(result["reimport"], "2x RF Pack Five")
                for fmt in ("discord", "reimport"):
                    download = self.http.get("/export/download", params={**params, "fmt": fmt})
                    self.assertEqual(download.status_code, 200)
                    self.assertEqual(download.text, result[fmt])
                with self.factory() as db:
                    row = db.get(BuylistItem, before["id"])
                    after = {column.name: getattr(row, column.name) for column in BuylistItem.__table__.columns}
                    self.assertEqual(after, before)

    def test_an_empty_pack_in_the_selected_list_exports_no_cards(self):
        response = self.http.get("/api/export", params={"sets": "GEM6", "lists": "general"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 0)
        self.assertEqual(response.json()["reimport"], "")
        self.assertNotIn("GEM6", response.json()["discord"])


if __name__ == "__main__":
    unittest.main()
