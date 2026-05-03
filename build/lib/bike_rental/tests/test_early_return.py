from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from bike_rental.api.early_return import process_early_return


class TestEarlyReturn(FrappeTestCase):
    """Tests for early return API (Story 3.3)."""

    def setUp(self):
        self.bike_model = frappe.get_doc({
            "doctype": "Bike Model",
            "model_name": "ER-Test Model",
            "brand": "TestBrand",
            "category": "City",
            "base_rate_hourly": 10.00,
            "base_rate_daily": 40.00,
            "included_km": 100,
            "per_km_rate": 2.00,
        }).insert()

        self.hub = frappe.get_doc({
            "doctype": "Hub",
            "hub_name": "ER-Test Hub",
            "location": "Test Location",
            "operating_hours_start": "06:00:00",
            "operating_hours_end": "22:00:00",
        }).insert()

        self.customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": "ER-Test Customer",
            "email": "er-test@example.com",
            "phone": "+1888888889",
        }).insert()

        self.serial = frappe.get_doc({
            "doctype": "Bike Serial",
            "registration_no": "ER-SER-001",
            "chassis_no": "CH-ER-SER-001",
            "bike_model": self.bike_model.name,
            "hub": self.hub.name,
            "status": "Rented",
            "current_km": 100,
        }).insert()

    def tearDown(self):
        for name in frappe.get_all("Sales Invoice", pluck="name"):
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

    def _make_active_booking(self, pickup_offset_hours=-2, return_offset_hours=46):
        """Create an Active booking for testing."""
        pickup = add_to_date(now_datetime(), hours=pickup_offset_hours)
        return_dt = add_to_date(now_datetime(), hours=return_offset_hours)

        booking = frappe.get_doc({
            "doctype": "Rental Booking",
            "bike_model": self.bike_model.name,
            "customer": self.customer.name,
            "pickup_hub": self.hub.name,
            "return_hub": self.hub.name,
            "pickup_datetime": pickup,
            "return_datetime": return_dt,
            "bike_serial": self.serial.name,
            "total_amount": 200.00,
            "status": "Active",
        }).insert(ignore_permissions=True)
        return booking

    def test_early_return_more_than_4h_early(self):
        """Early return >4h before scheduled end gets pro-rata refund."""
        # Booking scheduled to end 46h from now, returning now = ~46h early
        hours_early = 46
        booking = self._make_active_booking(
            pickup_offset_hours=-2, return_offset_hours=hours_early
        )
        result = process_early_return(
            booking.name, end_km=120,
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["booking_status"], "Completed")
        self.assertEqual(result["serial_status"], "Available")
        self.assertGreater(result["early_refund"], 0)
        self.assertGreater(result["hours_early"], 4)

    def test_early_return_under_4h_no_refund(self):
        """Early return <4h before scheduled end = no refund (FR-21 buffer)."""
        # Booking scheduled to end 3h from now, returning now
        booking = self._make_active_booking(
            pickup_offset_hours=-2, return_offset_hours=3
        )
        result = process_early_return(
            booking.name, end_km=110,
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["early_refund"], 0)
        self.assertLess(result["hours_early"], 4)

    def test_early_return_not_active_blocked(self):
        """Non-Active booking cannot early-return."""
        booking = self._make_active_booking()
        booking.db_set("status", "Confirmed")
        with self.assertRaises(frappe.ValidationError):
            process_early_return(booking.name, end_km=120)

    def test_early_return_no_serial_blocked(self):
        """Booking without serial cannot early-return."""
        booking = self._make_active_booking()
        booking.db_set("bike_serial", None)
        with self.assertRaises(frappe.ValidationError):
            process_early_return(booking.name, end_km=120)

    def test_early_return_serial_not_rented_blocked(self):
        """Serial not in Rented status blocks early return."""
        booking = self._make_active_booking()
        self.serial.db_set("status", "Available")
        with self.assertRaises(frappe.ValidationError):
            process_early_return(booking.name, end_km=120)

    def test_early_return_end_km_validation(self):
        """End KM less than start KM is rejected."""
        booking = self._make_active_booking()
        with self.assertRaises(frappe.ValidationError):
            process_early_return(booking.name, end_km=50)

    def test_early_return_with_damage_and_battery(self):
        """Damage notes and battery level are recorded."""
        booking = self._make_active_booking()
        result = process_early_return(
            booking.name, end_km=150,
            end_battery=60, damage_notes="Scratched frame",
            damage_amount=25.00,
        )
        self.assertEqual(result["status"], "success")
        booking.reload()
        self.assertEqual(booking.end_km, 150)
        self.assertEqual(booking.end_battery_level, 60)
        self.assertEqual(booking.damage_notes, "Scratched frame")

    def test_early_return_updates_serial(self):
        """Early return sets serial to Available with updated KM."""
        booking = self._make_active_booking()
        process_early_return(booking.name, end_km=180)
        self.serial.reload()
        self.assertEqual(self.serial.status, "Available")
        self.assertEqual(self.serial.current_km, 180)

    def test_early_return_generates_invoice(self):
        """Early return creates a submitted Sales Invoice."""
        booking = self._make_active_booking()
        result = process_early_return(booking.name, end_km=130)
        self.assertIsNotNone(result["invoice"])
        invoice = frappe.get_doc("Sales Invoice", result["invoice"])
        self.assertEqual(invoice.docstatus, 1)  # submitted

    def test_early_return_exact_4h_boundary(self):
        """Early return exactly at 4h boundary = no refund (FR-21)."""
        # Return at exactly 4h before scheduled end
        now = now_datetime()
        pickup = add_to_date(now, hours=-10)
        return_dt = add_to_date(now, hours=4)  # 4h from now
        # So actual end = now, scheduled = now+4h => hours_early = 4

        booking = frappe.get_doc({
            "doctype": "Rental Booking",
            "bike_model": self.bike_model.name,
            "customer": self.customer.name,
            "pickup_hub": self.hub.name,
            "return_hub": self.hub.name,
            "pickup_datetime": pickup,
            "return_datetime": return_dt,
            "bike_serial": self.serial.name,
            "total_amount": 100.00,
            "status": "Active",
        }).insert(ignore_permissions=True)

        result = process_early_return(booking.name, end_km=110)
        # At exactly 4h, the condition is hours_early > 4, so 4 is NOT > 4
        self.assertEqual(result["early_refund"], 0)
        self.assertAlmostEqual(result["hours_early"], 4.0, places=1)
