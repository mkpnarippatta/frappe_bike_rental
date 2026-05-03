from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from bike_rental.api.payments import create_cash_payment


class TestPaymentIntegration(FrappeTestCase):
    """Integration tests for Payment Entry → Rental Booking flow (Story 2.4)."""

    def setUp(self):
        self.bike_model = frappe.get_doc(
            {
                "doctype": "Bike Model",
                "model_name": "PAY-Test Model",
                "brand": "TestBrand",
                "category": "City",
                "base_rate_hourly": 10.00,
                "base_rate_daily": 40.00,
            }
        ).insert()

        self.hub = frappe.get_doc(
            {
                "doctype": "Hub",
                "hub_name": "PAY-Test Hub",
                "location": "Test Location",
                "operating_hours_start": "06:00:00",
                "operating_hours_end": "22:00:00",
            }
        ).insert()

        self.customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": "PAY-Test Customer",
                "email": "pay-test@example.com",
                "phone": "+1222222222",
            }
        ).insert()

        # Create Bike Serials so availability check passes
        self._create_serial("PAY-INT-001")
        self._create_serial("PAY-INT-002")

        self.booking = frappe.get_doc(
            {
                "doctype": "Rental Booking",
                "bike_model": self.bike_model.name,
                "customer": self.customer.name,
                "pickup_hub": self.hub.name,
                "return_hub": self.hub.name,
                "pickup_datetime": add_to_date(now_datetime(), days=7, hours=10),
                "return_datetime": add_to_date(now_datetime(), days=9, hours=10),
                "customer_name": self.customer.customer_name,
                "customer_phone": self.customer.phone,
            }
        ).insert()

    def tearDown(self):
        # Clean up Payment Entries first
        for name in frappe.get_all("Payment Entry", pluck="name"):
            try:
                frappe.get_doc("Payment Entry", name).cancel()
            except Exception:
                pass
            frappe.delete_doc("Payment Entry", name, force=True)

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

    def _create_serial(self, reg):
        return frappe.get_doc(
            {
                "doctype": "Bike Serial",
                "registration_no": reg,
                "chassis_no": f"CH-{reg}",
                "bike_model": self.bike_model.name,
                "hub": self.hub.name,
                "status": "Available",
            }
        ).insert()

    def test_create_cash_payment_confirms_booking(self):
        """AC #3-4: create_cash_payment creates PE and confirms booking."""
        result = create_cash_payment(self.booking.name, 100.00)

        self.assertEqual(result["status"], "Confirmed")
        self.assertIsNotNone(result["payment_entry"])

        # Verify Payment Entry exists
        pe = frappe.get_doc("Payment Entry", result["payment_entry"])
        self.assertEqual(pe.payment_type, "Receive")
        self.assertEqual(pe.party_type, "Customer")
        self.assertEqual(pe.party, self.customer.name)
        self.assertEqual(pe.paid_amount, 100.00)

        # Verify booking is linked and Confirmed
        booking = frappe.get_doc("Rental Booking", self.booking.name)
        self.assertEqual(booking.status, "Confirmed")
        self.assertEqual(booking.payment_entry, pe.name)

        # Verify reference on Payment Entry
        self.assertEqual(len(pe.references), 1)
        self.assertEqual(pe.references[0].reference_doctype, "Rental Booking")
        self.assertEqual(pe.references[0].reference_name, self.booking.name)
        self.assertEqual(pe.references[0].allocated_amount, 100.00)
