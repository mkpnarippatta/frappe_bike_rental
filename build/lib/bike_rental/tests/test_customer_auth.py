from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase

from bike_rental.www.register.index import register_customer


class TestCustomerAuth(FrappeTestCase):
    """Tests for Customer Portal Auth (Story 6.3)."""

    def test_register_requires_email(self):
        """register_customer raises without email."""
        with self.assertRaises(frappe.ValidationError):
            register_customer("Test User", "", "1234567890", "password123")

    def test_register_requires_password(self):
        """register_customer raises without password."""
        with self.assertRaises(frappe.ValidationError):
            register_customer("Test User", "test@example.com", "1234567890", "")

    def test_register_returns_message(self):
        """register_customer returns success message on valid input."""
        # Use a unique email to avoid conflicts
        import uuid
        unique = uuid.uuid4().hex[:8]
        email = "test_{}@example.com".format(unique)
        result = register_customer("Test User", email, "9988776655", "testpass123")
        self.assertIn("user", result)
        self.assertIn("customer", result)
        self.assertIn("message", result)

        # Cleanup
        frappe.db.rollback()

    def test_register_duplicate_email(self):
        """register_customer raises on duplicate email."""
        import uuid
        unique = uuid.uuid4().hex[:8]
        email = "dup_{}@example.com".format(unique)
        register_customer("First User", email, "1111111111", "password1")
        with self.assertRaises(frappe.DuplicateEntryError):
            register_customer("Second User", email, "2222222222", "password2")

        # Cleanup
        frappe.db.rollback()
