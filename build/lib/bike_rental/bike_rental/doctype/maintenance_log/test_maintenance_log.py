from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime, add_to_date


class TestMaintenanceLog(FrappeTestCase):
    """Tests for Maintenance Log DocType hooks (Story 3.4)."""

    def setUp(self):
        self.bike_model = frappe.get_doc({
            "doctype": "Bike Model",
            "model_name": "ML-Test Model",
            "brand": "TestBrand",
            "category": "City",
            "base_rate_hourly": 10.00,
            "base_rate_daily": 40.00,
        }).insert()

        self.hub = frappe.get_doc({
            "doctype": "Hub",
            "hub_name": "ML-Test Hub",
            "location": "Test Location",
        }).insert()

        self.serial = frappe.get_doc({
            "doctype": "Bike Serial",
            "registration_no": "ML-SER-001",
            "chassis_no": "CH-ML-001",
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

    def test_creating_log_sets_serial_to_maintenance(self):
        """Creating a Maintenance Log with In Progress status sets serial to Maintenance."""
        log = frappe.get_doc({
            "doctype": "Maintenance Log",
            "serial_no": self.serial.name,
            "issue_description": "Brake failure",
            "reported_date": now_datetime(),
            "reported_by": frappe.session.user,
            "status": "In Progress",
        })
        log.insert()

        self.serial.reload()
        self.assertEqual(self.serial.status, "Maintenance")

    def test_resolving_log_restores_serial_to_available(self):
        """Resolving a log sets serial back to Available when no other unresolved logs exist."""
        log = frappe.get_doc({
            "doctype": "Maintenance Log",
            "serial_no": self.serial.name,
            "issue_description": "Brake failure",
            "reported_date": now_datetime(),
            "reported_by": frappe.session.user,
            "status": "In Progress",
        })
        log.insert()

        log.status = "Resolved"
        log.resolution_notes = "Brakes replaced, tested OK"
        log.save()

        self.serial.reload()
        self.assertEqual(self.serial.status, "Available")

    def test_resolution_blocked_without_notes(self):
        """Resolving a log without resolution_notes is rejected."""
        log = frappe.get_doc({
            "doctype": "Maintenance Log",
            "serial_no": self.serial.name,
            "issue_description": "Brake failure",
            "reported_date": now_datetime(),
            "reported_by": frappe.session.user,
            "status": "In Progress",
        })
        log.insert()

        log.status = "Resolved"
        log.resolution_notes = ""
        with self.assertRaises(frappe.ValidationError):
            log.save()

    def test_cannot_delete_in_progress_log(self):
        """Deleting an In Progress maintenance log is blocked."""
        log = frappe.get_doc({
            "doctype": "Maintenance Log",
            "serial_no": self.serial.name,
            "issue_description": "Brake failure",
            "reported_date": now_datetime(),
            "reported_by": frappe.session.user,
            "status": "In Progress",
        })
        log.insert()

        with self.assertRaises(frappe.ValidationError):
            frappe.delete_doc("Maintenance Log", log.name, force=True)

    def test_resolved_log_can_be_deleted(self):
        """A resolved maintenance log can be deleted."""
        log = frappe.get_doc({
            "doctype": "Maintenance Log",
            "serial_no": self.serial.name,
            "issue_description": "Brake failure",
            "reported_date": now_datetime(),
            "reported_by": frappe.session.user,
            "status": "In Progress",
        })
        log.insert()

        log.status = "Resolved"
        log.resolution_notes = "Brakes replaced"
        log.save()

        # Should not raise
        frappe.delete_doc("Maintenance Log", log.name, force=True)

    def test_multiple_logs_same_serial(self):
        """Multiple unresolved logs keep serial in Maintenance after resolving one."""
        log1 = frappe.get_doc({
            "doctype": "Maintenance Log",
            "serial_no": self.serial.name,
            "issue_description": "Brake issue",
            "reported_date": now_datetime(),
            "reported_by": frappe.session.user,
        })
        log1.insert()
        self.serial.reload()
        self.assertEqual(self.serial.status, "Maintenance")

        log2 = frappe.get_doc({
            "doctype": "Maintenance Log",
            "serial_no": self.serial.name,
            "issue_description": "Engine noise",
            "reported_date": now_datetime(),
            "reported_by": frappe.session.user,
        })
        log2.insert()

        # Resolve the first log
        log1.status = "Resolved"
        log1.resolution_notes = "Fixed"
        log1.save()

        # Serial should still be Maintenance because log2 is unresolved
        self.serial.reload()
        self.assertEqual(self.serial.status, "Maintenance")

        # Resolve the second log
        log2.status = "Resolved"
        log2.resolution_notes = "Engine rebuilt"
        log2.save()

        self.serial.reload()
        self.assertEqual(self.serial.status, "Available")

    def test_duplicate_maintenance_blocked(self):
        """Creating a log for an already-Maintenance serial is blocked."""
        log = frappe.get_doc({
            "doctype": "Maintenance Log",
            "serial_no": self.serial.name,
            "issue_description": "First issue",
            "reported_date": now_datetime(),
            "reported_by": frappe.session.user,
        })
        log.insert()

        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({
                "doctype": "Maintenance Log",
                "serial_no": self.serial.name,
                "issue_description": "Second issue",
                "reported_date": now_datetime(),
                "reported_by": frappe.session.user,
            }).insert()
