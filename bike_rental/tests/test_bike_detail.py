from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase

from bike_rental.www.bikes.index import get_bike_detail, calculate_price


class TestBikeDetail(FrappeTestCase):
    """Tests for Bike Detail page and Booking Widget (Story 6.2)."""

    def test_get_bike_detail_returns_structure(self):
        """get_bike_detail returns expected fields."""
        models = frappe.get_all("Bike Model", limit=1)
        if not models:
            self.skipTest("No bike models in database")
        detail = get_bike_detail(models[0].name)
        self.assertIn("name", detail)
        self.assertIn("category", detail)
        self.assertIn("base_rate_daily", detail)
        self.assertIn("hubs", detail)
        self.assertIn("total_serials", detail)
        self.assertIsInstance(detail["hubs"], list)

    def test_get_bike_detail_nonexistent(self):
        """get_bike_detail raises for nonexistent model."""
        with self.assertRaises(frappe.ValidationError):
            get_bike_detail("NONEXISTENT-MODEL")

    def test_calculate_price_returns_keys(self):
        """calculate_price returns expected fields."""
        models = frappe.get_all("Bike Model", limit=1)
        if not models:
            self.skipTest("No bike models in database")
        price = calculate_price(models[0].name, "2026-06-01", "2026-06-03")
        self.assertIn("daily_rate", price)
        self.assertIn("days", price)
        self.assertIn("base_amount", price)
        self.assertIn("deposit", price)
        self.assertIn("total_due", price)

    def test_calculate_price_correct_days(self):
        """calculate_price returns correct day count."""
        models = frappe.get_all("Bike Model", limit=1)
        if not models:
            self.skipTest("No bike models in database")
        price = calculate_price(models[0].name, "2026-06-01", "2026-06-04")
        self.assertEqual(price["days"], 3)

    def test_calculate_price_single_day(self):
        """calculate_price returns at least 1 day."""
        models = frappe.get_all("Bike Model", limit=1)
        if not models:
            self.skipTest("No bike models in database")
        # Same day should give 1 day minimum
        price = calculate_price(models[0].name, "2026-06-01", "2026-06-01")
        self.assertEqual(price["days"], 1)

    def test_calculate_price_nonexistent_model(self):
        """calculate_price raises for nonexistent model."""
        with self.assertRaises(frappe.ValidationError):
            calculate_price("NONEXISTENT", "2026-06-01", "2026-06-02")
