from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from bike_rental.api.swap_bike import swap_bike


class TestBikeSwap(FrappeTestCase):
    """Tests for bike swap API (Story 3.3)."""

    def setUp(self):
        self.bike_model = frappe.get_doc({
            "doctype": "Bike Model",
            "model_name": "SW-Test Model",
            "brand": "TestBrand",
            "category": "City",
            "base_rate_hourly": 10.00,
            "base_rate_daily": 40.00,
            "included_km": 100,
            "per_km_rate": 2.00,
        }).insert()

        self.hub = frappe.get_doc({
            "doctype": "Hub",
            "hub_name": "SW-Test Hub",
            "location": "Test Location",
            "operating_hours_start": "06:00:00",
            "operating_hours_end": "22:00:00",
        }).insert()

        self.customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": "SW-Test Customer",
            "email": "sw-test@example.com",
            "phone": "+1888888890",
        }).insert()

        self.serial_a = frappe.get_doc({
            "doctype": "Bike Serial",
            "registration_no": "SW-SER-A",
            "chassis_no": "CH-SW-SER-A",
            "bike_model": self.bike_model.name,
            "hub": self.hub.name,
            "status": "Rented",
            "current_km": 100,
        }).insert()

        self.serial_b = frappe.get_doc({
            "doctype": "Bike Serial",
            "registration_no": "SW-SER-B",
            "chassis_no": "CH-SW-SER-B",
            "bike_model": self.bike_model.name,
            "hub": self.hub.name,
            "status": "Available",
            "current_km": 50,
        }).insert()

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

    def _make_active_booking(self):
        """Create an Active booking with serial_a."""
        booking = frappe.get_doc({
            "doctype": "Rental Booking",
            "bike_model": self.bike_model.name,
            "customer": self.customer.name,
            "pickup_hub": self.hub.name,
            "return_hub": self.hub.name,
            "pickup_datetime": add_to_date(now_datetime(), hours=-2),
            "return_datetime": add_to_date(now_datetime(), days=2),
            "bike_serial": self.serial_a.name,
            "total_amount": 100.00,
            "status": "Active",
        }).insert(ignore_permissions=True)
        return booking

    def test_successful_swap(self):
        """Swap from serial_a to serial_b succeeds."""
        booking = self._make_active_booking()
        result = swap_bike(
            booking.name, new_serial_no=self.serial_b.name,
            end_km=120,
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["booking_status"], "Active")
        self.assertEqual(result["previous_serial"], self.serial_a.name)
        self.assertEqual(result["new_serial"], self.serial_b.name)

        # Verify serial A is now Available with KM updated
        self.serial_a.reload()
        self.assertEqual(self.serial_a.status, "Available")
        self.assertEqual(self.serial_a.current_km, 120)

        # Verify serial B is now Rented
        self.serial_b.reload()
        self.assertEqual(self.serial_b.status, "Rented")

        # Verify booking now references serial B
        booking.reload()
        self.assertEqual(booking.bike_serial, self.serial_b.name)

    def test_swap_not_active_blocked(self):
        """Non-Active booking cannot swap."""
        booking = self._make_active_booking()
        booking.db_set("status", "Confirmed")
        with self.assertRaises(frappe.ValidationError):
            swap_bike(booking.name, new_serial_no=self.serial_b.name, end_km=120)

    def test_swap_new_serial_not_available_blocked(self):
        """New serial must be Available."""
        booking = self._make_active_booking()
        self.serial_b.db_set("status", "Rented")
        with self.assertRaises(frappe.ValidationError):
            swap_bike(booking.name, new_serial_no=self.serial_b.name, end_km=120)

    def test_swap_same_serial_blocked(self):
        """Swapping to the same serial is rejected."""
        booking = self._make_active_booking()
        with self.assertRaises(frappe.ValidationError):
            swap_bike(booking.name, new_serial_no=self.serial_a.name, end_km=120)

    def test_swap_wrong_model_blocked(self):
        """Swap to a different model is rejected."""
        other_model = frappe.get_doc({
            "doctype": "Bike Model",
            "model_name": "SW-Other Model",
            "brand": "OtherBrand",
            "category": "Mountain",
            "base_rate_hourly": 15.00,
            "base_rate_daily": 60.00,
            "included_km": 50,
            "per_km_rate": 3.00,
        }).insert()

        other_serial = frappe.get_doc({
            "doctype": "Bike Serial",
            "registration_no": "SW-SER-C",
            "chassis_no": "CH-SW-SER-C",
            "bike_model": other_model.name,
            "hub": self.hub.name,
            "status": "Available",
            "current_km": 10,
        }).insert()

        booking = self._make_active_booking()
        with self.assertRaises(frappe.ValidationError):
            swap_bike(booking.name, new_serial_no=other_serial.name, end_km=120)

        frappe.delete_doc("Bike Serial", other_serial.name, force=True)
        frappe.delete_doc("Bike Model", other_model.name, force=True)

    def test_swap_end_km_validation(self):
        """End KM less than start KM on current bike is rejected."""
        booking = self._make_active_booking()
        with self.assertRaises(frappe.ValidationError):
            swap_bike(booking.name, new_serial_no=self.serial_b.name, end_km=50)

    def test_swap_with_damage_and_battery(self):
        """Damage notes and battery level recorded on swap."""
        booking = self._make_active_booking()
        result = swap_bike(
            booking.name, new_serial_no=self.serial_b.name,
            end_km=130, end_battery=70,
            damage_notes="Broken mirror",
        )
        self.assertEqual(result["status"], "success")

    def test_swap_current_serial_not_rented_blocked(self):
        """Current serial must be Rented to swap."""
        booking = self._make_active_booking()
        self.serial_a.db_set("status", "Available")
        with self.assertRaises(frappe.ValidationError):
            swap_bike(booking.name, new_serial_no=self.serial_b.name, end_km=120)

    def test_swap_no_bike_serial_blocked(self):
        """Booking without a serial cannot swap."""
        booking = self._make_active_booking()
        booking.db_set("bike_serial", None)
        with self.assertRaises(frappe.ValidationError):
            swap_bike(booking.name, new_serial_no=self.serial_b.name, end_km=120)
