"""Offline browser checks for named-buylist editing and confirmed deletion."""
import mimetypes
import os
import unittest
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright, expect
from card_preview_browser import ART, ROOT, ITEM, render


class BuylistManagementBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        options = {"headless": True}
        if os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE"):
            options["executable_path"] = os.environ["PLAYWRIGHT_CHROMIUM_EXECUTABLE"]
        cls.browser = cls.playwright.chromium.launch(**options)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1280, "height": 900})
        self.addCleanup(self.page.close)
        self.lists = [{"id": 1, "name": "Dani"}, {"id": 2, "name": 'Deck <Red> & "Foil"'}]
        self.posts = []
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.route("**/*", self.route)

    def route(self, route):
        path = urlparse(route.request.url).path
        if route.request.method == "POST" and path in ("/lists/rename", "/lists/delete"):
            data = parse_qs(route.request.post_data)
            self.posts.append((path, data))
            target = next(item for item in self.lists if str(item["id"]) == data["list_id"][0])
            if path == "/lists/rename":
                if data["name"][0].strip() == "Dani":
                    route.fulfill(status=409, json={"detail": "That name already exists"})
                    return
                target["name"] = data["name"][0].strip()
            else:
                self.lists.remove(target)
            route.fulfill(status=200, body="Saved")
        elif path in ("/", "/buylist", "/partials/buylist"):
            scope = parse_qs(urlparse(route.request.url).query).get("scope", ["all"])[0]
            template = {"/": "index.html", "/buylist": "buylist.html", "/partials/buylist": "_buylist_table.html"}[path]
            route.fulfill(body=render(template, [ITEM], scope=scope, lists=self.lists), content_type="text/html")
        elif path.startswith("/static/"):
            asset = ROOT / "app" / path.lstrip("/")
            route.fulfill(body=asset.read_bytes(), content_type=mimetypes.guess_type(asset.name)[0] or "text/plain")
        elif path == "/test-card.svg":
            route.fulfill(body=ART, content_type="image/svg+xml")
        elif path == "/api/catalogue-status":
            route.fulfill(json={"available": True, "stale": False, "persistent": True})
        else:
            route.abort()

    def test_delete_requires_confirmation_and_removes_only_selected_list(self):
        original = [dict(item) for item in self.lists]
        for path in ("/", "/buylist"):
            with self.subTest(page=path):
                self.lists = [dict(item) for item in original]
                self.posts.clear()
                self.page.goto("https://inventory.test" + path + "?scope=2")
                if path == "/":
                    self.page.locator("#query").fill("keep search")
                trigger = self.page.get_by_role("button", name="Delete buylist", exact=True)
                expect(trigger).to_be_visible(timeout=2000)
                trigger.click()
                dialog = self.page.get_by_role("dialog", name="Delete buylist", exact=True)
                expect(dialog).to_be_visible()
                expect(dialog).to_contain_text('Deck <Red> & "Foil"')
                expect(dialog).to_contain_text("all its card entries")
                expect(dialog.get_by_role("button", name="Cancel", exact=True)).to_be_focused()
                self.assertEqual(self.posts, [])
                if os.getenv("CARD_INVENTORY_MANAGEMENT_SCREENSHOT"):
                    self.page.screenshot(path=os.environ["CARD_INVENTORY_MANAGEMENT_SCREENSHOT"])
                dialog.get_by_role("button", name="Cancel", exact=True).click()
                expect(dialog).not_to_be_visible()
                self.assertEqual(self.posts, [])
                trigger.click()
                dialog.get_by_role("button", name="Delete buylist and cards", exact=True).click()
                expect(dialog).not_to_be_visible()
                expect(self.page.locator(".buylist-scope")).to_have_value("all")
                self.assertEqual(self.posts, [("/lists/delete", {"list_id": ["2"], "mode": ["delete"]})])
                self.assertEqual(self.lists, [{"id": 1, "name": "Dani"}])
                self.assertEqual(urlparse(self.page.url).path, path)
                if path == "/":
                    expect(self.page.locator("#query")).to_have_value("keep search")
                self.assertEqual(self.errors, [])

    def test_inline_rename_updates_selected_add_destination(self):
        self.page.goto("https://inventory.test/?scope=2")
        destination = self.page.locator("#qty-list")
        destination.select_option("2", force=True)
        self.page.get_by_role("button", name="Edit buylist", exact=True).click()
        dialog = self.page.get_by_role("dialog", name="Edit buylist", exact=True)
        name = dialog.get_by_label("Name", exact=True)
        name.fill("Dani")
        dialog.get_by_role("button", name="Save changes").click()
        expect(dialog.get_by_role("alert")).to_contain_text("already exists")
        expect(destination.locator('option[value="2"]')).to_have_text('Deck <Red> & "Foil"')
        name.fill('Updated <Deck> & "Foil"')
        dialog.get_by_role("button", name="Save changes").click()
        expect(dialog).not_to_be_visible()
        expect(destination.locator('option[value="2"]')).to_have_text('Updated <Deck> & "Foil"')
        expect(destination).to_have_value("2")
        expect(destination.locator('option[value="1"]')).to_have_text("Dani")
        self.assertEqual(self.page.url, "https://inventory.test/?scope=2")
        self.assertEqual(self.errors, [])

    def test_inline_rename_then_delete_synchronizes_add_destination_before_refresh(self):
        original = [dict(item) for item in self.lists]
        self.page.route("**/buylist/add", lambda route: route.fulfill(status=200, body="Added"))
        for refresh_status in (200, 503):
            for selected in ("2", "1", "general"):
                with self.subTest(refresh_status=refresh_status, selected=selected):
                    self.lists = [dict(item) for item in original]
                    self.posts.clear()
                    self.page.unroute("**/partials/buylist?scope=all")
                    if refresh_status == 503:
                        self.page.route("**/partials/buylist?scope=all",
                                        lambda route: route.fulfill(status=503, body="Unavailable"))
                    self.page.goto("https://inventory.test/?scope=2")
                    self.page.locator("#query").fill("keep search")
                    destination = self.page.locator("#qty-list")
                    destination.select_option(selected, force=True)
                    self.page.get_by_role("button", name="Edit buylist", exact=True).click()
                    dialog = self.page.get_by_role("dialog", name="Edit buylist", exact=True)
                    dialog.get_by_label("Name", exact=True).fill("Renamed deck")
                    dialog.get_by_role("button", name="Save changes").click()
                    expect(dialog).not_to_be_visible()
                    expect(destination.locator('option[value="2"]')).to_have_text("Renamed deck")
                    self.page.evaluate("""() => {
                      const original = window.fetch;
                      window.fetch = (url, options) => {
                        if (String(url) === '/partials/buylist?scope=all') {
                          const select = document.getElementById('qty-list');
                          window.destinationAtRefresh = {
                            value: select.value,
                            options: Array.from(select.options, option => option.value)
                          };
                        }
                        return original(url, options);
                      };
                    }""")
                    self.page.get_by_role("button", name="Delete buylist", exact=True).click()
                    dialog = self.page.get_by_role("dialog", name="Delete buylist", exact=True)
                    expect(dialog).to_contain_text("Renamed deck")
                    dialog.get_by_role("button", name="Delete buylist and cards", exact=True).click()
                    expect(dialog).not_to_be_visible()
                    if refresh_status == 503:
                        expect(self.page.locator("#buylist-container")).to_contain_text(
                            "Buylist deleted. Reload this page")
                    else:
                        expect(self.page.locator(".buylist-scope")).to_have_value("all")
                    expected_target = "general" if selected == "2" else selected
                    self.assertEqual(self.page.evaluate("window.destinationAtRefresh"), {
                        "value": expected_target, "options": ["general", "1"]})
                    expect(destination.locator("option")).to_have_text(["General buylist", "Dani"])
                    expect(destination).to_have_value(expected_target)
                    expect(self.page.locator("#query")).to_have_value("keep search")
                    self.assertEqual(self.posts[-1], (
                        "/lists/delete", {"list_id": ["2"], "mode": ["delete"]}))
                    self.page.evaluate("""() => openQtyPrompt(
                        {identifier: 'test-card', name: 'Test card'},
                        {identifier: 'test-printing', label: 'Test printing'})""")
                    with self.page.expect_request("**/buylist/add") as addition:
                        self.page.get_by_role("button", name="Add", exact=True).click()
                    self.assertEqual(addition.value.method, "POST")
                    self.assertIn(f'name="target_list"\r\n\r\n{expected_target}\r\n', addition.value.post_data)
                    expect(self.page.locator("#qty-overlay")).not_to_be_visible()
                    self.assertEqual(self.page.url, "https://inventory.test/?scope=all")
                    self.assertEqual(self.errors, [])

    def test_edit_freezes_submitted_name_while_saving(self):
        self.page.goto("https://inventory.test/buylist?scope=2")
        self.page.get_by_role("button", name="Edit buylist", exact=True).click()
        dialog = self.page.get_by_role("dialog", name="Edit buylist", exact=True)
        name = dialog.get_by_label("Name", exact=True)
        name.fill("Submitted name")
        self.page.evaluate("""() => {
          const original = window.fetch;
          window.fetch = (url, options) => String(url) === '/lists/rename'
            ? new Promise(resolve => { window.resolveRename = resolve; }) : original(url, options);
        }""")
        dialog.get_by_role("button", name="Save changes").click()
        expect(name).to_be_disabled(timeout=2000)
        self.page.keyboard.press("Escape")
        expect(dialog).to_be_visible()
        self.page.evaluate("window.resolveRename(new Response('Saved'))")
        expect(dialog).not_to_be_visible()
        expect(self.page.locator('.buylist-scope option[value="2"]')).to_have_text("Submitted name")
        self.assertEqual(self.errors, [])

    def test_protected_views_and_refreshed_empty_named_list(self):
        for scope in ("all", "general"):
            self.page.goto("https://inventory.test/buylist?scope=" + scope)
            self.assertEqual(self.page.get_by_role("button", name="Edit buylist", exact=True).count(), 0)
            self.assertEqual(self.page.get_by_role("button", name="Delete buylist", exact=True).count(), 0)
        self.page.goto("https://inventory.test/?scope=all")
        self.page.locator("#buylist-container").evaluate(
            "(el, html) => { el.innerHTML = html; }", render("_buylist_table.html", [], scope="2", lists=self.lists))
        self.page.get_by_role("button", name="Edit buylist", exact=True).click()
        expect(self.page.get_by_role("dialog", name="Edit buylist", exact=True)).to_be_visible()
        self.page.keyboard.press("Escape")
        expect(self.page.locator("#buylist-editor")).not_to_be_visible()
        self.page.get_by_role("button", name="Delete buylist", exact=True).click()
        expect(self.page.get_by_role("dialog", name="Delete buylist", exact=True)).to_be_visible()
        self.page.keyboard.press("Escape")
        self.assertEqual(self.posts, [])
        self.assertEqual(self.errors, [])

    def test_delete_failure_keeps_confirmation_and_allows_cancel(self):
        self.page.goto("https://inventory.test/buylist?scope=2")
        self.page.route("**/lists/delete", lambda route: route.fulfill(status=500, json={"detail": "Deletion rejected"}))
        self.page.get_by_role("button", name="Delete buylist", exact=True).click()
        dialog = self.page.get_by_role("dialog", name="Delete buylist", exact=True)
        dialog.get_by_role("button", name="Delete buylist and cards", exact=True).click()
        expect(dialog.get_by_role("alert")).to_contain_text("Deletion rejected")
        expect(dialog.get_by_role("button", name="Cancel", exact=True)).to_be_enabled()
        expect(self.page.locator(".buylist-scope")).to_have_value("2")
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        expect(dialog).not_to_be_visible()
        self.assertEqual(len(self.lists), 2)
        self.assertEqual(self.errors, [])

    def test_deleted_entries_are_not_actionable_if_view_refresh_fails(self):
        self.page.goto("https://inventory.test/?scope=2")
        self.page.route("**/partials/buylist?scope=all", lambda route: route.fulfill(status=503, body="Unavailable"))
        self.page.get_by_role("button", name="Delete buylist", exact=True).click()
        self.page.get_by_role("button", name="Delete buylist and cards", exact=True).click()
        expect(self.page.locator("#buylist-editor")).not_to_be_visible()
        expect(self.page.locator("#buylist-container")).to_contain_text("Buylist deleted. Reload this page")
        self.assertEqual(self.page.locator("#buylist-container button").count(), 0)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.errors, [])

    def test_edit_keeps_selected_buylist_and_handles_name_conflicts(self):
        self.page.goto("https://inventory.test/buylist?scope=2")
        edit = self.page.get_by_role("button", name="Edit buylist", exact=True)
        expect(edit).to_be_visible(timeout=2000)
        edit.click()
        dialog = self.page.get_by_role("dialog", name="Edit buylist", exact=True)
        expect(dialog).to_be_visible(timeout=3000)
        name = dialog.get_by_label("Name", exact=True)
        expect(name).to_have_value('Deck <Red> & "Foil"')
        name.fill("Dani")
        dialog.get_by_role("button", name="Save changes").click()
        expect(dialog.get_by_role("alert")).to_contain_text("already exists")
        expect(dialog).to_be_visible()
        name.fill("Updated deck")
        dialog.get_by_role("button", name="Save changes").click()
        expect(dialog).not_to_be_visible()
        expect(self.page.locator(".buylist-scope")).to_have_value("2")
        expect(self.page.locator('.buylist-scope option[value="2"]')).to_have_text("Updated deck")
        self.assertEqual(self.page.url, "https://inventory.test/buylist?scope=2")
        self.assertEqual(self.posts[-1], ("/lists/rename", {"list_id": ["2"], "name": ["Updated deck"]}))
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
