from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase


class TestBikeSerial(FrappeTestCase):
    """Test suite for Bike Serial DocType (FR-02, FR-03)."""

    def setUp(self):
        # Create a Bike Model to link serials to
        self.bike_model = frappe.get_doc(
            {
                "doctype": "Bike Model",
                "model_name": "Test Serial Bike",
                "brand": "SerialBrand",
                "category": "City",
                "base_rate_hourly": 10.00,
                "base_rate_daily": 40.00,
            }
        ).insert()

        self.serial_reg = "TEST-001"
        self.serial = frappe.get_doc(
            {
                "doctype": "Bike Serial",
                "registration_no": self.serial_reg,
                "chassis_no": "CH-TEST-001",
                "bike_model": self.bike_model.name,
                "status": "Available",
                "current_km": 100,
            }
        ).insert()

    def tearDown(self):
        for name in frappe.get_all("Bike Serial", pluck="name"):
            frappe.delete_doc("Bike Serial", name, force=True)
        if frappe.db.exists("Bike Model", self.bike_model.name):
            frappe.delete_doc("Bike Model", self.bike_model.name, force=True)

    def test_create_with_all_fields(self):
        """AC #1: Verify all field values are stored correctly."""
        self.assertEqual(self.serial.registration_no, "TEST-001")
        self.assertEqual(self.serial.chassis_no, "CH-TEST-001")
        self.assertEqual(self.serial.bike_model, self.bike_model.name)
        self.assertEqual(self.serial.status, "Available")
        self.assertEqual(self.serial.current_km, 100)

    def test_create_minimal_fields(self):
        """AC #1: Verify creation with only required fields."""
        serial = frappe.get_doc(
            {
                "doctype": "Bike Serial",
                "registration_no": "TEST-002",
                "chassis_no": "CH-TEST-002",
                "bike_model": self.bike_model.name,
            }
        ).insert()

        self.assertEqual(serial.status, "Available")  # default
        self.assertEqual(serial.current_km, 0)  # default

        frappe.delete_doc("Bike Serial", "TEST-002", force=True)

    def test_must_link_to_existing_bike_model(self):
        """AC #1: Bike Model link validates existence."""
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Bike Serial",
                    "registration_no": "TEST-BAD",
                    "chassis_no": "CH-BAD",
                    "bike_model": "NonExistent Model",
                }
            ).insert()

    def test_status_transition_rented_to_scrapped_blocked(self):
        """AC #3: Rented → Scrapped is blocked."""
        self.serial.status = "Rented"
        self.serial.save()

        self.serial.status = "Scrapped"
        with self.assertRaises(frappe.ValidationError) as cm:
            self.serial.save()
        self.assertIn("Release bike", str(cm.exception))

    def test_status_transition_maintenance_to_scrapped_blocked(self):
        """AC #3: Maintenance → Scrapped is blocked."""
        self.serial.status = "Maintenance"
        self.serial.save()

        self.serial.status = "Scrapped"
        with self.assertRaises(frappe.ValidationError) as cm:
            self.serial.save()
        self.assertIn("Release bike", str(cm.exception))

    def test_status_transition_available_to_scrapped_allowed(self):
        """AC #3: Available → Scrapped is allowed."""
        self.serial.status = "Scrapped"
        try:
            self.serial.save()
        except frappe.ValidationError:
            self.fail("Available → Scrapped raised ValidationError unexpectedly")

    def test_status_change_logged(self):
        """AC #2: Status changes create a Notification Log."""
        self.serial.status = "Maintenance"
        self.serial.save()

        logs = frappe.get_all(
            "Notification Log",
            filters={"document_name": self.serial.name},
            fields=["subject", "type"],
        )
        self.assertGreaterEqual(len(logs), 1)
        self.assertIn("Available → Maintenance", logs[0].subject)

    def test_total_capacity_excludes_scrapped(self):
        """AC #4: get_total_capacity counts only non-scrapped serials."""
        from .bike_serial import get_total_capacity

        # Create second serial
        frappe.get_doc(
            {
                "doctype": "Bike Serial",
                "registration_no": "TEST-003",
                "chassis_no": "CH-TEST-003",
                "bike_model": self.bike_model.name,
                "status": "Available",
            }
        ).insert()

        total = get_total_capacity(self.bike_model.name)
        self.assertEqual(total, 2)

        # Scrap one
        frappe.db.set_value("Bike Serial", "TEST-003", "status", "Scrapped")

        total = get_total_capacity(self.bike_model.name)
        self.assertEqual(total, 1)

    def test_total_capacity_excludes_in_transit(self):
        """AC #1: get_total_capacity excludes In Transit serials."""
        from .bike_serial import get_total_capacity

        # Create one Available and one In Transit serial
        frappe.get_doc(
            {
                "doctype": "Bike Serial",
                "registration_no": "TEST-IT-001",
                "chassis_no": "CH-IT-001",
                "bike_model": self.bike_model.name,
                "status": "In Transit",
            }
        ).insert()

        total = get_total_capacity(self.bike_model.name)
        self.assertEqual(total, 1)  # Only the original serial counts

        frappe.delete_doc("Bike Serial", "TEST-IT-001", force=True)

    def test_list_view_fields(self):
        """AC #2: List view returns expected columns."""
        serials = frappe.get_list(
            "Bike Serial",
            fields=["registration_no", "bike_model", "status", "current_km"],
            limit=10,
        )
        self.assertGreaterEqual(len(serials), 1)
        self.assertTrue(any(s.registration_no == self.serial_reg for s in serials))

    def test_search_by_registration_no(self):
        """AC #2: Search by registration no returns matching results."""
        results = frappe.get_list(
            "Bike Serial",
            fields=["registration_no"],
            filters={"registration_no": ["like", "%TEST-001%"]},
        )
        self.assertGreaterEqual(len(results), 1)
