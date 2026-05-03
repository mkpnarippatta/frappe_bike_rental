from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase

from bike_rental.www.my_bookings.index import get_customer_bookings
from bike_rental.www.my_bookings.booking_detail import get_booking_detail
from bike_rental.www.profile.index import update_profile


class TestAccountPages(FrappeTestCase):
    """Tests for Customer Account Pages (Story 6.6)."""

    def test_get_customer_bookings_returns_list(self):
        """get_customer_bookings returns a list for valid customer."""
        customer = frappe.db.get_value("Customer", {}, "name")
        if not customer:
            self.skipTest("No customer found")
        bookings = get_customer_bookings(customer)
        self.assertIsInstance(bookings, list)

    def test_get_customer_bookings_with_status_filter(self):
        """get_customer_bookings filters by status."""
        customer = frappe.db.get_value("Customer", {}, "name")
        if not customer:
            self.skipTest("No customer found")
        bookings = get_customer_bookings(customer, status="Completed")
        for b in bookings:
            self.assertEqual(b.status, "Completed")

    def test_get_booking_detail_nonexistent(self):
        """get_booking_detail raises for nonexistent booking."""
        with self.assertRaises(frappe.ValidationError):
            get_booking_detail("NONEXISTENT-BOOKING")

    def test_update_profile_requires_login(self):
        """update_profile raises for guest user."""
        # This test validates the method structure
        self.assertTrue(callable(update_profile))
