from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase

from bike_rental.www.checkout.index import create_booking


class TestCheckout(FrappeTestCase):
    """Tests for Checkout & Payment Flow (Story 6.5)."""

    def test_create_booking_requires_customer(self):
        """create_booking raises for unknown customer email."""
        with self.assertRaises(frappe.ValidationError):
            create_booking("Test Model", "Test Hub",
                          "2026-07-01 10:00:00", "2026-07-03 10:00:00",
                          customer_email="nonexistent@example.com")

    def test_create_booking_structure(self):
        """create_booking returns expected keys on success."""
        # Find a valid model and hub
        model = frappe.get_all("Bike Model", limit=1)
        hub = frappe.get_all("Hub", limit=1)

        # Find a customer with email
        customer_email = frappe.db.get_value("Customer",
            filters={"email": ["!=", ""]},
            fieldname="email")
        customer_name = frappe.db.get_value("Customer",
            filters={"email": customer_email},
            fieldname="name") if customer_email else None

        if not model or not hub or not customer_email or not customer_name:
            self.skipTest("Required test data not available")

        result = create_booking(
            model[0].name, hub[0].name,
            "2026-08-01 10:00:00", "2026-08-03 10:00:00",
            customer_email=customer_email,
        )
        self.assertIn("name", result)
        self.assertIn("total_amount", result)
        self.assertIn("status", result)
        self.assertEqual(result["status"], "Draft")

        # Cleanup
        frappe.db.rollback()
