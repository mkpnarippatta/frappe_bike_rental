from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from bike_rental.api.extend_rental import extend_rental


class TestExtendRental(FrappeTestCase):
    """Tests for mid-rental extension API (Story 3.2)."""

    def setUp(self):
        self.bike_model = frappe.get_doc(
            {
                "doctype": "Bike Model",
                "model_name": "EX-Test Model",
                "brand": "TestBrand",
                "category": "City",
                "base_rate_hourly": 10.00,
                "base_rate_daily": 40.00,
                "included_km": 100,
                "per_km_rate": 2.00,
            }
        ).insert()

        self.hub = frappe.get_doc(
            {
                "doctype": "Hub",
                "hub_name": "EX-Test Hub",
                "location": "Test Location",
                "operating_hours_start": "06:00:00",
                "operating_hours_end": "22:00:00",
            }
        ).insert()

        self.customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": "EX-Test Customer",
                "email": "ex-test@example.com",
                "phone": "+1999999999",
            }
        ).insert()

        self.serial = frappe.get_doc(
            {
                "doctype": "Bike Serial",
                "registration_no": "EX-SER-001",
                "chassis_no": "CH-EX-SER-001",
                "bike_model": self.bike_model.name,
                "hub": self.hub.name,
                "status": "Rented",
                "current_km": 500,
            }
        ).insert()

        self.booking = frappe.get_doc(
            {
                "doctype": "Rental Booking",
                "bike_model": self.bike_model.name,
                "customer": self.customer.name,
                "pickup_hub": self.hub.name,
                "return_hub": self.hub.name,
                "pickup_datetime": add_to_date(now_datetime(), hours=-1),
                "return_datetime": add_to_date(now_datetime(), days=1),
                "bike_serial": self.serial.name,
                "total_amount": 40.00,
                "status": "Active",
            }
        ).insert(ignore_permissions=True)

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
        frappe.delete_doc("Bike Model", self.bike_model.name, force=True)

    def test_extend_active_booking(self):
        """Active booking can be extended."""
        new_return = add_to_date(self.booking.return_datetime, hours=6)
        result = extend_rental(self.booking.name, str(new_return))
        self.assertEqual(result["status"], "success")
        self.assertGreater(result["additional_charge"], 0)

        booking = frappe.get_doc("Rental Booking", self.booking.name)
        self.assertAlmostEqual(booking.total_amount, result["total_amount"])

    def test_non_active_booking_blocked(self):
        """Non-Active booking cannot be extended."""
        self.booking.db_set("status", "Confirmed")
        new_return = add_to_date(self.booking.return_datetime, hours=6)
        with self.assertRaises(frappe.ValidationError):
            extend_rental(self.booking.name, str(new_return))

    def test_earlier_return_blocked(self):
        """New return before current return is blocked."""
        earlier = add_to_date(self.booking.return_datetime, hours=-1)
        with self.assertRaises(frappe.ValidationError):
            extend_rental(self.booking.name, str(earlier))

    def test_extension_blocked_if_overlapping(self):
        """Extension blocked if another booking overlaps."""
        other_serial = frappe.get_doc(
            {
                "doctype": "Bike Serial",
                "registration_no": "EX-SER-002",
                "chassis_no": "CH-EX-SER-002",
                "bike_model": self.bike_model.name,
                "hub": self.hub.name,
                "status": "Rented",
                "current_km": 200,
            }
        ).insert()

        frappe.get_doc(
            {
                "doctype": "Rental Booking",
                "bike_model": self.bike_model.name,
                "customer": self.customer.name,
                "pickup_hub": self.hub.name,
                "return_hub": self.hub.name,
                "pickup_datetime": add_to_date(self.booking.return_datetime, hours=2),
                "return_datetime": add_to_date(self.booking.return_datetime, days=1),
                "bike_serial": other_serial.name,
                "total_amount": 40.00,
                "status": "Confirmed",
            }
        ).insert(ignore_permissions=True)

        # Extending into the other booking's time slot should be blocked
        new_return = add_to_date(self.booking.return_datetime, hours=4)
        with self.assertRaises(frappe.ValidationError):
            extend_rental(self.booking.name, str(new_return))
