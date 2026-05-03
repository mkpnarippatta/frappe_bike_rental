from __future__ import unicode_literals

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from bike_rental.page.reporting_analytics.reporting_analytics import (
    get_revenue_report,
    get_utilisation_report,
    get_booking_trends,
    get_maintenance_cost_report,
    export_report_csv,
)


class TestReportingAnalytics(FrappeTestCase):
    """Tests for Reporting & Analytics server methods (Story 5.5)."""

    def test_revenue_report_returns_required_keys(self):
        """get_revenue_report returns expected structure."""
        data = get_revenue_report()
        self.assertIn("total_revenue", data)
        self.assertIn("booking_count", data)
        self.assertIn("average_booking_value", data)
        self.assertIn("by_hub", data)
        self.assertIn("by_model", data)

    def test_revenue_report_non_negative(self):
        """Revenue totals should be non-negative."""
        data = get_revenue_report()
        self.assertGreaterEqual(data["total_revenue"], 0)
        self.assertGreaterEqual(data["booking_count"], 0)
        self.assertGreaterEqual(data["average_booking_value"], 0)

    def test_utilisation_report_returns_required_keys(self):
        """get_utilisation_report returns expected structure."""
        data = get_utilisation_report()
        self.assertIn("total_capacity", data)
        self.assertIn("days", data)
        self.assertIn("average_utilisation", data)
        self.assertIn("peak_utilisation", data)
        self.assertIn("low_utilisation", data)
        self.assertIsInstance(data["days"], list)

    def test_utilisation_capacity_non_negative(self):
        """Total capacity should be non-negative."""
        data = get_utilisation_report()
        self.assertGreaterEqual(data["total_capacity"], 0)

    def test_booking_trends_returns_required_keys(self):
        """get_booking_trends returns expected structure."""
        data = get_booking_trends(granularity="Daily")
        self.assertIn("total_bookings", data)
        self.assertIn("periods", data)
        self.assertIn("granularity", data)
        self.assertIsInstance(data["periods"], list)

    def test_booking_trends_daily_granularity(self):
        """get_booking_trends with Daily granularity returns correct label."""
        data = get_booking_trends(granularity="Daily")
        self.assertEqual(data["granularity"], "Daily")

    def test_booking_trends_monthly_granularity(self):
        """get_booking_trends with Monthly granularity returns correct label."""
        data = get_booking_trends(granularity="Monthly")
        self.assertEqual(data["granularity"], "Monthly")

    def test_booking_trends_weekly_granularity(self):
        """get_booking_trends with Weekly granularity returns correct label."""
        data = get_booking_trends(granularity="Weekly")
        self.assertEqual(data["granularity"], "Weekly")

    def test_maintenance_report_returns_required_keys(self):
        """get_maintenance_cost_report returns expected structure."""
        data = get_maintenance_cost_report()
        self.assertIn("total_cost", data)
        self.assertIn("maintenance_count", data)
        self.assertIn("by_model", data)
        self.assertIn("by_type", data)
        self.assertIsInstance(data["by_model"], list)
        self.assertIsInstance(data["by_type"], list)

    def test_maintenance_cost_non_negative(self):
        """Maintenance costs should be non-negative."""
        data = get_maintenance_cost_report()
        self.assertGreaterEqual(data["total_cost"], 0)
        self.assertGreaterEqual(data["maintenance_count"], 0)

    def test_export_csv_returns_file_info(self):
        """export_report_csv returns file_url and file_name."""
        data = get_revenue_report()
        result = export_report_csv("Revenue", json.dumps(data))
        self.assertIn("file_url", result)
        self.assertIn("file_name", result)
        self.assertTrue(result["file_name"].endswith(".csv"))

    def test_export_csv_with_nonexistent_hub(self):
        """export_report_csv handles empty data from nonexistent hub."""
        data = get_revenue_report(hub="Nonexistent Hub")
        result = export_report_csv("Revenue", json.dumps(data))
        self.assertIn("file_url", result)
