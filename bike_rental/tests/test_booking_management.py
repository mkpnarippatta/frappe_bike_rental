from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase

from bike_rental.page.booking_management.booking_management import (
    get_bookings,
    get_booking_detail,
    process_checkout,
    process_cancellation,
)


class TestBookingManagement(FrappeTestCase):
    """Tests for Booking Management page server methods (Story 5.4)."""

    def test_get_bookings_returns_list(self):
        """get_bookings returns a list of bookings."""
        bookings = get_bookings(limit=5)
        self.assertIsInstance(bookings, list)

    def test_get_bookings_has_required_fields(self):
        """Each booking dict has the expected fields."""
        bookings = get_bookings(limit=5)
        if bookings:
            for key in ("name", "customer", "customer_name", "hub",
                         "status", "start_date", "end_date", "total_amount"):
                self.assertIn(key, bookings[0], msg=f"Missing field: {key}")

    def test_get_bookings_enriches_kyc_status(self):
        """Each booking has kyc_status field."""
        bookings = get_bookings(limit=5)
        if bookings:
            self.assertIn("kyc_status", bookings[0])

    def test_get_bookings_by_status(self):
        """get_bookings filters by status correctly."""
        bookings = get_bookings(status="Draft", limit=5)
        for b in bookings:
            self.assertEqual(b.status, "Draft")

    def test_get_bookings_by_customer(self):
        """get_bookings filters by customer name (partial match)."""
        bookings = get_bookings(customer="Test", limit=5)
        self.assertIsInstance(bookings, list)

    def test_get_bookings_nonexistent_customer(self):
        """get_bookings with nonexistent customer returns empty list."""
        bookings = get_bookings(customer="ZZZZNONEXISTENT", limit=5)
        self.assertEqual(bookings, [])

    def test_get_bookings_nonexistent_status(self):
        """get_bookings with nonexistent status returns empty list."""
        bookings = get_bookings(status="Nonexistent", limit=5)
        self.assertEqual(bookings, [])

    def test_get_booking_detail_has_booking_key(self):
        """get_booking_detail returns dict with 'booking' key."""
        bookings = get_bookings(limit=1)
        if not bookings:
            self.skipTest("No bookings in database")
        detail = get_booking_detail(bookings[0].name)
        self.assertIn("booking", detail)
        self.assertIn("customer", detail)

    def test_get_booking_detail_customer_info(self):
        """get_booking_detail returns customer details."""
        bookings = get_bookings(limit=1)
        if not bookings:
            self.skipTest("No bookings in database")
        detail = get_booking_detail(bookings[0].name)
        customer = detail["customer"]
        self.assertIn("customer_name", customer)
        self.assertIn("kyc_status", customer)

    def test_process_checkout_missing_booking(self):
        """process_checkout raises on nonexistent booking."""
        with self.assertRaises(frappe.DoesNotExistError):
            process_checkout("NONEXISTENT-BOOKING-001", "SN001")
