from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from bike_rental.scheduler.expire_ghost_bookings import expire_ghost_bookings


class TestGhostBookings(FrappeTestCase):
    """Tests for ghost-booking expiry scheduled job (Story 2.8)."""

    def setUp(self):
        self.bike_model = frappe.get_doc(
            {
                "doctype": "Bike Model",
                "model_name": "GH-Test Model",
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
                "hub_name": "GH-Test Hub",
                "location": "Test Location",
                "operating_hours_start": "06:00:00",
                "operating_hours_end": "22:00:00",
            }
        ).insert()

        self.customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": "GH-Test Customer",
                "email": "gh-test@example.com",
                "phone": "+1777777777",
            }
        ).insert()

        # Booking that expired (pickup 3 hours ago, still Confirmed)
        self.expired_booking = frappe.get_doc(
            {
                "doctype": "Rental Booking",
                "bike_model": self.bike_model.name,
                "customer": self.customer.name,
                "pickup_hub": self.hub.name,
                "return_hub": self.hub.name,
                "pickup_datetime": add_to_date(now_datetime(), hours=-3),
                "return_datetime": add_to_date(now_datetime(), hours=21),
                "total_amount": 80.00,
                "status": "Confirmed",
            }
        ).insert(ignore_permissions=True)

        # Booking within window but not yet expired (pickup 30 min ago)
        self.recent_booking = frappe.get_doc(
            {
                "doctype": "Rental Booking",
                "bike_model": self.bike_model.name,
                "customer": self.customer.name,
                "pickup_hub": self.hub.name,
                "return_hub": self.hub.name,
                "pickup_datetime": add_to_date(now_datetime(), hours=-0.5),
                "return_datetime": add_to_date(now_datetime(), hours=23.5),
                "total_amount": 80.00,
                "status": "Confirmed",
            }
        ).insert(ignore_permissions=True)

        # Booking already Active (checked out) — should not be touched
        self.active_booking = frappe.get_doc(
            {
                "doctype": "Rental Booking",
                "bike_model": self.bike_model.name,
                "customer": self.customer.name,
                "pickup_hub": self.hub.name,
                "return_hub": self.hub.name,
                "pickup_datetime": add_to_date(now_datetime(), hours=-4),
                "return_datetime": add_to_date(now_datetime(), hours=20),
                "total_amount": 80.00,
                "status": "Active",
            }
        ).insert(ignore_permissions=True)

    def tearDown(self):
        for name in frappe.get_all("Rental Booking", pluck="name"):
            frappe.delete_doc("Rental Booking", name, force=True)
        for name in frappe.get_all("Customer", pluck="name"):
            if name != self.customer.name:
                frappe.delete_doc("Customer", name, force=True)
        frappe.delete_doc("Customer", self.customer.name, force=True)
        frappe.delete_doc("Hub", self.hub.name, force=True)
        frappe.delete_doc("Bike Model", self.bike_model.name, force=True)

    def test_expires_old_confirmed_bookings(self):
        """Confirmed booking >2h past pickup is expired."""
        expire_ghost_bookings()
        expired = frappe.get_doc("Rental Booking", self.expired_booking.name)
        self.assertEqual(expired.status, "Expired")

    def test_does_not_expire_recent_bookings(self):
        """Confirmed booking within 2h window is not expired."""
        expire_ghost_bookings()
        recent = frappe.get_doc("Rental Booking", self.recent_booking.name)
        self.assertEqual(recent.status, "Confirmed")

    def test_does_not_affect_active_bookings(self):
        """Active bookings are never touched."""
        expire_ghost_bookings()
        active = frappe.get_doc("Rental Booking", self.active_booking.name)
        self.assertEqual(active.status, "Active")

    def test_idempotent(self):
        """Running twice does not error or double-process."""
        expire_ghost_bookings()
        expire_ghost_bookings()  # second run
        expired = frappe.get_doc("Rental Booking", self.expired_booking.name)
        self.assertEqual(expired.status, "Expired")
