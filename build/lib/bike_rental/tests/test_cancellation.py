from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from bike_rental.api.cancel_booking import cancel_booking, calculate_refund


class TestCancellation(FrappeTestCase):
    """Tests for cancellation API (Story 3.1)."""

    def setUp(self):
        self.bike_model = frappe.get_doc(
            {
                "doctype": "Bike Model",
                "model_name": "CN-Test Model",
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
                "hub_name": "CN-Test Hub",
                "location": "Test Location",
                "operating_hours_start": "06:00:00",
                "operating_hours_end": "22:00:00",
            }
        ).insert()

        self.customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": "CN-Test Customer",
                "email": "cn-test@example.com",
                "phone": "+1888888888",
            }
        ).insert()

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

    def _make_booking(self, pickup_offset_hours=None, status="Draft"):
        """Helper to create a booking with configurable pickup time."""
        if pickup_offset_hours is None:
            pickup = add_to_date(now_datetime(), days=3)
        else:
            pickup = add_to_date(now_datetime(), hours=pickup_offset_hours)

        booking = frappe.get_doc(
            {
                "doctype": "Rental Booking",
                "bike_model": self.bike_model.name,
                "customer": self.customer.name,
                "pickup_hub": self.hub.name,
                "return_hub": self.hub.name,
                "pickup_datetime": pickup,
                "return_datetime": add_to_date(pickup, days=2),
                "total_amount": 80.00,
                "status": status,
            }
        ).insert(ignore_permissions=True)
        return booking

    # --- Refund Policy Tests ---

    def test_full_refund_more_than_48h(self):
        """Booking >48h before pickup = full refund."""
        booking = self._make_booking(pickup_offset_hours=72)
        refund = calculate_refund(booking)
        self.assertEqual(refund["refund_amount"], 80.00)
        self.assertIn("Full refund", refund["policy"])

    def test_half_refund_24_to_48h(self):
        """Booking 24-48h before pickup = 50% refund."""
        booking = self._make_booking(pickup_offset_hours=36)
        refund = calculate_refund(booking)
        self.assertEqual(refund["refund_amount"], 40.00)
        self.assertIn("50% refund", refund["policy"])

    def test_no_refund_under_24h(self):
        """Booking <24h before pickup = no refund."""
        booking = self._make_booking(pickup_offset_hours=12)
        refund = calculate_refund(booking)
        self.assertEqual(refund["refund_amount"], 0)
        self.assertIn("No refund", refund["policy"])

    # --- Status Validation ---

    def test_cancel_draft_booking(self):
        """Draft booking can be cancelled."""
        booking = self._make_booking(status="Draft")
        result = cancel_booking(booking.name)
        self.assertEqual(result["booking_status"], "Cancelled")
        self.assertEqual(result["refund"]["refund_amount"], 80.00)

    def test_cancel_confirmed_booking(self):
        """Confirmed booking can be cancelled."""
        booking = self._make_booking(status="Confirmed")
        result = cancel_booking(booking.name)
        self.assertEqual(result["booking_status"], "Cancelled")

    def test_cancel_completed_blocked(self):
        """Completed booking cannot be cancelled."""
        booking = self._make_booking(status="Completed")
        with self.assertRaises(frappe.ValidationError):
            cancel_booking(booking.name)

    # --- Active Booking Cancellation ---

    def test_cancel_active_releases_serial(self):
        """Active booking cancellation releases serial to Available."""
        serial = frappe.get_doc(
            {
                "doctype": "Bike Serial",
                "registration_no": "CN-SER-001",
                "chassis_no": "CH-CN-SER-001",
                "bike_model": self.bike_model.name,
                "hub": self.hub.name,
                "status": "Rented",
                "current_km": 500,
            }
        ).insert()

        booking = frappe.get_doc(
            {
                "doctype": "Rental Booking",
                "bike_model": self.bike_model.name,
                "customer": self.customer.name,
                "pickup_hub": self.hub.name,
                "return_hub": self.hub.name,
                "pickup_datetime": add_to_date(now_datetime(), hours=-2),
                "return_datetime": add_to_date(now_datetime(), days=2),
                "bike_serial": serial.name,
                "total_amount": 80.00,
                "status": "Active",
            }
        ).insert(ignore_permissions=True)

        result = cancel_booking(booking.name)
        self.assertEqual(result["booking_status"], "Cancelled")

        serial.reload()
        self.assertEqual(serial.status, "Available")
        self.assertGreater(result["refund"]["refund_amount"], 0)

    def test_cancel_already_cancelled_blocked(self):
        """Already-cancelled booking cannot be cancelled again."""
        booking = self._make_booking(status="Draft")
        cancel_booking(booking.name)  # first cancel succeeds
        with self.assertRaises(frappe.ValidationError):
            cancel_booking(booking.name)  # second fails

    def test_cancel_expired_blocked(self):
        """Expired booking cannot be cancelled."""
        booking = self._make_booking(status="Expired")
        with self.assertRaises(frappe.ValidationError):
            cancel_booking(booking.name)

    def test_cancel_with_reason(self):
        """Cancellation reason is stored."""
        booking = self._make_booking(status="Confirmed")
        result = cancel_booking(booking.name, reason="Change of plans")
        self.assertEqual(result["booking_status"], "Cancelled")
        booking.reload()
        self.assertEqual(booking.cancellation_reason, "Change of plans")
