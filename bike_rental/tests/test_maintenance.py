from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from bike_rental.api.maintenance import mark_for_maintenance, resolve_maintenance


class TestMaintenanceAPI(FrappeTestCase):
    """Tests for maintenance API (Story 3.4)."""

    def setUp(self):
        self.bike_model = frappe.get_doc({
            "doctype": "Bike Model",
            "model_name": "MA-Test Model",
            "brand": "TestBrand",
            "category": "City",
            "base_rate_hourly": 10.00,
            "base_rate_daily": 40.00,
        }).insert()

        self.hub = frappe.get_doc({
            "doctype": "Hub",
            "hub_name": "MA-Test Hub",
            "location": "Test Location",
        }).insert()

        self.serial = frappe.get_doc({
            "doctype": "Bike Serial",
            "registration_no": "MA-SER-001",
            "chassis_no": "CH-MA-001",
            "bike_model": self.bike_model.name,
            "hub": self.hub.name,
            "status": "Available",
            "current_km": 500,
        }).insert()

    def tearDown(self):
        for name in frappe.get_all("Maintenance Log", pluck="name"):
            frappe.delete_doc("Maintenance Log", name, force=True)
        for name in frappe.get_all("Bike Serial", pluck="name"):
            frappe.delete_doc("Bike Serial", name, force=True)
        for name in frappe.get_all("Hub", pluck="name"):
            if name != self.hub.name:
                frappe.delete_doc("Hub", name, force=True)
        frappe.delete_doc("Hub", self.hub.name, force=True)
        for name in frappe.get_all("Bike Model", pluck="name"):
            if name != self.bike_model.name:
                frappe.delete_doc("Bike Model", name, force=True)
        frappe.delete_doc("Bike Model", self.bike_model.name, force=True)
        for name in frappe.get_all("Notification Log", pluck="name"):
            frappe.delete_doc("Notification Log", name, force=True)

    def test_mark_available_bike_for_maintenance(self):
        """Marking an available bike for maintenance succeeds."""
        result = mark_for_maintenance(self.serial.name, "Engine overheating")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["new_status"], "Maintenance")

        self.serial.reload()
        self.assertEqual(self.serial.status, "Maintenance")

    def test_mark_already_maintenance_bike_fails(self):
        """Marking an already-maintenance bike is rejected."""
        mark_for_maintenance(self.serial.name, "First issue")
        with self.assertRaises(frappe.ValidationError):
            mark_for_maintenance(self.serial.name, "Second issue")

    def test_mark_scrapped_bike_fails(self):
        """Marking a scrapped bike is rejected."""
        self.serial.db_set("status", "Scrapped")
        with self.assertRaises(frappe.ValidationError):
            mark_for_maintenance(self.serial.name, "Test issue")

    def test_mark_nonexistent_serial_fails(self):
        """Marking a non-existent serial is rejected."""
        with self.assertRaises(frappe.ValidationError):
            mark_for_maintenance("NONEXISTENT-SERIAL", "Test issue")

    def test_notification_log_created_on_maintenance(self):
        """Notification Log is created when marking for maintenance."""
        mark_for_maintenance(self.serial.name, "Electrical fault")
        logs = frappe.get_all(
            "Notification Log",
            filters={"document_type": "Maintenance Log"},
            pluck="name",
        )
        self.assertGreater(len(logs), 0)

    def test_resolve_maintenance(self):
        """Resolving maintenance restores serial to Available."""
        mark_for_maintenance(self.serial.name, "Flat tire")
        logs = frappe.get_all("Maintenance Log", pluck="name")
        self.assertEqual(len(logs), 1)

        result = resolve_maintenance(logs[0], "Tire replaced", 50)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["serial_status"], "Available")

        self.serial.reload()
        self.assertEqual(self.serial.status, "Available")

    def test_resolve_already_resolved_fails(self):
        """Resolving an already-resolved log is rejected."""
        mark_for_maintenance(self.serial.name, "Flat tire")
        logs = frappe.get_all("Maintenance Log", pluck="name")
        resolve_maintenance(logs[0], "Tire replaced", 50)

        with self.assertRaises(frappe.ValidationError):
            resolve_maintenance(logs[0], "Already done")

    def test_mark_for_maintenance_updates_serial_status(self):
        """Verify serial status transitions correctly."""
        self.assertEqual(self.serial.status, "Available")
        mark_for_maintenance(self.serial.name, "Test")
        self.serial.reload()
        self.assertEqual(self.serial.status, "Maintenance")
