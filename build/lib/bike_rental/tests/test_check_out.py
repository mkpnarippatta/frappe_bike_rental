from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from bike_rental.api.check_out import check_out


class TestCheckOut(FrappeTestCase):
    """Test suite for check-out API (Story 2.5)."""

    def setUp(self):
        # Create two Bike Models (second for mismatch testing)
        self.model_a = frappe.get_doc(
            {
                "doctype": "Bike Model",
                "model_name": "CO-Test Model A",
                "brand": "TestBrand",
                "category": "City",
                "base_rate_hourly": 10.00,
                "base_rate_daily": 40.00,
            }
        ).insert()

        self.model_b = frappe.get_doc(
            {
                "doctype": "Bike Model",
                "model_name": "CO-Test Model B",
                "brand": "TestBrand",
                "category": "Touring",
                "base_rate_hourly": 15.00,
                "base_rate_daily": 60.00,
            }
        ).insert()

        self.hub = frappe.get_doc(
            {
                "doctype": "Hub",
                "hub_name": "CO-Test Hub",
                "location": "Test Location",
                "operating_hours_start": "06:00:00",
                "operating_hours_end": "22:00:00",
            }
        ).insert()

        self.customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": "CO-Test Customer",
                "email": "co-test@example.com",
                "phone": "+1333333333",
            }
        ).insert()

        # Serials for model_a
        self.serial_available = self._create_serial(
            "CO-AVAIL-001", self.model_a.name, "Available"
        )
        self.serial_maintenance = self._create_serial(
            "CO-MAINT-001", self.model_a.name, "Maintenance"
        )

        # Serial for model_b (model mismatch)
        self.serial_other_model = self._create_serial(
            "CO-OTHER-001", self.model_b.name, "Available"
        )

        # Create a Confirmed booking for model_a
        self.booking = frappe.get_doc(
            {
                "doctype": "Rental Booking",
                "bike_model": self.model_a.name,
                "customer": self.customer.name,
                "pickup_hub": self.hub.name,
                "return_hub": self.hub.name,
                "pickup_datetime": add_to_date(now_datetime(), days=7, hours=10),
                "return_datetime": add_to_date(now_datetime(), days=9, hours=10),
                "customer_name": self.customer.customer_name,
                "customer_phone": self.customer.phone,
            }
        ).insert()

        # Set to Confirmed via db_set (bypass submit flow)
        self.booking.db_set("status", "Confirmed")
        self.booking.reload()

    def tearDown(self):
        for name in frappe.get_all("Notification Log", pluck="name"):
            frappe.delete_doc("Notification Log", name, force=True)
        for name in frappe.get_all("Rental Booking", pluck="name"):
            frappe.delete_doc("Rental Booking", name, force=True)
        for name in frappe.get_all("Bike Serial", pluck="name"):
            frappe.delete_doc("Bike Serial", name, force=True)
        for name in frappe.get_all("Customer", pluck="name"):
            if name != self.customer.name:
                frappe.delete_doc("Customer", name, force=True)
        frappe.delete_doc("Customer", self.customer.name, force=True)
        frappe.delete_doc("Hub", self.hub.name, force=True)
        frappe.delete_doc("Bike Model", self.model_a.name, force=True)
        frappe.delete_doc("Bike Model", self.model_b.name, force=True)

    def _create_serial(self, reg, model, status="Available"):
        return frappe.get_doc(
            {
                "doctype": "Bike Serial",
                "registration_no": reg,
                "chassis_no": f"CH-{reg}",
                "bike_model": model,
                "hub": self.hub.name,
                "status": status,
            }
        ).insert()

    # --- AC #2: Booking Status Validation ---

    def test_check_out_validates_booking_status(self):
        """AC #2: Non-Confirmed booking is blocked."""
        draft_booking = frappe.get_doc(
            {
                "doctype": "Rental Booking",
                "bike_model": self.model_a.name,
                "customer": self.customer.name,
                "pickup_hub": self.hub.name,
                "return_hub": self.hub.name,
                "pickup_datetime": add_to_date(now_datetime(), days=7, hours=10),
                "return_datetime": add_to_date(now_datetime(), days=9, hours=10),
                "customer_name": self.customer.customer_name,
                "customer_phone": self.customer.phone,
            }
        ).insert()

        with self.assertRaises(frappe.ValidationError) as cm:
            check_out(draft_booking.name, self.serial_available.name)
        self.assertIn("Confirmed", str(cm.exception))
        frappe.delete_doc("Rental Booking", draft_booking.name, force=True)

    # --- AC #2: Serial Availability Validation ---

    def test_check_out_validates_serial_availability(self):
        """AC #2: Non-Available serial is blocked."""
        with self.assertRaises(frappe.ValidationError) as cm:
            check_out(self.booking.name, self.serial_maintenance.name)
        self.assertIn("not available", str(cm.exception))

    # --- AC #3: Model Match Validation ---

    def test_check_out_validates_model_match(self):
        """AC #3: Serial from a different model is blocked."""
        with self.assertRaises(frappe.ValidationError) as cm:
            check_out(self.booking.name, self.serial_other_model.name)
        self.assertIn("does not match", str(cm.exception))

    # --- AC #4: Full Check-Out Flow ---

    def test_check_out_full_flow(self):
        """AC #4: Valid check-out succeeds and updates all statuses."""
        result = check_out(
            self.booking.name,
            self.serial_available.name,
            current_km=1500,
            battery_level=90,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["booking_status"], "Active")
        self.assertEqual(result["serial_status"], "Rented")

        # Verify booking is Active
        booking = frappe.get_doc("Rental Booking", self.booking.name)
        self.assertEqual(booking.status, "Active")
        self.assertEqual(booking.bike_serial, self.serial_available.name)

        # Verify serial is Rented with updated condition
        serial = frappe.get_doc("Bike Serial", self.serial_available.name)
        self.assertEqual(serial.status, "Rented")
        self.assertEqual(serial.current_km, 1500)
        self.assertEqual(serial.battery_level, 90)

        # Verify audit log exists
        logs = frappe.get_all(
            "Notification Log",
            filters={
                "document_type": "Rental Booking",
                "document_name": self.booking.name,
            },
        )
        self.assertGreaterEqual(len(logs), 1)

    def test_check_out_without_optional_fields(self):
        """AC #4: Check-out succeeds without current_km and battery_level."""
        result = check_out(self.booking.name, self.serial_available.name)

        self.assertEqual(result["status"], "success")

        # Verify serial status changed but optional fields remain None
        serial = frappe.get_doc("Bike Serial", self.serial_available.name)
        self.assertEqual(serial.status, "Rented")
