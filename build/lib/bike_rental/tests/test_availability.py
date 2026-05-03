from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime


class TestAvailability(FrappeTestCase):
    """Integration tests for check_availability API (Story 2.2, FR-06)."""

    def setUp(self):
        # Bike Model with Safety Margin
        self.bike_model = frappe.get_doc(
            {
                "doctype": "Bike Model",
                "model_name": "Avail Test Model",
                "brand": "AvailBrand",
                "category": "City",
                "base_rate_hourly": 10.00,
                "base_rate_daily": 40.00,
                "safety_margin": 2,
            }
        ).insert()

        # Hub
        self.hub = frappe.get_doc(
            {
                "doctype": "Hub",
                "hub_name": "Avail Test Hub",
                "location": "Avail Location",
                "operating_hours_start": "06:00:00",
                "operating_hours_end": "22:00:00",
            }
        ).insert()

        # Customer
        self.customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": "Avail Customer",
                "email": "avail@example.com",
                "phone": "+0000000000",
            }
        ).insert()

        # Bike Serials: 5 Available + 1 Maintenance + 1 Rented + 1 In Transit + 1 Scrapped
        self.serials = {}
        for i, status in enumerate(
            [
                "Available",
                "Available",
                "Available",
                "Available",
                "Available",
                "Maintenance",
                "Rented",
                "In Transit",
                "Scrapped",
            ]
        ):
            reg = f"AVAIL-SER-{i:03d}"
            serial = frappe.get_doc(
                {
                    "doctype": "Bike Serial",
                    "registration_no": reg,
                    "chassis_no": f"CH-{reg}",
                    "bike_model": self.bike_model.name,
                    "hub": self.hub.name,
                    "status": status,
                }
            ).insert()
            self.serials[status] = self.serials.get(status, []) + [serial]

    def tearDown(self):
        for name in frappe.get_all("Rental Booking", pluck="name"):
            frappe.delete_doc("Rental Booking", name, force=True)
        for name in frappe.get_all("Bike Serial", pluck="name"):
            frappe.delete_doc("Bike Serial", name, force=True)
        for name in frappe.get_all("Customer", pluck="name"):
            frappe.delete_doc("Customer", name, force=True)
        frappe.delete_doc("Hub", self.hub.name, force=True)
        frappe.delete_doc("Bike Model", self.bike_model.name, force=True)

    def _create_booking(self, status, start_delta_days, end_delta_days):
        """Helper to create a Rental Booking with relative date offsets."""
        now = now_datetime()
        return frappe.get_doc(
            {
                "doctype": "Rental Booking",
                "bike_model": self.bike_model.name,
                "customer": self.customer.name,
                "pickup_hub": self.hub.name,
                "return_hub": self.hub.name,
                "pickup_datetime": add_to_date(now, days=start_delta_days),
                "return_datetime": add_to_date(now, days=end_delta_days),
                "status": status,
            }
        ).insert()

    # --- AC #1: Basic availability ---

    def test_returns_correct_total_capacity(self):
        """AC #1 + FR-28: Total capacity excludes Scrapped, In Transit, and Maintenance."""
        from bike_rental.api.availability import check_availability

        now = now_datetime()
        result = check_availability(
            self.hub.name,
            self.bike_model.name,
            add_to_date(now, days=10),
            add_to_date(now, days=12),
        )

        # 9 serials: 5 Available + 1 Maint + 1 Rented + 1 In Transit + 1 Scrapped
        # Excluded: Scrapped + In Transit + Maintenance = 6 remaining
        self.assertEqual(result["total"], 6)

    def test_occupied_counts_confirmed_and_active(self):
        """AC #1: Occupied includes Confirmed and Active bookings in range."""
        from bike_rental.api.availability import check_availability

        now = now_datetime()
        # Create a Confirmed booking in the range
        self._create_booking("Confirmed", 10, 12)
        # Create an Active booking in the range
        self._create_booking("Active", 11, 13)

        result = check_availability(
            self.hub.name,
            self.bike_model.name,
            add_to_date(now, days=10),
            add_to_date(now, days=14),
        )

        self.assertEqual(result["occupied"], 2)

    def test_draft_bookings_not_occupied(self):
        """AC #1: Draft bookings do not count as occupied."""
        from bike_rental.api.availability import check_availability

        now = now_datetime()
        self._create_booking("Draft", 10, 12)

        result = check_availability(
            self.hub.name,
            self.bike_model.name,
            add_to_date(now, days=10),
            add_to_date(now, days=14),
        )

        self.assertEqual(result["occupied"], 0)

    def test_non_overlapping_bookings_excluded(self):
        """AC #1: Bookings outside the date range are not counted."""
        from bike_rental.api.availability import check_availability

        now = now_datetime()
        # Booking far in the future
        self._create_booking("Confirmed", 100, 105)

        result = check_availability(
            self.hub.name,
            self.bike_model.name,
            add_to_date(now, days=10),
            add_to_date(now, days=14),
        )

        self.assertEqual(result["occupied"], 0)

    # --- AC #3: Safety Margin ---

    def test_safety_margin_subtracted(self):
        """AC #3: Safety Margin (2) is subtracted from available count."""
        from bike_rental.api.availability import check_availability

        now = now_datetime()
        result = check_availability(
            self.hub.name,
            self.bike_model.name,
            add_to_date(now, days=10),
            add_to_date(now, days=12),
        )

        # total=6, occupied=0, safety_margin=2, available=4
        self.assertEqual(result["available"], 4)
        self.assertEqual(result["safety_margin"], 2)

    # --- AC #4: Zero available ---

    def test_zero_available_when_all_occupied(self):
        """AC #4: Returns available=0 when all capacity is consumed."""
        from bike_rental.api.availability import check_availability

        now = now_datetime()
        # Create 6 Confirmed bookings to consume total capacity
        for _ in range(6):
            self._create_booking("Confirmed", 10, 12)

        result = check_availability(
            self.hub.name,
            self.bike_model.name,
            add_to_date(now, days=10),
            add_to_date(now, days=14),
        )

        # total=6, occupied=6, safety_margin=2, available=max(0, -2)=0
        self.assertEqual(result["available"], 0)

    # --- AC #5: Input validation ---

    def test_invalid_hub_raises_validation_error(self):
        """AC #5: Non-existent hub raises ValidationError."""
        from bike_rental.api.availability import check_availability

        now = now_datetime()
        with self.assertRaises(frappe.ValidationError) as cm:
            check_availability(
                "NonExistent Hub",
                self.bike_model.name,
                add_to_date(now, days=10),
                add_to_date(now, days=12),
            )
        self.assertIn("does not exist", str(cm.exception))

    def test_invalid_model_raises_validation_error(self):
        """AC #5: Non-existent model raises ValidationError."""
        from bike_rental.api.availability import check_availability

        now = now_datetime()
        with self.assertRaises(frappe.ValidationError) as cm:
            check_availability(
                self.hub.name,
                "NonExistent Model",
                add_to_date(now, days=10),
                add_to_date(now, days=12),
            )
        self.assertIn("does not exist", str(cm.exception))

    def test_inverted_dates_raises_validation_error(self):
        """AC #5: start >= end raises ValidationError."""
        from bike_rental.api.availability import check_availability

        now = now_datetime()
        with self.assertRaises(frappe.ValidationError) as cm:
            check_availability(
                self.hub.name,
                self.bike_model.name,
                add_to_date(now, days=12),
                add_to_date(now, days=10),
            )
        self.assertIn("must be before", str(cm.exception))

    # --- AC #2: Excluded statuses ---

    def test_total_capacity_excludes_scrapped_in_transit_and_maintenance(self):
        """AC #2 + FR-28: Total capacity excludes Scrapped, In Transit, and Maintenance."""
        from bike_rental.api.availability import check_availability

        now = now_datetime()
        result = check_availability(
            self.hub.name,
            self.bike_model.name,
            add_to_date(now, days=10),
            add_to_date(now, days=12),
        )

        # 9 serials total: 5 Available + 1 Maintenance + 1 Rented + 1 In Transit + 1 Scrapped
        # Excluded from total: Scrapped + In Transit + Maintenance → 6 remaining (Avail + Rented)
        self.assertEqual(result["total"], 6)

    def test_return_format(self):
        """AC #1: Returns dict with expected keys."""
        from bike_rental.api.availability import check_availability

        now = now_datetime()
        result = check_availability(
            self.hub.name,
            self.bike_model.name,
            add_to_date(now, days=10),
            add_to_date(now, days=12),
        )

        self.assertIn("total", result)
        self.assertIn("occupied", result)
        self.assertIn("available", result)
        self.assertIn("safety_margin", result)
        self.assertIsInstance(result["total"], int)
        self.assertIsInstance(result["occupied"], int)
        self.assertIsInstance(result["available"], int)
        self.assertIsInstance(result["safety_margin"], int)
