"""Pure pricing regressions using newest-first, synthetic API sale buckets."""
import unittest

from app.pricing.tcgplayer import PricingResult, compute_pricing


def bucket(low, high, quantity=1, market=None):
    return {
        "lowSalePrice": low,
        "highSalePrice": high,
        "quantitySold": quantity,
        "marketPrice": market,
    }


def sku(buckets, variant="Normal", total_quantity=1):
    return {
        "condition": "Near Mint",
        "language": "English",
        "variant": variant,
        "totalQuantitySold": total_quantity,
        "buckets": buckets,
    }


class SuggestedPriceTests(unittest.TestCase):
    def test_suggested_price_cannot_exceed_latest_sale_midpoint(self):
        data = {"result": [sku([
            bucket(4, 6, market=20),
            bucket(10, 10),
        ])]}

        result = compute_pricing(data)

        self.assertEqual(result, PricingResult(20.0, 5.0, 2))

    def test_rounding_cannot_raise_suggested_price_above_current_market(self):
        data = {"result": [sku([bucket(6, 6, market=3.8)])]}

        result = compute_pricing(data)

        self.assertEqual(result, PricingResult(3.8, 3.8, 1))

    def test_rounding_cannot_raise_suggested_price_above_latest_sale(self):
        data = {"result": [sku([bucket(3.7, 3.9, market=20)])]}

        result = compute_pricing(data)

        self.assertEqual(result, PricingResult(20.0, 3.8, 1))

    def test_latest_sale_ceiling_applies_without_market_price(self):
        data = {"result": [sku([
            bucket(2, 3),
            bucket(9, 10),
        ])]}

        result = compute_pricing(data)

        self.assertEqual(result, PricingResult(None, 2.5, 2))

    def test_newest_invalid_or_zero_sales_bucket_is_skipped(self):
        invalid_buckets = [
            bucket(0.1, 0.1, quantity=0, market=20),
            bucket(0.1, 0.1, quantity=-1, market=20),
            bucket(0.1, 0.1, quantity="bad", market=20),
            bucket(None, None, market=20),
            bucket("bad", "bad", market=20),
            bucket(0, 0, market=20),
        ]
        for invalid in invalid_buckets:
            with self.subTest(bucket=invalid):
                data = {"result": [sku([
                    invalid,
                    bucket(3, 5),
                    bucket(10, 10),
                ])]}

                result = compute_pricing(data)

                self.assertEqual(result, PricingResult(20.0, 4.0, 2))

    def test_latest_sale_uses_one_sided_price_fallback(self):
        for low, high in [(3.8, None), (None, 3.8), (3.8, 0), (0, 3.8)]:
            with self.subTest(low=low, high=high):
                data = {"result": [sku([
                    bucket(low, high, market=20),
                    bucket(10, 10),
                ])]}

                result = compute_pricing(data)

                self.assertEqual(result, PricingResult(20.0, 3.8, 2))

    def test_latest_sale_ceiling_uses_selected_foiling_sku(self):
        data = {"result": [
            sku([bucket(0.5, 0.5, market=1)], total_quantity=1000),
            sku([
                bucket(3, 5, market=20),
                bucket(10, 10),
            ], variant="Cold Foil", total_quantity=2),
        ]}

        result = compute_pricing(data, variant="Cold Foil")

        self.assertEqual(result, PricingResult(20.0, 4.0, 2))

    def test_suggested_price_below_latest_sale_remains_unchanged(self):
        data = {"result": [sku([
            bucket(10, 10, market=20),
            bucket(2, 2, quantity=3),
        ])]}

        result = compute_pricing(data)

        self.assertEqual(result, PricingResult(20.0, 4.0, 4))

    def test_existing_market_cap_still_precedes_rounding_down(self):
        data = {"result": [sku([bucket(6, 6, market=3.2)])]}

        result = compute_pricing(data)

        self.assertEqual(result, PricingResult(3.2, 3.0, 1))

    def test_empty_sales_does_not_invent_suggested_price(self):
        for buckets, current in [
            ([], None),
            ([bucket(4, 6, quantity=0, market=20)], 20.0),
            ([bucket(None, None, market=20)], 20.0),
        ]:
            with self.subTest(buckets=buckets):
                result = compute_pricing({"result": [sku(buckets)]})

                self.assertEqual(result, PricingResult(current, None, 0))

    def test_missing_sku_does_not_invent_suggested_price(self):
        for data in [{}, {"result": None}, {"result": []}]:
            with self.subTest(data=data):
                self.assertEqual(compute_pricing(data), PricingResult(None, None, 0))

    def test_weighted_trimmed_mean_threshold_is_preserved(self):
        for older_quantity, expected in [(8, 3.0), (9, 2.0)]:
            with self.subTest(older_quantity=older_quantity):
                data = {"result": [sku([
                    bucket(10, 10, market=20),
                    bucket(2, 2, quantity=older_quantity),
                ])]}

                result = compute_pricing(data)

                self.assertEqual(
                    result, PricingResult(20.0, expected, older_quantity + 1)
                )

    def test_only_latest_hundred_weighted_sales_are_used(self):
        data = {"result": [sku([
            bucket(20, 20, market=50),
            bucket(10, 10, quantity=99),
            bucket(1, 1, quantity=100),
        ])]}

        result = compute_pricing(data)

        self.assertEqual(result, PricingResult(50.0, 10.0, 100))


if __name__ == "__main__":
    unittest.main()
