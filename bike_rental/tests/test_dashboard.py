from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase

from bike_rental.page.dashboard.dashboard import (
    get_dashboard_data,
    get_pending_kyc_highlights,
    get_prolonged_maintenance,
)


class TestDashboard(FrappeTestCase):
    """Tests for Hub Dashboard data queries (Story 5.3)."""

    def test_dashboard_returns_counts(self):
        """get_dashboard_data returns all metric counts."""
        data = get_dashboard_data()
        self.assertIn("active_bookings", data)
        self.assertIn("available_bikes", data)
        self.assertIn("maintenance_bikes", data)
        self.assertIn("pending_kyc", data)
        self.assertIn("today_checkouts", data)
        self.assertIn("today_checkins", data)
        self.assertIn("total_capacity", data)
        self.assertIn("rented_bikes", data)

    def test_dashboard_counts_are_non_negative(self):
        """All metric counts should be non-negative integers."""
        data = get_dashboard_data()
        for key in ["active_bookings", "available_bikes", "maintenance_bikes",
                     "pending_kyc", "today_checkouts", "today_checkins",
                     "total_capacity", "rented_bikes"]:
            self.assertGreaterEqual(data[key], 0, msg=f"{key} should be >= 0")

    def test_dashboard_with_hub_filter(self):
        """Dashboard accepts optional hub filter without error."""
        data = get_dashboard_data(hub="Downtown Hub")
        self.assertIsNotNone(data)
        self.assertNotIn("error", data)

    def test_dashboard_unknown_hub(self):
        """Dashboard with an nonexistent hub returns zero counts."""
        data = get_dashboard_data(hub="Nonexistent Hub")
        for key in ["active_bookings", "available_bikes", "maintenance_bikes",
                     "pending_kyc"]:
            self.assertEqual(data[key], 0, msg=f"{key} should be 0 for nonexistent hub")

    def test_pending_kyc_returns_highlights(self):
        """get_pending_kyc_highlights returns expected structure."""
        highlights = get_pending_kyc_highlights()
        self.assertIn("total_pending", highlights)
        self.assertIn("high_priority_count", highlights)
        self.assertIn("items", highlights)
        self.assertIsInstance(highlights["items"], list)

    def test_prolonged_maintenance_returns_items(self):
        """get_prolonged_maintenance returns expected structure."""
        result = get_prolonged_maintenance()
        self.assertIn("total_prolonged", result)
        self.assertIn("items", result)
        self.assertIsInstance(result["items"], list)

    def test_prolonged_maintenance_with_hub(self):
        """get_prolonged_maintenance accepts hub filter."""
        result = get_prolonged_maintenance(hub="Downtown Hub")
        self.assertIn("total_prolonged", result)
        self.assertIsInstance(result["items"], list)
