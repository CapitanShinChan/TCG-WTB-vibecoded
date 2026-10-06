"""Offline add-card modal regressions: real templates/assets, no server or DB.

Run: .venv/Scripts/python.exe -B tests/add_card_modal_browser.py
Set PLAYWRIGHT_CHROMIUM_EXECUTABLE to use an already-installed browser.
"""
import mimetypes
import os
import re
import unittest
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright
from card_preview_browser import ART, ENV, ROOT


CARD = {"identifier": "test-card", "name": "Test card", "sets": ["TST"],
        "image": "/test-card.svg"}
PRINTINGS = [
    {"identifier": "test-regular", "label": "TST001 Regular", "set_code": "TST",
     "image": "/test-card.svg", "rarity": "Rare"},
    {"identifier": "test-foil", "label": "TST001 Foil", "set_code": "TST",
     "image": "/test-card.svg", "rarity": "Rare", "foiling": "RF"},
]


def render(template):
    return ENV.get_template(template).render(
        items=[], lists=[{"id": 7, "name": "Test buylist"}], scope="general",
        games=[{"game_id": "fab", "display_name": "Flesh and Blood"}], app_debug=False)


class AddCardModalBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        options = {"headless": True}
        if os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE"):
            options["executable_path"] = os.environ["PLAYWRIGHT_CHROMIUM_EXECUTABLE"]
        cls.browser = cls.playwright.chromium.launch(**options)
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1280, "height": 900},
                                          service_workers="block")
        self.addCleanup(self.page.close)
        self.errors = []
        self.posts = []
        self.hold_add = False
        self.pending_routes = []
        self.unexpected_requests = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.route("**/*", self.route)

    def tearDown(self):
        self.assertEqual(self.errors, [], "No browser JavaScript errors")
        self.assertEqual(self.unexpected_requests, [], "All requests must use offline fixtures")

    def route(self, route):
        request = route.request
        url = urlparse(request.url)
        path = url.path
        if request.method == "POST":
            self.posts.append(request)
        if url.netloc != "inventory.test":
            self.unexpected_requests.append(request.url)
            route.abort()
        elif path == "/":
            route.fulfill(body=render("index.html"), content_type="text/html")
        elif path == "/api/search":
            self.assertEqual(parse_qs(url.query), {"game": ["fab"], "q": [CARD["name"]]})
            route.fulfill(json={"results": [CARD]})
        elif path == "/api/printings":
            self.assertEqual(parse_qs(url.query), {"game": ["fab"], "id": [CARD["identifier"]]})
            route.fulfill(json={"printings": PRINTINGS})
        elif path == "/api/catalogue-status":
            route.fulfill(json={"available": True, "stale": False, "persistent": True})
        elif path == "/buylist/add" and request.method == "POST":
            if self.hold_add:
                self.pending_routes.append(route)
            else:
                route.fulfill(json={"ok": True})
        elif path == "/partials/buylist":
            route.fulfill(body=render("_buylist_table.html"), content_type="text/html")
        elif path == "/test-card.svg":
            route.fulfill(body=ART, content_type="image/svg+xml")
        elif path.startswith("/static/"):
            asset = ROOT / "app" / path.lstrip("/")
            route.fulfill(body=asset.read_bytes(),
                          content_type=mimetypes.guess_type(asset.name)[0] or "text/plain")
        else:
            self.unexpected_requests.append(request.url)
            route.abort()  # Never reach a live app, provider, or external network.

    def search(self):
        self.page.goto("https://inventory.test/")
        self.page.locator("#query").fill(CARD["name"])
        self.page.get_by_role("button", name="Search", exact=True).click()
        expect(self.page.locator("#results .card")).to_have_count(1)

    def open_printings(self):
        self.page.locator("#results .card").click()
        expect(self.page.locator("#modal")).to_be_visible()
        expect(self.page.locator("#printings .add-btn")).to_have_count(len(PRINTINGS))

    def open_quantity(self, index=0):
        self.page.locator("#printings .add-btn").nth(index).click()
        expect(self.page.locator("#qty-overlay")).to_be_visible()
        expect(self.page.locator("#qty-input")).to_be_focused()

    def test_escape_closes_only_topmost_add_overlay_from_each_control(self):
        for selector in ("#qty-input", "#qty-list", "#qty-confirm", "#qty-cancel"):
            with self.subTest(focus=selector):
                self.search()
                self.open_printings()
                self.open_quantity()
                self.page.locator("#qty-input").fill("9")
                self.page.locator(selector).focus()
                expect(self.page.locator(selector)).to_be_focused()
                self.page.keyboard.press("Escape")
                expect(self.page.locator("#qty-overlay")).to_be_hidden()
                expect(self.page.locator("#modal")).to_be_visible()
                self.assertTrue(self.page.evaluate("pendingAdd === null"))
                self.page.keyboard.press("Escape")
                expect(self.page.locator("#modal")).to_be_hidden()
                self.assertEqual(self.posts, [], "Neither Escape may add a card")
                self.open_printings()
                self.open_quantity(index=1)
                expect(self.page.locator("#qty-input")).to_have_value("1")
                expect(self.page.locator("#qty-prompt-label")).to_contain_text(PRINTINGS[1]["label"])
                expect(self.page.locator("#qty-confirm")).to_be_enabled()
                self.page.keyboard.press("Escape")
                self.assertEqual(self.posts, [])

    def test_native_dialogs_keep_escape_without_dismissing_underlying_add_ui(self):
        for quantity_open in (False, True):
            for selector in ("#card-preview", "#buylist-editor", "#progress"):
                with self.subTest(quantity_open=quantity_open, dialog=selector):
                    self.search()
                    self.open_printings()
                    if quantity_open:
                        self.open_quantity()
                    # Stack the real native dialogs above the add flow. Progress
                    # uses its real helper, including its noncancelable handler.
                    if selector == "#progress":
                        self.page.evaluate("""() => {
                            window.withProgress(() => new Promise(resolve => {
                                window.finishTestProgress = resolve;
                            }));
                        }""")
                    else:
                        self.page.locator(selector).evaluate("dialog => dialog.showModal()")
                    expect(self.page.locator(selector)).to_be_visible()
                    self.page.keyboard.press("Escape")
                    expect(self.page.locator("#modal")).to_be_visible()
                    if quantity_open:
                        expect(self.page.locator("#qty-overlay")).to_be_visible()
                    if selector == "#progress":
                        expect(self.page.locator(selector)).to_be_visible()
                        self.page.evaluate("window.finishTestProgress()")
                    expect(self.page.locator(selector)).to_be_hidden()
                    self.page.keyboard.press("Escape")
                    expect(self.page.locator("#qty-overlay" if quantity_open else "#modal")).to_be_hidden()
                    if quantity_open:
                        expect(self.page.locator("#modal")).to_be_visible()
                    self.assertEqual(self.posts, [])

    def test_inflight_add_completion_does_not_close_reopened_prompt(self):
        self.search()
        self.open_printings()
        self.open_quantity()
        self.hold_add = True
        self.page.locator("#qty-confirm").click()
        expect(self.page.locator("#qty-confirm")).to_be_disabled()
        self.page.locator("#qty-cancel").focus()
        self.page.keyboard.press("Escape")
        expect(self.page.locator("#qty-overlay")).to_be_hidden()
        expect(self.page.locator("#modal")).to_be_visible()
        self.assertTrue(self.page.evaluate("pendingAdd === null"))
        self.open_quantity(index=1)
        self.assertEqual(len(self.posts), 1, "Escape cannot create a second POST")
        self.hold_add = False
        self.assertEqual(len(self.pending_routes), 1)
        self.pending_routes.pop().fulfill(json={"ok": True})
        # Waiting for completion distinguishes stale-close bugs from a still
        # unresolved request. Escape dismisses UI; it cannot undo an issued POST.
        expect(self.page.locator("#qty-confirm")).to_have_text("Add")
        expect(self.page.locator("#qty-overlay")).to_be_visible()
        expect(self.page.locator("#qty-input")).to_have_value("1")
        expect(self.page.locator("#qty-prompt-label")).to_contain_text(PRINTINGS[1]["label"])
        self.page.locator("#qty-input").fill("3")
        self.page.locator("#qty-list").select_option("7")
        self.page.locator("#qty-confirm").click()
        expect(self.page.locator("#qty-overlay")).to_be_hidden()
        self.assertEqual(len(self.posts), 2)
        fields = dict(re.findall(r'name="([^\"]+)"\r\n\r\n([^\r]*)', self.posts[-1].post_data))
        self.assertEqual(fields["printing_id"], PRINTINGS[1]["identifier"])
        self.assertEqual(fields["quantity"], "3")
        self.assertEqual(fields["target_list"], "7")

    def test_escape_closes_printing_picker(self):
        self.search()
        for selector in ("#modal-close", "#printings .add-btn", "#query"):
            with self.subTest(focus=selector):
                self.open_printings()
                self.page.locator(selector).first.focus()
                self.page.keyboard.press("Escape")
                expect(self.page.locator("#modal")).to_be_hidden()
                self.assertEqual(self.posts, [], "Escape must not add a card")

    def test_existing_click_dismissals_and_enter_confirmation_still_work(self):
        self.search()
        self.page.keyboard.press("Escape")  # No overlay: leave the page alone.
        expect(self.page.locator("#query")).to_have_value(CARD["name"])
        for dismiss in ("cancel", "backdrop"):
            with self.subTest(dismiss=dismiss):
                self.open_printings()
                self.open_quantity()
                self.page.keyboard.press("Tab")
                expect(self.page.locator("#qty-overlay")).to_be_visible()
                if dismiss == "cancel":
                    self.page.locator("#qty-cancel").click()
                else:
                    self.page.mouse.click(5, 5)
                expect(self.page.locator("#qty-overlay")).to_be_hidden()
                expect(self.page.locator("#modal")).to_be_visible()
                self.assertTrue(self.page.evaluate("pendingAdd === null"))
                if dismiss == "cancel":
                    self.page.locator("#modal-close").click()
                else:
                    self.page.mouse.click(5, 5)
                expect(self.page.locator("#modal")).to_be_hidden()
                self.assertEqual(self.posts, [])
        self.open_printings()
        self.open_quantity()
        self.page.keyboard.press("Escape")
        self.open_quantity(index=1)
        self.page.locator("#qty-input").fill("2")
        self.page.keyboard.press("Enter")
        expect(self.page.locator("#qty-overlay")).to_be_hidden()
        expect(self.page.locator("#modal")).to_be_visible()
        self.assertEqual(len(self.posts), 1)
        fields = dict(re.findall(r'name="([^\"]+)"\r\n\r\n([^\r]*)', self.posts[0].post_data))
        self.assertEqual(fields["printing_id"], PRINTINGS[1]["identifier"])
        self.assertEqual(fields["quantity"], "2")
        self.assertEqual(fields["target_list"], "general")


if __name__ == "__main__":
    unittest.main(verbosity=2)
