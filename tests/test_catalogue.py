"""Catalogue tests use synthetic fixtures, never the live provider."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.fabrary.client import FabraryClient, FabraryError


CARD = {
    "cardIdentifier": "doomsaying-red", "name": "Doomsaying",
    "defaultImage": "PEN097", "sets": ["Compendium of Rathe"],
    "rarities": ["Majestic"],
    "printings": [
        {"identifier": "PEN097", "print": "PEN097", "image": "PEN097",
         "set": "Compendium of Rathe", "rarity": "Majestic",
         "tcgplayer": {"productId": "677622", "url": "https://www.tcgplayer.com/product/677622"}},
        {"identifier": "PEN097", "print": "PEN097-Rainbow", "image": "PEN097-RF",
         "set": "Compendium of Rathe", "foiling": "Rainbow", "rarity": "Majestic",
         "tcgplayer": {"productId": "677622"}},
    ],
}


def response(payload):
    result = Mock()
    result.status_code = 200
    result.json.return_value = copy.deepcopy(payload)
    return result


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.getenv("CARD_INVENTORY_TEST_TMP"))
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "catalogue.json"

    def test_download_search_lookup_and_persist(self):
        with patch("app.fabrary.client.logged_request", side_effect=[
            response({"latestCardsVersion": "5.2.3"}), response({"cards": [CARD]}),
        ]) as request:
            client = FabraryClient(cache_path=self.path)
            self.assertEqual([c["cardIdentifier"] for c in client.search_cards("  DOOM  ")],
                             ["doomsaying-red"])
            self.assertEqual(client.get_card("doomsaying-red")["printings"], CARD["printings"])
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args_list[0].args[0], "GET")
            self.assertTrue(request.call_args_list[1].args[1].endswith("cards-5.2.3.json"))
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["version"], "5.2.3")
        self.assertEqual(saved["cards"], [CARD])


    def test_restart_uses_fresh_disk_cache_without_network(self):
        self.path.write_text(json.dumps({"version": "5.2.3", "checked_at": 1000,
                                         "cards": [CARD]}), encoding="utf-8")
        with patch("app.fabrary.client.logged_request", side_effect=AssertionError("network")):
            client = FabraryClient(cache_path=self.path, clock=lambda: 1001)
            self.assertEqual(client.search_cards("doom")[0]["name"], "Doomsaying")


    def test_failed_refresh_keeps_last_good_cache_and_throttles_retries(self):
        import requests
        good = json.dumps({"version": "5.2.3", "checked_at": 1, "cards": [CARD]})
        failures = [requests.Timeout("offline"), response({"latestCardsVersion": "../bad"}),
                    response({"latestCardsVersion": "5.2.4"})]
        for failure in failures:
            with self.subTest(failure=repr(failure)):
                self.path.write_text(good, encoding="utf-8")
                with patch("app.fabrary.client.logged_request", side_effect=[
                    failure, response({"cards": [{"name": "broken"}]}),
                ]) as request, self.assertLogs("app.fabrary.client", level="WARNING"):
                    client = FabraryClient(cache_path=self.path, clock=lambda: 10000)
                    self.assertEqual(client.search_cards("doom")[0]["name"], "Doomsaying")
                    calls = request.call_count
                    self.assertTrue(client.status()["stale"])
                    self.assertTrue(client.status()["error"])
                    client.get_card("doomsaying-red")
                    self.assertEqual(request.call_count, calls)
                    self.assertEqual(self.path.read_text(encoding="utf-8"), good)

    def test_cold_offline_failure_is_provider_error_and_retries_are_throttled(self):
        import requests
        with patch("app.fabrary.client.logged_request", side_effect=requests.Timeout("offline")) as req, \
                self.assertLogs("app.fabrary.client", level="WARNING"):
            client = FabraryClient(cache_path=self.path, clock=lambda: 10000)
            for _ in range(2):
                with self.assertRaises(FabraryError):
                    client.search_cards("doom")
            self.assertEqual(req.call_count, 1)
            self.assertFalse(client.status()["available"])


    def test_invalid_optional_fields_do_not_replace_good_catalogue(self):
        good = json.dumps({"version": "5.2.3", "checked_at": 1, "cards": [CARD]})
        for field, value in [("tcgplayer", 7), ("image", []), ("treatments", "")]:
            with self.subTest(field=field):
                bad = copy.deepcopy(CARD)
                bad["printings"][0][field] = value
                self.path.write_text(good, encoding="utf-8")
                with patch("app.fabrary.client.logged_request", side_effect=[
                    response({"latestCardsVersion": "5.2.4"}), response({"cards": [bad]}),
                ]), self.assertLogs("app.fabrary.client", level="WARNING"):
                    client = FabraryClient(cache_path=self.path, clock=lambda: 10000)
                    self.assertEqual(client.get_card("doomsaying-red"), CARD)
                    self.assertTrue(client.status()["stale"])
                self.assertEqual(self.path.read_text(encoding="utf-8"), good)


    def test_corrupt_disk_is_replaced_by_valid_download(self):
        self.path.write_text("{broken", encoding="utf-8")
        with patch("app.fabrary.client.logged_request", side_effect=[
            response({"latestCardsVersion": "5.2.3"}), response({"cards": [CARD]}),
        ]), self.assertLogs("app.fabrary.client", level="WARNING"):
            client = FabraryClient(cache_path=self.path)
            self.assertEqual(client.get_card("doomsaying-red")["name"], "Doomsaying")
        self.assertEqual(json.loads(self.path.read_text())["cards"], [CARD])

    def test_unchanged_version_only_fetches_manifest(self):
        self.path.write_text(json.dumps({"version": "5.2.3", "checked_at": 1,
                                         "cards": [CARD]}), encoding="utf-8")
        with patch("app.fabrary.client.logged_request", return_value=response(
            {"latestCardsVersion": "5.2.3"}
        )) as request:
            client = FabraryClient(cache_path=self.path, clock=lambda: 10000)
            self.assertEqual(client.get_card("doomsaying-red"), CARD)
            self.assertEqual(request.call_count, 1)
            self.assertFalse(client.status()["stale"])

    def test_new_version_replaces_snapshot_and_clears_offline_warning(self):
        import requests
        now = [10000]
        self.path.write_text(json.dumps({"version": "5.2.3", "checked_at": 1,
                                         "cards": [CARD]}), encoding="utf-8")
        updated = copy.deepcopy(CARD)
        updated["name"] = "Updated Doomsaying"
        with patch("app.fabrary.client.logged_request", side_effect=[
            requests.Timeout("offline"), response({"latestCardsVersion": "5.2.4"}),
            response({"cards": [updated]}),
        ]), self.assertLogs("app.fabrary.client", level="WARNING"):
            client = FabraryClient(cache_path=self.path, clock=lambda: now[0])
            self.assertEqual(client.get_card("doomsaying-red"), CARD)
            now[0] += 61
            self.assertEqual(client.get_card("doomsaying-red"), updated)
        self.assertFalse(client.status()["stale"])
        self.assertIsNone(client.status()["error"])
        self.assertEqual(json.loads(self.path.read_text())["version"], "5.2.4")

    def test_atomic_replace_failure_preserves_old_file_and_cleans_staging(self):
        good = json.dumps({"version": "5.2.3", "checked_at": 1, "cards": [CARD]})
        self.path.write_text(good, encoding="utf-8")
        with patch("app.fabrary.client.logged_request", side_effect=[
            response({"latestCardsVersion": "5.2.4"}), response({"cards": [CARD]}),
        ]), patch("app.fabrary.client.os.replace", side_effect=OSError("disk failure")), \
                self.assertLogs("app.fabrary.client", level="WARNING"):
            client = FabraryClient(cache_path=self.path, clock=lambda: 10000)
            self.assertEqual(client.get_card("doomsaying-red"), CARD)
        self.assertEqual(self.path.read_text(), good)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
        self.assertFalse(client.status()["persistent"])
        self.assertFalse(client.status()["stale"])

    def test_concurrent_cold_lookups_download_once_per_process(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier = Barrier(8)
        with patch("app.fabrary.client.logged_request", side_effect=[
            response({"latestCardsVersion": "5.2.3"}), response({"cards": [CARD]}),
        ]) as request:
            client = FabraryClient(cache_path=self.path)
            def lookup(_):
                barrier.wait(timeout=10)
                return client.search_cards("doom")
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lookup, range(8)))
            self.assertTrue(all(r[0]["name"] == "Doomsaying" for r in results))
            self.assertEqual(request.call_count, 2)

    def test_blank_literal_search_unknown_card_and_card_backs(self):
        back = copy.deepcopy(CARD)
        back["cardIdentifier"] = "doomsaying-back"
        back["isCardBack"] = True
        for p in back["printings"]:
            p["print"] += "-back"
        with patch("app.fabrary.client.logged_request", side_effect=[
            response({"latestCardsVersion": "5.2.3"}), response({"cards": [back, CARD]}),
        ]) as request:
            client = FabraryClient(cache_path=self.path)
            self.assertEqual(client.search_cards("   "), [])
            self.assertEqual(request.call_count, 0)
            self.assertEqual(len(client.search_cards("doom")), 1)
            self.assertEqual(client.search_cards("name:doom"), [])
            self.assertIsNone(client.get_card("unknown"))


    def test_cold_disk_failure_serves_memory_and_retries_persistence(self):
        now = [10000]
        with patch("app.fabrary.client.logged_request", side_effect=[
            response({"latestCardsVersion": "5.2.3"}), response({"cards": [CARD]}),
            response({"latestCardsVersion": "5.2.3"}),
        ]) as request:
            client = FabraryClient(cache_path=self.path, clock=lambda: now[0])
            with patch("app.fabrary.client.os.replace", side_effect=PermissionError("read-only")), \
                    self.assertLogs("app.fabrary.client", level="WARNING"):
                self.assertEqual(client.get_card("doomsaying-red"), CARD)
            self.assertFalse(client.status()["persistent"])
            self.assertFalse(client.status()["stale"])
            self.assertTrue(client.status()["error"])
            now[0] += 61
            self.assertEqual(client.get_card("doomsaying-red"), CARD)
            self.assertTrue(client.status()["persistent"])
            self.assertIsNone(client.status()["error"])
            self.assertEqual(request.call_count, 3)  # no second catalogue download


    def test_warm_readers_and_status_do_not_wait_for_network_refresh(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        now = [1001]
        entered, release = Event(), Event()
        self.path.write_text(json.dumps({"version": "5.2.3", "checked_at": 1000,
                                         "cards": [CARD]}), encoding="utf-8")
        client = FabraryClient(cache_path=self.path, clock=lambda: now[0])
        self.assertEqual(client.get_card("doomsaying-red"), CARD)
        now[0] = 10000
        def delayed_request(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(timeout=10))
            return response({"latestCardsVersion": "5.2.3"})
        with patch("app.fabrary.client.logged_request", side_effect=delayed_request) as request:
            with ThreadPoolExecutor(max_workers=3) as pool:
                refreshing = pool.submit(client.get_card, "doomsaying-red")
                try:
                    self.assertTrue(entered.wait(timeout=3))
                    self.assertEqual(pool.submit(client.get_card, "doomsaying-red").result(timeout=1), CARD)
                    self.assertTrue(pool.submit(client.status).result(timeout=1)["stale"])
                finally:
                    release.set()
                self.assertEqual(refreshing.result(timeout=3), CARD)
            self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
