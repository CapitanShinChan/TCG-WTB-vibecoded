"""Offline browser regression: real templates/assets, synthetic card art, no DB.

Run: .venv/Scripts/python -B tests/card_preview_browser.py
Requires Playwright and its Chromium browser (see README).
"""
import mimetypes
import os
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
# Direct script execution puts tests/, not the project root, on sys.path.
import sys
sys.path.insert(0, str(ROOT))
from app.pricing.history import sparkline
NAME = 'Doomsaying <Red> & "Foil"'
ART = '<svg xmlns="http://www.w3.org/2000/svg" width="630" height="880"><rect width="630" height="880" fill="#26364a"/><text x="40" y="100" fill="white" font-size="32">Synthetic test card</text></svg>'
ITEM = dict(id=1, card_name=NAME, image_url="/test-card.svg", set_code="PEN",
            printing_label="PEN097 RF", quantity=2, rarity="Rare", price=None,
            suggested_price=None, tcgplayer_url=None)
ENV = Environment(loader=FileSystemLoader(ROOT / "app/templates"), autoescape=select_autoescape())
ENV.filters["printing_code"] = lambda item: item["printing_label"]
ENV.filters["price_sparkline"] = sparkline


def render(template, items=None, *, scope="general", lists=None):
    return ENV.get_template(template).render(
        items=[ITEM, dict(ITEM, id=2, card_name="No image", image_url=None)] if items is None else items,
        lists=lists or [], scope=scope, games=[], app_debug=False)


class CardPreviewBrowserTests(unittest.TestCase):
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
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.route("**/*", self.route)

    def route(self, route):
        path = urlparse(route.request.url).path
        if path in ("/", "/buylist"):
            route.fulfill(body=render("index.html" if path == "/" else "buylist.html"), content_type="text/html")
        elif path == "/test-card.svg":
            route.fulfill(body=ART, content_type="image/svg+xml")
        elif path.startswith("/static/"):
            asset = ROOT / "app" / path.lstrip("/")
            if asset.is_file():
                route.fulfill(body=asset.read_bytes(), content_type=mimetypes.guess_type(asset.name)[0] or "text/plain")
            else:
                route.fulfill(status=404, body="Not found")
        elif path == "/api/catalogue-status":
            route.fulfill(json={"available": True, "stale": False, "persistent": True})
        else:
            route.abort()  # Never reach external APIs or the user's running server.

    def test_thumbnail_and_name_open_centered_preview(self):
        self.page.goto("https://inventory.test/buylist")
        row = self.page.locator("table.buylist tbody tr").first
        triggers = row.locator(".card-preview-trigger")
        self.assertEqual(triggers.count(), 2, "Both thumbnail and name must open a preview")
        for trigger in triggers.all():
            trigger.click()
            dialog = self.page.get_by_role("dialog", name=NAME, exact=True)
            expect(dialog).to_be_visible()
            image = dialog.get_by_role("img", name=NAME, exact=True)
            expect(image).to_have_attribute("src", ITEM["image_url"])
            box = image.bounding_box()
            self.assertGreater(box["width"], 300)
            self.assertAlmostEqual(box["x"] + box["width"] / 2, 640, delta=2)
            self.assertAlmostEqual(box["y"] + box["height"] / 2, 450, delta=2)
            self.page.keyboard.press("Escape")
            expect(dialog).not_to_be_visible()
            expect(trigger).to_be_focused()
        self.assertEqual(self.errors, [])

    def test_dismissal_keyboard_and_missing_image(self):
        self.page.goto("https://inventory.test/buylist")
        trigger = self.page.get_by_role("button", name=NAME, exact=True)
        trigger.focus()
        self.page.keyboard.press("Enter")
        dialog = self.page.get_by_role("dialog", name=NAME, exact=True)
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role("button", name="Close card preview")).to_be_focused()
        self.assertEqual(self.page.locator("html").evaluate("el => getComputedStyle(el).overflow"), "hidden")
        dialog.get_by_role("img").click()
        expect(dialog).to_be_visible()  # Clicking the art must not dismiss it.
        dialog.get_by_role("button", name="Close card preview").click()
        expect(dialog).not_to_be_visible()
        expect(trigger).to_be_focused()
        self.page.keyboard.press("Space")
        expect(dialog).to_be_visible()
        self.page.mouse.click(5, 5)
        expect(dialog).not_to_be_visible()
        expect(trigger).to_be_focused()
        expect(self.page.locator("html")).not_to_have_class("card-preview-open")
        missing = self.page.locator("table.buylist tbody tr").nth(1)
        self.assertEqual(missing.locator(".card-preview-trigger").count(), 0)
        expect(missing).to_contain_text("No image")
        self.assertEqual(self.errors, [])

    def test_inline_table_replacement_and_sorting(self):
        self.page.goto("https://inventory.test/")
        replacement = dict(ITEM, card_name="Updated card")
        self.page.locator("#buylist-container").evaluate(
            "(el, html) => { el.innerHTML = html; }",
            render("_buylist_table.html", [replacement, dict(ITEM, card_name="A card")]))
        self.page.get_by_role("columnheader", name="Card", exact=True).click()
        expect(self.page.locator("table.buylist tbody tr").first).to_contain_text("A card")
        self.page.get_by_role("button", name="Updated card", exact=True).click()
        expect(self.page.get_by_role("dialog", name="Updated card", exact=True)).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_price_sparklines_and_price_sorting_after_inline_refresh(self):
        def priced_item(name, prices, suggested):
            history = [{"price": price, "at": f"2026-01-{i + 1:02d}T12:00:00+00:00", "currency": "USD"}
                       for i, price in enumerate(prices)]
            return dict(ITEM, card_name=name, price=prices[-1] if prices else None,
                        suggested_price=suggested, currency="USD", price_history=history)

        rows = [priced_item("Rising", list(range(1, 11)), 1),
                priced_item("Falling", list(range(10, 0, -1)), 10),
                priced_item("Flat", [3, 3, 3], 3),
                priced_item("First observation", [2], 2),
                priced_item("Unpriced", [], None)]
        self.page.route("**/buylist", lambda route: route.fulfill(body=render("buylist.html", rows), content_type="text/html"))
        self.page.goto("https://inventory.test/buylist")
        headers = self.page.locator("table.buylist th").all_text_contents()
        self.assertEqual(headers[6:9], ["Current", "History", "Suggested"])
        graphs = self.page.locator(".price-sparkline")
        self.assertEqual(graphs.count(), 4)
        for graph, count in zip(graphs.all(), [10, 10, 3, 1]):
            self.assertEqual(graph.locator("circle").count(), count)
            self.assertIn(f"Data points: {count}", graph.get_attribute("aria-label"))
            self.assertEqual(graph.locator("title").count(), 1)
            self.assertEqual(len(graph.locator("title").text_content().splitlines()), 3)
            box = graph.bounding_box()
            self.assertEqual((box["width"], box["height"]), (88, 28))
        self.assertEqual(graphs.nth(3).locator("polyline").count(), 0)
        self.assertEqual(graphs.nth(2).locator("circle").evaluate_all("els => new Set(els.map(e => e.getAttribute('cy'))).size"), 1)
        expect(self.page.locator(".price-history").last).to_contain_text("—")
        colors = [graph.evaluate("el => getComputedStyle(el).color") for graph in graphs.all()]
        self.assertEqual(colors[:3], ["rgb(242, 139, 130)", "rgb(125, 214, 90)", "rgb(96, 165, 250)"])
        self.assertEqual(colors[3], "rgb(96, 165, 250)")
        if os.getenv("CARD_INVENTORY_SCREENSHOT"):
            self.page.screenshot(path=os.environ["CARD_INVENTORY_SCREENSHOT"], full_page=True)

        self.page.goto("https://inventory.test/")
        self.page.locator("#buylist-container").evaluate(
            "(el, html) => { el.innerHTML = html; }", render("_buylist_table.html", rows[:2]))
        for column, expected in [("Current", "Falling"), ("Suggested", "Rising")]:
            self.page.get_by_role("columnheader", name=column, exact=True).click()
            first = self.page.locator("table.buylist tbody tr").first
            expect(first).to_contain_text(expected)
            expect(first.locator(".price-sparkline")).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_quantity_changes_stay_on_the_current_view(self):
        navigations = []
        self.page.on("framenavigated", lambda frame: navigations.append(frame.url))
        for path in ("/", "/buylist"):
            for scope in ("all", "general", "2"):
                with self.subTest(page=path, scope=scope):
                    quantity = [2]
                    posts = []
                    lists = [{"id": 1, "name": "Dani"}, {"id": 2, "name": "Current list"}]
                    def route_page(route):
                        request_path = urlparse(route.request.url).path
                        if request_path == "/buylist/qty":
                            raw = route.request.post_data
                            if "multipart/form-data" in route.request.headers.get("content-type", ""):
                                import re
                                data = {name: [value] for name, value in re.findall(r'name="([^\"]+)"\r\n\r\n([^\r]*)', raw)}
                            else:
                                data = parse_qs(raw)
                            posts.append(data)
                            quantity[0] = max(1, quantity[0] + int(data["delta"][0]))
                            route.fulfill(json={"item_id": 1, "quantity": quantity[0]})
                        elif request_path == path:
                            route.fulfill(body=render("index.html" if path == "/" else "buylist.html",
                                [dict(ITEM, quantity=quantity[0]), dict(ITEM, id=2, card_name="Z card")],
                                scope=scope, lists=lists), content_type="text/html")
                        else:
                            route.fallback()
                    self.page.route("**/*", route_page)
                    self.page.goto("https://inventory.test" + path + "?scope=" + scope)
                    if path == "/":
                        self.page.locator("#query").fill("keep this search")
                    header = self.page.locator("table.buylist thead th").nth(1)
                    header.click()
                    url = self.page.url
                    before = len(navigations)
                    row = self.page.locator("table.buylist tbody tr").first
                    minus = row.get_by_role("button", name="−", exact=True)
                    minus.click()
                    expect(row.locator(".qty-controls > span")).to_have_text("1", timeout=3000)
                    self.assertEqual(self.page.url, url)
                    self.assertEqual(len(navigations), before)
                    expect(self.page.locator(".buylist-scope")).to_have_value(scope)
                    expect(header).to_have_class("sort-asc")
                    expect(row.locator("td.qty")).to_have_attribute("data-sort", "1")
                    row.get_by_role("button", name="+", exact=True).click()
                    expect(row.locator(".qty-controls > span")).to_have_text("2")
                    self.assertEqual(len(posts), 2)
                    self.assertEqual(posts[0]["scope"], [scope])
                    if path == "/":
                        expect(self.page.locator("#query")).to_have_value("keep this search")
                    self.assertEqual(self.errors, [])
                    self.page.unroute("**/*", route_page)

    def test_quantity_failure_keeps_value_and_reenables_controls(self):
        self.page.goto("https://inventory.test/buylist?scope=general")
        self.page.evaluate("""() => {
          const original = window.fetch;
          window.quantityRequests = 0;
          window.fetch = (url, options) => {
            if (String(url) === '/buylist/qty') {
              window.quantityRequests++;
              return new Promise(resolve => { window.resolveQuantity = resolve; });
            }
            return original(url, options);
          };
        }""")
        row = self.page.locator("table.buylist tbody tr").first
        minus = row.get_by_role("button", name="−", exact=True)
        minus.click()
        expect(minus).to_be_disabled()
        expect(row.get_by_role("button", name="+", exact=True)).to_be_disabled()
        row.locator('form[action="/buylist/qty"]').first.evaluate(
            "form => form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}))")
        self.assertEqual(self.page.evaluate("window.quantityRequests"), 1)
        self.page.evaluate("window.resolveQuantity(new Response(JSON.stringify({detail: 'Update rejected'}), {status: 500}))")
        expect(self.page.locator("#buylist-action-error")).to_contain_text("Update rejected")
        expect(row.locator(".qty-controls > span")).to_have_text("2")
        expect(minus).to_be_enabled()
        expect(row.get_by_role("button", name="+", exact=True)).to_be_enabled()
        self.assertEqual(self.page.url, "https://inventory.test/buylist?scope=general")
        self.assertEqual(self.errors, [])

    def test_preview_fits_mobile_and_landscape_screens(self):
        for width, height in [(390, 844), (844, 390)]:
            with self.subTest(viewport=(width, height)):
                self.page.set_viewport_size({"width": width, "height": height})
                self.page.goto("https://inventory.test/buylist")
                self.page.get_by_role("button", name=NAME, exact=True).click()
                dialog = self.page.get_by_role("dialog", name=NAME, exact=True)
                image = dialog.get_by_role("img")
                image.evaluate("el => el.decode()")
                box = image.bounding_box()
                self.assertGreater(box["width"], 46)
                self.assertAlmostEqual(box["width"] / box["height"], 630 / 880, delta=0.01)
                self.assertAlmostEqual(box["x"] + box["width"] / 2, width / 2, delta=2)
                self.assertAlmostEqual(box["y"] + box["height"] / 2, height / 2, delta=2)
                close = dialog.get_by_role("button", name="Close card preview").bounding_box()
                self.assertGreaterEqual(close["y"], 0)
                self.assertLessEqual(box["x"] + box["width"], width)
                self.assertLessEqual(box["y"] + box["height"], height)
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
