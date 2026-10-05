import copy
import json
import unittest
from unittest.mock import patch

from app.providers.flesh_and_blood import FleshAndBloodProvider
from app import export
from app.importer import parse_list, resolve_list
from app.models import BuylistItem
from test_catalogue import CARD


class ProviderTests(unittest.TestCase):
    def test_catalogue_variants_and_multiple_treatments_survive_import_export(self):
        card = copy.deepcopy(CARD)
        card["printings"][1]["treatments"] = ["Alternate Art", "Extended Art"]
        card["printings"][1]["print"] = "PEN097-Rainbow-Alternate Art-Extended Art"
        with patch("app.providers.flesh_and_blood.fabrary") as catalogue:
            catalogue.get_card.return_value = card
            catalogue.search_cards.return_value = [card]
            provider = FleshAndBloodProvider()
            printings = provider.printings("doomsaying-red")
            self.assertEqual(len(printings), 2)
            self.assertNotEqual(printings[0].identifier, printings[1].identifier)
            self.assertEqual(printings[0].identifier, "fab:PEN097")
            self.assertEqual(json.loads(printings[1].treatment), ["Alternate Art", "Extended Art"])
            self.assertIn("Alternate Art", printings[1].label)
            self.assertNotIn("[", printings[1].label)
            self.assertEqual(printings[1].price_source_id, "677622")
            lines = resolve_list(parse_list("2x RF EA Doomsaying"), provider)
            self.assertEqual(lines[0].status, "matched")
            self.assertTrue(lines[0].printing["alt_art"])
            item = BuylistItem(card_name="Doomsaying", quantity=2, foiling="Rainbow",
                               treatment=lines[0].printing["treatment"])
            self.assertEqual(export.reimport_text([item]), "2x RF EA Doomsaying")
            self.assertEqual(export.display_printing(item), "RF EA")
            item.treatment = "Extended Art"  # previously saved scalar data
            self.assertEqual(export.display_printing(item), "RF EA")


if __name__ == "__main__":
    unittest.main()
