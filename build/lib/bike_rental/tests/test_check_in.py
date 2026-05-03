from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from bike_rental.api.check_in import check_in


class TestCheckIn(FrappeTestCase):
    """Integration tests for check-in API (Story 2.6)."""

    def setUp(self):
        self.bike_model = frappe.get_doc(
            {
                "doctype": "Bike Model",
                "model_name": "CI-Test Model",
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
                "hub_name": "CI-Test Hub",
                "location": "Test Location",
                "operating_hours_start": "06:00:00",
                "operating_hours_end": "22:00:00",
            }
        ).insert()

        self.customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": "CI-Test Customer",
                "email": "ci-test@example.com",
                "phone": "+1555555555",
            }
        ).insert()

        # Create service item for invoice
        try:
            self.service_item = frappe.get_doc(
                {
                    "doctype": "Item",
                    "item_code": "Rental Service",
                    "item_name": "Rental Service",
                    "item_group": "Services",
                    "is_stock_item": 0,
                }
            ).insert(ignore_permissions=True)
        except frappe.DuplicateEntryError:
            self.service_item = frappe.get_doc("Item", "Rental Service")

        # Serial with starting KM (simulates check-out)
        self.serial = frappe.get_doc(
            {
                "doctype": "Bike Serial",
                "registration_no": "CI-SER-001",
                "chassis_no": "CH-CI-SER-001",
                "bike_model": self.bike_model.name,
                "hub": self.hub.name,
                "status": "Rented",
                "current_km": 1000,
            }
        ).insert()

        self.serial_no_serial = frappe.get_doc(
            {
                "doctype": "Bike Serial",
                "registration_no": "CI-SER-002",
                "chassis_no": "CH-CI-SER-002",
                "bike_model": self.bike_model.name,
                "hub": self.hub.name,
                "status": "Rented",
                "current_km": 500,
            }
        ).insert()

        # Active booking with serial
        self.booking = frappe.get_doc(
            {
                "doctype": "Rental Booking",
                "bike_model": self.bike_model.name,
                "customer": self.customer.name,
                "pickup_hub": self.hub.name,
                "return_hub": self.hub.name,
                "pickup_datetime": add_to_date(now_datetime(), days=1),
                "return_datetime": add_to_date(now_datetime(), days=3),
                "bike_serial": self.serial.name,
                "total_amount": 80.00,
            }
        ).insert()
        self.booking.db_set("status", "Active")
        self.booking.reload()

        # Active booking WITHOUT serial (for no-serial test)
        self.booking_no_serial = frappe.get_doc(
            {
                "doctype": "Rental Booking",
                "bike_model": self.bike_model.name,
                "customer": self.customer.name,
                "pickup_hub": self.hub.name,
                "return_hub": self.hub.name,
                "pickup_datetime": add_to_date(now_datetime(), days=1),
                "return_datetime": add_to_date(now_datetime(), days=3),
                "total_amount": 80.00,
            }
        ).insert()
        self.booking_no_serial.db_set("status", "Active")
        self.booking_no_serial.reload()

    def tearDown(self):
        # Clean up Sales Invoices first (cancel + delete)
        for name in frappe.get_all("Sales Invoice", pluck="name"):
            try:
                frappe.get_doc("Sales Invoice", name).cancel()
            except Exception:
                pass
            frappe.delete_doc("Sales Invoice", name, force=True)

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
        if hasattr(self, "service_item") and self.service_item:
            try:
                frappe.delete_doc("Item", self.service_item.name, force=True)
            except Exception:
                pass

    # --- AC #1: Booking Status Validation ---

    def test_check_in_validates_booking_status(self):
        """Non-Active booking is blocked."""
        draft = frappe.get_doc(
            {
                "doctype": "Rental Booking",
                "bike_model": self.bike_model.name,
                "customer": self.customer.name,
                "pickup_hub": self.hub.name,
                "return_hub": self.hub.name,
                "pickup_datetime": add_to_date(now_datetime(), days=1),
                "return_datetime": add_to_date(now_datetime(), days=3),
                "customer_name": self.customer.customer_name,
                "customer_phone": self.customer.phone,
            }
        ).insert()

        with self.assertRaises(frappe.ValidationError) as cm:
            check_in(draft.name, end_km=1000)
        self.assertIn("Active", str(cm.exception))
        frappe.delete_doc("Rental Booking", draft.name, force=True)

    # --- AC #1: Serial Assignment Validation ---

    def test_check_in_no_serial(self):
        """Booking without bike serial is blocked."""
        with self.assertRaises(frappe.ValidationError) as cm:
            check_in(self.booking_no_serial.name, end_km=1000)
        self.assertIn("serial", str(cm.exception))

    # --- AC #2-3: Full Check-In Flow ---

    def test_check_in_full_flow(self):
        """Complete check-in with charges, invoice, status updates."""
        result = check_in(
            self.booking.name,
            end_km=1200,
            end_battery=70,
            damage_notes="Minor scratch on left fairing",
            damage_amount=25.00,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["booking_status"], "Completed")
        self.assertEqual(result["serial_status"], "Available")

        # Verify booking updated
        booking = frappe.get_doc("Rental Booking", self.booking.name)
        self.assertEqual(booking.status, "Completed")
        self.assertEqual(booking.end_km, 1200)
        self.assertEqual(booking.end_battery_level, 70)
        self.assertEqual(booking.damage_notes, "Minor scratch on left fairing")

        # Verify charges stored
        self.assertGreater(booking.excess_km_charges, 0)

        # Verify serial updated
        serial = frappe.get_doc("Bike Serial", self.serial.name)
        self.assertEqual(serial.status, "Available")
        self.assertEqual(serial.current_km, 1200)

        # Verify invoice created
        self.assertIsNotNone(booking.invoice_ref)
        invoice = frappe.get_doc("Sales Invoice", booking.invoice_ref)
        self.assertEqual(invoice.total, result["charges"]["total"])

        # Verify deposit released flagged
        self.assertEqual(booking.deposit_released, 1)

        # Verify audit log
        logs = frappe.get_all(
            "Notification Log",
            filters={
                "document_type": "Rental Booking",
                "document_name": self.booking.name,
            },
        )
        self.assertGreaterEqual(len(logs), 1)

    # --- AC: End KM validation ---

    def test_check_in_end_km_below_start_km_blocked(self):
        """End KM below starting KM is blocked."""
        with self.assertRaises(frappe.ValidationError) as cm:
            check_in(self.booking.name, end_km=500)  # start_km=1000
        self.assertIn("end_km", str(cm.exception).lower())

    # --- AC: Serial Rented status validation ---

    def test_check_in_serial_not_rented_blocked(self):
        """Serial not in Rented status is blocked."""
        self.serial.db_set("status", "Available")
        with self.assertRaises(frappe.ValidationError) as cm:
            check_in(self.booking.name, end_km=1000)
        self.assertIn("Rented", str(cm.exception))
