from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCustomer(FrappeTestCase):
    """Minimal Customer DocType tests (expanded in Epic 4)."""

    def setUp(self):
        self.customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": "Test Customer",
                "email": "test@example.com",
                "phone": "+1234567890",
            }
        ).insert()

    def tearDown(self):
        if frappe.db.exists("Customer", self.customer.name):
            frappe.delete_doc("Customer", self.customer.name, force=True)

    def test_create_with_all_fields(self):
        """Verify all fields are stored correctly."""
        self.assertEqual(self.customer.customer_name, "Test Customer")
        self.assertEqual(self.customer.email, "test@example.com")
        self.assertEqual(self.customer.phone, "+1234567890")
        self.assertEqual(self.customer.disabled, 0)

    def test_create_minimal_fields(self):
        """Verify creation with only required fields."""
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": "Minimal Customer",
                "email": "minimal@example.com",
                "phone": "+9876543210",
            }
        ).insert()

        self.assertEqual(customer.disabled, 0)

        frappe.delete_doc("Customer", customer.name, force=True)

    def test_email_validation(self):
        """Verify email field is required."""
        with self.assertRaises(frappe.MandatoryError):
            frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": "No Email",
                }
            ).insert()
