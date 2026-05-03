from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime


class TestRentalBooking(FrappeTestCase):
    """Test suite for Rental Booking DocType & State Machine (Story 2.1)."""

    def setUp(self):
        # Create dependent DocTypes
        self.bike_model = frappe.get_doc(
            {
                "doctype": "Bike Model",
                "model_name": "RB Test Model",
                "brand": "TestBrand",
                "category": "City",
                "base_rate_hourly": 10.00,
                "base_rate_daily": 40.00,
            }
        ).insert()

        self.hub = frappe.get_doc(
            {
                "doctype": "Hub",
                "hub_name": "RB Test Hub",
                "location": "Test Location",
                "operating_hours_start": "06:00:00",
                "operating_hours_end": "22:00:00",
            }
        ).insert()

        self.customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": "RB Test Customer",
                "email": "rb-test@example.com",
                "phone": "+1111111111",
            }
        ).insert()

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
        for name in frappe.get_all("Rental Booking", pluck="name"):
            frappe.delete_doc("Rental Booking", name, force=True)
        for name in frappe.get_all("Customer", pluck="name"):
            if name != self.customer.name:
                frappe.delete_doc("Customer", name, force=True)
        frappe.delete_doc("Customer", self.customer.name, force=True)
        frappe.delete_doc("Hub", self.hub.name, force=True)
        frappe.delete_doc("Bike Model", self.bike_model.name, force=True)

    # --- AC #1: DocType Creation ---

    def test_create_with_all_required_fields(self):
        """AC #1: Verify Rental Booking stores all required fields."""
        self.assertEqual(self.booking.bike_model, self.bike_model.name)
        self.assertEqual(self.booking.customer, self.customer.name)
        self.assertEqual(self.booking.pickup_hub, self.hub.name)
        self.assertEqual(self.booking.return_hub, self.hub.name)
        self.assertIsNotNone(self.booking.pickup_datetime)
        self.assertIsNotNone(self.booking.return_datetime)

    def test_default_status_is_draft(self):
        """AC #1: New Rental Booking defaults to Draft status."""
        self.assertEqual(self.booking.status, "Draft")

    def test_naming_series_format(self):
        """AC #6: Naming series follows BIKE-RENT-YYYY-#####."""
        import re

        pattern = r"^BIKE-RENT-\d{4}-\d{5}$"
        self.assertRegex(self.booking.name, pattern)

    # --- AC #2: Draft Transitions ---

    def test_draft_to_confirmed_allowed(self):
        """AC #2: Draft → Confirmed is allowed."""
        self.booking.status = "Confirmed"
        try:
            self.booking.save()
        except frappe.ValidationError:
            self.fail("Draft → Confirmed raised ValidationError unexpectedly")

    def test_draft_to_cancelled_allowed(self):
        """AC #2: Draft → Cancelled is allowed."""
        self.booking.status = "Cancelled"
        try:
            self.booking.save()
        except frappe.ValidationError:
            self.fail("Draft → Cancelled raised ValidationError unexpectedly")

    # --- AC #3: Confirmed Transitions ---

    def test_confirmed_to_active_allowed(self):
        """AC #3: Confirmed → Active is allowed."""
        self.booking.status = "Confirmed"
        self.booking.save()

        self.booking.status = "Active"
        try:
            self.booking.save()
        except frappe.ValidationError:
            self.fail("Confirmed → Active raised ValidationError unexpectedly")

    def test_confirmed_to_expired_allowed(self):
        """AC #3: Confirmed → Expired is allowed."""
        self.booking.status = "Confirmed"
        self.booking.save()

        self.booking.status = "Expired"
        try:
            self.booking.save()
        except frappe.ValidationError:
            self.fail("Confirmed → Expired raised ValidationError unexpectedly")

    def test_confirmed_to_cancelled_allowed(self):
        """AC #3: Confirmed → Cancelled is allowed."""
        self.booking.status = "Confirmed"
        self.booking.save()

        self.booking.status = "Cancelled"
        try:
            self.booking.save()
        except frappe.ValidationError:
            self.fail("Confirmed → Cancelled raised ValidationError unexpectedly")

    # --- AC #4: Active -> Completed ---

    def test_active_to_completed_allowed(self):
        """AC #4: Active → Completed is the only valid transition."""
        self.booking.status = "Confirmed"
        self.booking.save()
        self.booking.status = "Active"
        self.booking.save()

        self.booking.status = "Completed"
        try:
            self.booking.save()
        except frappe.ValidationError:
            self.fail("Active → Completed raised ValidationError unexpectedly")

    # --- AC #5: Terminal States Block All Transitions ---

    def test_completed_is_terminal(self):
        """AC #5: Completed → any is blocked."""
        self.booking.status = "Confirmed"
        self.booking.save()
        self.booking.status = "Active"
        self.booking.save()
        self.booking.status = "Completed"
        self.booking.save()

        blocked_statuses = ["Draft", "Confirmed", "Active", "Cancelled", "Expired"]
        for target in blocked_statuses:
            self.booking.status = target
            with self.assertRaises(frappe.ValidationError):
                self.booking.save()

    def test_cancelled_is_terminal(self):
        """AC #5: Cancelled → any is blocked."""
        self.booking.status = "Cancelled"
        self.booking.save()

        blocked_statuses = ["Draft", "Confirmed", "Active", "Completed", "Expired"]
        for target in blocked_statuses:
            self.booking.status = target
            with self.assertRaises(frappe.ValidationError):
                self.booking.save()

    def test_expired_is_terminal(self):
        """AC #5: Expired → any is blocked."""
        self.booking.status = "Confirmed"
        self.booking.save()
        self.booking.status = "Expired"
        self.booking.save()

        blocked_statuses = ["Draft", "Confirmed", "Active", "Completed", "Cancelled"]
        for target in blocked_statuses:
            self.booking.status = target
            with self.assertRaises(frappe.ValidationError):
                self.booking.save()

    # --- AC #7: Minimum Duration ---

    def test_minimum_duration_exactly_24h_passes(self):
        """AC #7: Exactly 24-hour rental duration passes validation."""
        booking = frappe.get_doc(
            {
                "doctype": "Rental Booking",
                "bike_model": self.bike_model.name,
                "customer": self.customer.name,
                "pickup_hub": self.hub.name,
                "return_hub": self.hub.name,
                "pickup_datetime": add_to_date(now_datetime(), days=1),
                "return_datetime": add_to_date(
                    now_datetime(), days=2
                ),  # exactly 24h
            }
        )
        try:
            booking.insert()
        except frappe.ValidationError:
            self.fail("24-hour rental raised ValidationError unexpectedly")
        frappe.delete_doc("Rental Booking", booking.name, force=True)

    def test_minimum_duration_23h_fails(self):
        """AC #7: 23-hour rental duration is blocked."""
        with self.assertRaises(frappe.ValidationError) as cm:
            frappe.get_doc(
                {
                    "doctype": "Rental Booking",
                    "bike_model": self.bike_model.name,
                    "customer": self.customer.name,
                    "pickup_hub": self.hub.name,
                    "return_hub": self.hub.name,
                    "pickup_datetime": add_to_date(now_datetime(), days=1, hours=10),
                    "return_datetime": add_to_date(
                        now_datetime(), days=2, hours=9
                    ),  # 23h
                }
            ).insert()
        self.assertIn("Minimum rental duration is 24 hours", str(cm.exception))

    def test_minimum_duration_zero_hours_fails(self):
        """AC #7: Same pickup/return time (0h) is blocked."""
        now = now_datetime()
        with self.assertRaises(frappe.ValidationError) as cm:
            frappe.get_doc(
                {
                    "doctype": "Rental Booking",
                    "bike_model": self.bike_model.name,
                    "customer": self.customer.name,
                    "pickup_hub": self.hub.name,
                    "return_hub": self.hub.name,
                    "pickup_datetime": now,
                    "return_datetime": now,  # 0h duration
                }
            ).insert()
        self.assertIn("Minimum rental duration is 24 hours", str(cm.exception))

    # --- Invalid Transitions ---

    def test_draft_to_active_blocked(self):
        """AC #2: Draft → Active is blocked."""
        self.booking.status = "Active"
        with self.assertRaises(frappe.ValidationError):
            self.booking.save()

    def test_draft_to_completed_blocked(self):
        """AC #2: Draft → Completed is blocked."""
        self.booking.status = "Completed"
        with self.assertRaises(frappe.ValidationError):
            self.booking.save()

    def test_draft_to_expired_blocked(self):
        """AC #2: Draft → Expired is blocked."""
        self.booking.status = "Expired"
        with self.assertRaises(frappe.ValidationError):
            self.booking.save()

    def test_list_view_fields(self):
        """AC #1: List view returns expected columns."""
        bookings = frappe.get_list(
            "Rental Booking",
            fields=["bike_model", "customer", "status", "pickup_datetime"],
            limit=10,
        )
        self.assertGreaterEqual(len(bookings), 1)

    # --- AC #2-4: before_submit availability re-verification ---

    def _create_serial(self, reg, status="Available"):
        """Helper to create a Bike Serial at the test hub."""
        return frappe.get_doc(
            {
                "doctype": "Bike Serial",
                "registration_no": reg,
                "chassis_no": f"CH-{reg}",
                "bike_model": self.bike_model.name,
                "hub": self.hub.name,
                "status": status,
            }
        ).insert()

    def test_before_submit_available_passes(self):
        """AC #2: Sufficient availability allows submit to Confirmed."""
        self._create_serial("SUB-AVAIL-001")
        self._create_serial("SUB-AVAIL-002")

        self.booking.submit()
        self.assertEqual(self.booking.status, "Confirmed")

    def test_before_submit_blocks_when_no_availability(self):
        """AC #3: Zero available blocks submit with ValidationError."""
        # No Bike Serials exist → total capacity = 0 → available = 0
        with self.assertRaises(frappe.ValidationError) as cm:
            self.booking.submit()
        self.assertIn("no longer available", str(cm.exception))
        # Booking remains Draft
        self.assertEqual(self.booking.status, "Draft")

    def test_before_submit_save_still_works(self):
        """AC #1: before_submit only runs on Submit, not Save."""
        self.booking.customer_name = "Updated Name"
        try:
            self.booking.save()
        except frappe.ValidationError:
            self.fail("Save raised ValidationError unexpectedly")

    # --- AC #2-4: Payment Validation ---

    def test_submit_without_payment_entry_blocked(self):
        """AC #2: Submit without payment_entry throws ValidationError."""
        self._create_serial("PAY-BLOCK-001")
        self._create_serial("PAY-BLOCK-002")

        with self.assertRaises(frappe.ValidationError) as cm:
            self.booking.submit()
        self.assertIn("Payment Entry", str(cm.exception))
        self.assertEqual(self.booking.status, "Draft")

    def test_submit_with_payment_entry_passes(self):
        """AC #3: Submit with payment_entry passes and status is Confirmed."""
        self._create_serial("PAY-PASS-001")
        self._create_serial("PAY-PASS-002")

        self.booking.db_set("payment_entry", "PAYMENT-TEST-001")
        self.booking.reload()
        self.booking.submit()
        self.assertEqual(self.booking.status, "Confirmed")
