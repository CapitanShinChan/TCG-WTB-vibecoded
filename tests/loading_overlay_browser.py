"""Offline loading-dialog regression tests with real templates and JavaScript."""
import mimetypes
import os
from pathlib import Path
import unittest
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect
from card_preview_browser import ART, ROOT, render


class LoadingOverlayBrowserTests(unittest.TestCase):
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
        self.errors = []
        self.requests = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.route("**/*", self.route)
        self.page.add_init_script("""(() => {
          const original = window.fetch;
          window.fetch = (url, options) => {
            if (String(url).startsWith('/test-progress')) {
              window.fetchCount = (window.fetchCount || 0) + 1;
              return new Promise((resolve, reject) => {
                window.resolveFetch = resolve;
                window.rejectFetch = reject;
              });
            }
            return original(url, options);
          };
        })();""")

    def route(self, route):
        path = urlparse(route.request.url).path
        self.requests.append((route.request.method, path))
        if path in ("/", "/buylist", "/import"):
            template = {"/": "index.html", "/buylist": "buylist.html", "/import": "import.html"}[path]
            route.fulfill(body=render(template), content_type="text/html")
        elif path == "/partials/buylist":
            route.fulfill(body=render("_buylist_table.html"), content_type="text/html")
        elif path.startswith("/static/"):
            asset = ROOT / "app" / path.lstrip("/")
            route.fulfill(body=asset.read_bytes(), content_type=mimetypes.guess_type(asset.name)[0] or "text/plain")
        elif path == "/test-card.svg":
            route.fulfill(body=ART, content_type="image/svg+xml")
        elif path == "/api/catalogue-status":
            route.fulfill(json={"available": True, "stale": False, "persistent": True})
        else:
            route.abort()

    def start(self):
        self.page.goto("https://inventory.test/buylist")
        self.page.locator(".refresh-all").focus()
        self.page.evaluate("""() => {
          window.finished = false;
          window.streamProgress('/test-progress', {}, {title: 'Updating prices'})
            .then(() => { window.finished = true; })
            .catch(error => { window.failure = error.message; });
        }""")

    def open_stream(self):
        self.page.evaluate("""() => {
          window.resolveFetch(new Response(new ReadableStream({
            start(controller) { window.progressController = controller; }
          }), {headers: {'Content-Type': 'text/event-stream'}}));
        }""")

    def event(self, data):
        self.page.evaluate("data => window.progressController.enqueue(new TextEncoder().encode('data: ' + JSON.stringify(data) + '\\n\\n'))", data)

    def test_errors_release_the_modal_and_report_failure(self):
        cases = {
            "http": "window.resolveFetch(new Response(JSON.stringify({detail: 'Provider unavailable'}), {status: 503, headers: {'Content-Type': 'application/json'}}))",
            "network": "window.rejectFetch(new TypeError('Network disconnected'))",
            "truncated": "window.resolveFetch(new Response('data: {\"type\":\"progress\",\"done\":1,\"total\":2}\\n\\n'))",
            "server": "window.resolveFetch(new Response('data: {\"type\":\"error\",\"message\":\"Provider unavailable\"}\\n\\n'))",
            "malformed": "window.resolveFetch(new Response('data: broken-json\\n\\n'))",
        }
        for kind, action in cases.items():
            with self.subTest(failure=kind):
                self.start()
                self.page.evaluate(action)
                self.page.wait_for_function("window.finished || window.failure")
                self.assertTrue(self.page.evaluate("Boolean(window.failure)"), "Failed requests must not report success")
                expect(self.page.locator("#progress")).not_to_be_visible()
                expect(self.page.locator("html")).not_to_have_class("progress-open")
                expect(self.page.locator(".refresh-all")).to_be_focused()
                self.assertEqual(self.errors, [])

    def test_duplicate_operation_does_not_unlock_the_active_dialog(self):
        self.start()
        self.page.evaluate("""() => {
          window.streamProgress('/test-progress-second', {})
            .catch(error => { window.secondFailure = error.message; });
        }""")
        self.assertEqual(self.page.evaluate("window.fetchCount"), 1)
        expect(self.page.locator("#progress")).to_be_visible()
        self.page.wait_for_function("Boolean(window.secondFailure)")
        self.page.evaluate("window.rejectFetch(new TypeError('Test cleanup'))")
        expect(self.page.locator("#progress")).not_to_be_visible()

    def test_single_price_refresh_uses_modal_once_on_both_table_views(self):
        for path in ("/", "/buylist"):
            with self.subTest(page=path):
                self.page.goto("https://inventory.test" + path)
                self.page.evaluate("""() => {
                  const original = window.fetch;
                  window.fetchCount = 0;
                  window.fetch = (url, options) => {
                    if (new URL(url, location.href).pathname === '/buylist/refresh-price') {
                      window.fetchCount++;
                      return new Promise(resolve => { window.resolvePrice = resolve; });
                    }
                    return original(url, options);
                  };
                }""")
                self.page.locator('form[action="/buylist/refresh-price"] button').first.click()
                expect(self.page.get_by_role("dialog", name="Updating prices", exact=True)).to_be_visible(timeout=3000)
                self.assertEqual(self.page.evaluate("window.fetchCount"), 1)
                self.page.evaluate("window.resolvePrice(new Response(JSON.stringify({detail: 'Test provider failure'}), {status: 502, headers: {'Content-Type':'application/json'}}))")
                expect(self.page.locator("#progress")).not_to_be_visible()
                expect(self.page.get_by_role("alert")).to_contain_text("Test provider failure")
                self.assertEqual(self.errors, [])

    def test_successful_price_refreshes_update_both_table_views(self):
        for path in ("/", "/buylist"):
            for bulk in (False, True):
                with self.subTest(page=path, bulk=bulk):
                    self.page.goto("https://inventory.test" + path)
                    self.page.evaluate("""() => {
                      const original = window.fetch;
                      window.fetchCount = 0;
                      window.fetch = (url, options) => {
                        if (new URL(url, location.href).pathname.startsWith('/buylist/refresh-')) {
                          window.fetchCount++;
                          return new Promise(resolve => { window.resolveFetch = resolve; });
                        }
                        return original(url, options);
                      };
                    }""")
                    selector = '.refresh-all' if bulk else 'form[action="/buylist/refresh-price"] button'
                    self.page.locator(selector).first.click()
                    expect(self.page.locator("#progress")).to_be_visible()
                    self.assertEqual(self.page.evaluate("window.fetchCount"), 1)
                    expected_path = "/partials/buylist" if path == "/" else "/buylist"
                    with self.page.expect_request(lambda req: req.method == "GET" and urlparse(req.url).path == expected_path):
                        if bulk:
                            self.open_stream()
                            self.event({"type": "progress", "done": 2, "total": 2})
                            self.event({"type": "result", "refreshed": 2})
                            self.page.evaluate("window.progressController.close()")
                        else:
                            self.page.evaluate("window.resolveFetch(new Response('OK'))")
                    expect(self.page.locator("#progress")).not_to_be_visible()
                    expect(self.page.locator(".refresh-all")).to_be_visible()
                    self.assertEqual(self.errors, [])

    def test_import_uses_matching_copy_and_restores_its_controls(self):
        self.page.goto("https://inventory.test/import")
        self.page.evaluate("""() => {
          const original = window.fetch;
          window.fetch = (url, options) => String(url) === '/api/import/preview-stream'
            ? new Promise(resolve => { window.resolveFetch = resolve; }) : original(url, options);
        }""")
        self.page.locator("#import-text").fill("1x Doomsaying")
        self.page.locator("#preview-btn").click()
        expect(self.page.get_by_role("dialog", name="Checking card list", exact=True)).to_be_visible(timeout=3000)
        self.open_stream()
        self.event({"type": "progress", "done": 1, "total": 1})
        self.event({"type": "result", "lines": []})
        self.page.evaluate("window.progressController.close()")
        expect(self.page.locator("#progress")).not_to_be_visible()
        expect(self.page.locator("#preview-btn")).to_be_enabled()
        expect(self.page.locator("#preview-section")).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_mobile_layout_and_reduced_motion(self):
        for width, height in [(390, 844), (844, 390)]:
            with self.subTest(viewport=(width, height)):
                self.page.set_viewport_size({"width": width, "height": height})
                self.page.emulate_media(reduced_motion="reduce")
                self.start()
                dialog = self.page.locator("#progress")
                expect(dialog).to_be_visible()
                box = dialog.bounding_box()
                self.assertGreaterEqual(box["x"], 16)
                self.assertGreaterEqual(box["y"], 16)
                self.assertLessEqual(box["x"] + box["width"], width - 16)
                self.assertLessEqual(box["y"] + box["height"], height - 16)
                self.assertEqual(self.page.locator(".progress-icon svg").evaluate("el => getComputedStyle(el).animationName"), "none")
                self.assertEqual(self.page.locator("#progress-fill").evaluate("el => getComputedStyle(el).animationName"), "none")
                self.assertIsNone(self.page.get_by_role("progressbar").get_attribute("aria-valuenow"))
                self.page.evaluate("window.rejectFetch(new TypeError('Test cleanup'))")
                expect(dialog).not_to_be_visible()
        self.assertEqual(self.errors, [])

    def test_centered_green_dialog_blocks_background_until_completion(self):
        self.start()
        dialog = self.page.get_by_role("dialog", name="Updating prices", exact=True)
        expect(dialog).to_be_visible(timeout=3000)
        box = dialog.bounding_box()
        self.assertAlmostEqual(box["x"] + box["width"] / 2, 640, delta=2)
        self.assertAlmostEqual(box["y"] + box["height"] / 2, 450, delta=2)
        self.assertLess(box["width"], 500)
        self.assertIn("grayscale", dialog.evaluate("el => getComputedStyle(el, '::backdrop').backdropFilter"))
        self.assertEqual(self.page.locator("html").evaluate("el => getComputedStyle(el).overflow"), "hidden")
        self.page.keyboard.press("Escape")
        self.page.mouse.click(30, 25)
        expect(dialog).to_be_visible()
        self.assertEqual(self.page.url, "https://inventory.test/buylist")
        self.page.locator(".brand").evaluate("el => el.focus()")
        self.assertFalse(self.page.locator(".brand").evaluate("el => document.activeElement === el"))
        for _ in range(3):
            self.page.keyboard.press("Tab")
            self.assertFalse(self.page.evaluate("document.activeElement.closest('header, main') !== null"))

        self.open_stream()
        self.event({"type": "progress", "done": 3, "total": 8})
        expect(self.page.get_by_role("progressbar")).to_have_attribute("aria-valuenow", "38")
        expect(dialog).to_contain_text("3 of 8")
        color = self.page.locator("#progress-fill").evaluate("el => getComputedStyle(el).backgroundColor")
        self.assertEqual(color, "rgb(74, 222, 128)")
        if os.getenv("CARD_INVENTORY_LOADING_SCREENSHOT"):
            self.page.screenshot(path=os.environ["CARD_INVENTORY_LOADING_SCREENSHOT"])
        self.event({"type": "result", "refreshed": 8})
        self.page.evaluate("window.progressController.close()")
        expect(dialog).not_to_be_visible()
        self.page.wait_for_function("window.finished === true")
        expect(self.page.locator("html")).not_to_have_class("progress-open")
        expect(self.page.locator(".refresh-all")).to_be_focused()
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
