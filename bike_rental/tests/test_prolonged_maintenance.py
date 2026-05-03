from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime, add_to_date

from bike_rental.scheduler.prolonged_maintenance_alerts import alert_prolonged_maintenance


class TestProlongedMaintenance(FrappeTestCase):
    """Tests for prolonged maintenance scheduler (Story 3.4)."""

    def setUp(self):
        self.bike_model = frappe.get_doc({
            "doctype": "Bike Model",
            "model_name": "PM-Test Model",
            "brand": "TestBrand",
            "category": "City",
            "base_rate_hourly": 10.00,
            "base_rate_daily": 40.00,
        }).insert()

        self.hub = frappe.get_doc({
            "doctype": "Hub",
            "hub_name": "PM-Test Hub",
            "location": "Test Location",
        }).insert()

        self.serial = frappe.get_doc({
            "doctype": "Bike Serial",
            "registration_no": "PM-SER-001",
            "chassis_no": "CH-PM-001",
            "bike_model": self.bike_model.name,
            "hub": self.hub.name,
            "status": "Available",
            "current_km": 500,
        }).insert()

        # Ensure at least one Hub Manager user exists for ToDo creation
        self.hub_manager = frappe.get_doc({
            "doctype": "User",
            "email": "pm-test-manager@example.com",
            "first_name": "PM-Test",
            "roles": [{"role": "Hub Manager"}],
        }).insert(ignore_permissions=True)
        self.hub_manager_name = self.hub_manager.name

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
        for name in frappe.get_all("ToDo", pluck="name"):
            frappe.delete_doc("ToDo", name, force=True)
        for name in frappe.get_all("Notification Log", pluck="name"):
            frappe.delete_doc("Notification Log", name, force=True)
        frappe.delete_doc("User", self.hub_manager_name, force=True)

    def _create_maintenance_log(self, days_ago):
        """Create a maintenance log with reported_date set in the past."""
        log = frappe.get_doc({
            "doctype": "Maintenance Log",
            "serial_no": self.serial.name,
            "issue_description": "Test issue",
            "reported_date": add_to_date(now_datetime(), days=-days_ago),
            "reported_by": frappe.session.user,
            "status": "In Progress",
        })
        log.insert(ignore_permissions=True)
        return log

    def test_alert_created_for_bikes_over_14_days(self):
        """Alert is created for bikes in maintenance >14 days."""
        self._create_maintenance_log(15)

        todos_before = frappe.db.count("ToDo", {})
        alert_prolonged_maintenance()
        todos_after = frappe.db.count("ToDo", {})

        self.assertGreater(todos_after, todos_before)

    def test_no_alert_for_bikes_under_14_days(self):
        """No alert created for bikes in maintenance <14 days."""
        self._create_maintenance_log(5)

        todos_before = frappe.db.count("ToDo", {})
        alert_prolonged_maintenance()
        todos_after = frappe.db.count("ToDo", {})

        self.assertEqual(todos_after, todos_before)

    def test_no_alert_when_no_maintenance_logs(self):
        """No alert when there are no maintenance logs."""
        todos_before = frappe.db.count("ToDo", {})
        alert_prolonged_maintenance()
        todos_after = frappe.db.count("ToDo", {})

        self.assertEqual(todos_after, todos_before)

    def test_resolved_logs_not_alerted(self):
        """Resolved maintenance logs do not trigger alerts."""
        log = self._create_maintenance_log(20)
        log.status = "Resolved"
        log.resolution_notes = "Fixed"
        log.save()

        todos_before = frappe.db.count("ToDo", {})
        alert_prolonged_maintenance()
        todos_after = frappe.db.count("ToDo", {})

        self.assertEqual(todos_after, todos_before)
