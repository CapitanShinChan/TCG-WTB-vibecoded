"""Export-only pricing presentation; saved suggestions remain unchanged."""
import unittest

from app import export
from app.models import BuylistItem


def card(suggested=0.0, *, code="PEN001", set_code="PEN"):
    return BuylistItem(game="flesh-and-blood", card_identifier=code,
                       card_name="Example Card", printing_id=code,
                       set_code=set_code, foiling="Rainbow", quantity=3,
                       price=2.0, suggested_price=suggested)


class ExportPresentationTests(unittest.TestCase):
    def test_only_exact_zero_is_replaced_not_missing_or_small_positive_prices(self):
        for value, suffix in [(None, ""), (0.01, " 0.01$"), (0.49, " 0.49$"),
                              (0.5, " 0.5$"), (3.0, " 3$"), (-0.0, " 0.5$")]:
            with self.subTest(value=value):
                row = card(value)
                self.assertEqual(export.card_line(row, with_price=True), "3x RF Example Card" + suffix)
                self.assertEqual(row.suggested_price, value)
                self.assertEqual(export.card_line(row, with_price=False), "3x RF Example Card")

    def test_price_filters_still_use_saved_prices_not_export_asking_price(self):
        row = card()
        self.assertEqual(export.filter_items([row], price_max=0), [row])
        self.assertEqual(export.filter_items([row], price_min=0.5), [])
        self.assertEqual(export.filter_items([row], price_basis="current", price_min=2), [row])

    def test_gem_headers_match_wrapper_colors_for_legacy_and_canonical_ids(self):
        packs = [("GEM001", "GEM1", "🔴"), ("fab:GEM033-Rainbow", "GEM2", "🔵"),
                 ("GEM069", "GEM3", "🔴🔵"), ("fab:GEM105-Cold", "GEM4", "⚪"),
                 ("GEM141", "GEM5", "🔵🟣"), ("GEM219", "GEM6", "🟣")]
        rows = [card(code=code, set_code="GEM") for code, _, _ in packs]
        text = export.discord_text(list(reversed(rows)))
        headers = [line for line in text.splitlines() if " GEM" in line]
        self.assertEqual(headers, [f"{emoji} {name}" for _, name, emoji in packs])
        self.assertEqual([row.set_code for row in rows], ["GEM"] * 6)
        self.assertEqual(export.reimport_text(rows), "\n".join(["3x RF Example Card"] * 6))

    def test_unmapped_sets_keep_box_icon(self):
        for code, set_name in [("PEN001", "PEN"), ("GEM220", "GEM"),
                               ("GEM220", "GEM7"), ("PEN001", None)]:
            with self.subTest(set_name=set_name):
                row = card(code=code, set_code=set_name)
                self.assertIn(f"📦 {set_name or 'Others'}\n", export.discord_text([row]))

    def test_other_games_do_not_receive_fab_pack_icons(self):
        row = card(code="GEM001", set_code="GEM1")
        row.game = "another-game"
        self.assertIn("📦 GEM1\n", export.discord_text([row]))
        mixed = [card(code="GEM001", set_code="GEM"), row]
        self.assertIn("📦 GEM1\n", export.discord_text(mixed))

    def test_zero_suggestion_exports_as_fifty_cents_per_card_without_mutation(self):
        row = card()
        self.assertEqual(export.card_line(row, with_price=True), "3x RF Example Card 0.5$")
        self.assertIn("3x RF Example Card 0.5$", export.discord_text([row]))
        self.assertEqual(row.suggested_price, 0.0)
        self.assertEqual(row.price, 2.0)
        self.assertEqual(row.quantity, 3)
        self.assertEqual(export.reimport_text([row]), "3x RF Example Card")


if __name__ == "__main__":
    unittest.main()
