from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase

from bike_rental.scheduler.km_maintenance_alerts import alert_maintenance_thresholds


class TestKMMaintenanceAlerts(FrappeTestCase):
    """Tests for KM threshold alert scheduler (Story 3.5)."""

    def setUp(self):
        self.bike_model = frappe.get_doc({
            "doctype": "Bike Model",
            "model_name": "KM-Test Model",
            "brand": "TestBrand",
            "category": "City",
            "base_rate_hourly": 10.00,
            "base_rate_daily": 40.00,
            "service_interval_km": 1000,
        }).insert()

        self.hub = frappe.get_doc({
            "doctype": "Hub",
            "hub_name": "KM-Test Hub",
            "location": "Test Location",
        }).insert()

        self.hub_manager = frappe.get_doc({
            "doctype": "User",
            "email": "km-test-manager@example.com",
            "first_name": "KM-Test",
            "roles": [{"role": "Hub Manager"}],
        }).insert(ignore_permissions=True)
        self.hub_manager_name = self.hub_manager.name

    def tearDown(self):
        for name in frappe.get_all("Bike Serial", pluck="name"):
            frappe.delete_doc("Bike Serial", name, force=True)
        frappe.delete_doc("Hub", self.hub.name, force=True)
        for name in frappe.get_all("Bike Model", pluck="name"):
            if name != self.bike_model.name:
                frappe.delete_doc("Bike Model", name, force=True)
        frappe.delete_doc("Bike Model", self.bike_model.name, force=True)
        for name in frappe.get_all("ToDo", pluck="name"):
            frappe.delete_doc("ToDo", name, force=True)
        frappe.delete_doc("User", self.hub_manager_name, force=True)

    def _create_serial(self, registration, km):
        return frappe.get_doc({
            "doctype": "Bike Serial",
            "registration_no": registration,
            "chassis_no": f"CH-{registration}",
            "bike_model": self.bike_model.name,
            "hub": self.hub.name,
            "status": "Available",
            "current_km": km,
        }).insert()

    def _count_todos(self):
        return frappe.db.count("ToDo", {})

    def test_no_alert_below_80_percent(self):
        """No ToDo created when KM is below 80% of threshold."""
        self._create_serial("KM-SER-001", 500)
        todos_before = self._count_todos()
        alert_maintenance_thresholds()
        self.assertEqual(self._count_todos(), todos_before)

    def test_due_soon_alert_at_80_percent(self):
        """'[Service Due Soon]' ToDo created when KM is at 80% of threshold."""
        self._create_serial("KM-SER-002", 800)
        alert_maintenance_thresholds()
        todos = frappe.get_all("ToDo", fields=["description", "allocated_to"])
        self.assertEqual(len(todos), 1)
        self.assertIn("[Service Due Soon]", todos[0].description)
        self.assertEqual(todos[0].allocated_to, self.hub_manager_name)

    def test_overdue_alert_at_100_percent(self):
        """'[Service Overdue]' ToDo created when KM is at 100% of threshold."""
        self._create_serial("KM-SER-003", 1000)
        alert_maintenance_thresholds()
        todos = frappe.get_all("ToDo", fields=["description", "allocated_to"])
        self.assertEqual(len(todos), 1)
        self.assertIn("[Service Overdue]", todos[0].description)
        self.assertEqual(todos[0].allocated_to, self.hub_manager_name)

    def test_overdue_alert_exceeds_100_percent(self):
        """'[Service Overdue]' ToDo created when KM exceeds 100% of threshold."""
        self._create_serial("KM-SER-004", 1200)
        alert_maintenance_thresholds()
        todos = frappe.get_all("ToDo", fields=["description", "allocated_to"])
        self.assertEqual(len(todos), 1)
        self.assertIn("[Service Overdue]", todos[0].description)

    def test_no_alert_for_scrapped_or_in_transit(self):
        """No alert for scrapped or in-transit bikes."""
        serial = self._create_serial("KM-SER-005", 5000)
        serial.db_set("status", "Scrapped")
        todos_before = self._count_todos()
        alert_maintenance_thresholds()
        self.assertEqual(self._count_todos(), todos_before)

        # Also test In Transit
        serial2 = self._create_serial("KM-SER-006", 5000)
        serial2.db_set("status", "In Transit")
        alert_maintenance_thresholds()
        self.assertEqual(self._count_todos(), todos_before)

    def test_no_duplicate_todos(self):
        """Running the scheduler twice does not create duplicate ToDos."""
        self._create_serial("KM-SER-007", 900)
        alert_maintenance_thresholds()
        first_count = self._count_todos()
        self.assertGreater(first_count, 0)
        alert_maintenance_thresholds()
        self.assertEqual(self._count_todos(), first_count)

    def test_custom_interval_respected(self):
        """Custom service_interval_km on Bike Model is used instead of default."""
        self.bike_model.service_interval_km = 500
        self.bike_model.save()
        self._create_serial("KM-SER-008", 400)  # 80% of 500
        alert_maintenance_thresholds()
        todos = frappe.get_all("ToDo", pluck="description")
        self.assertEqual(len(todos), 1)
        self.assertIn("[Service Due Soon]", todos[0])

    def test_both_tiers_with_multiple_serials(self):
        """Multiple serials at different tiers each get correct alerts."""
        self._create_serial("KM-SER-009", 800)   # due_soon
        self._create_serial("KM-SER-010", 1000)  # overdue
        alert_maintenance_thresholds()
        todos = frappe.get_all("ToDo", pluck="description")
        self.assertEqual(len(todos), 2)
        labels = [t for t in todos]
        self.assertTrue(any("[Service Due Soon]" in d for d in labels))
        self.assertTrue(any("[Service Overdue]" in d for d in labels))
