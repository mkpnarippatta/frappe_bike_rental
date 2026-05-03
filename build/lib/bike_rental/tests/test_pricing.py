from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from bike_rental.pricing.calculate import calculate_charges, get_effective_rate, compute_base_rental


class TestPricing(FrappeTestCase):
    """Unit tests for pricing charge calculation (Story 2.6)."""

    def setUp(self):
        self.bike_model = frappe.get_doc(
            {
                "doctype": "Bike Model",
                "model_name": "PR-Test Model",
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
                "hub_name": "PR-Test Hub",
                "location": "Test Location",
                "operating_hours_start": "06:00:00",
                "operating_hours_end": "22:00:00",
            }
        ).insert()

        self.customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": "PR-Test Customer",
                "email": "pr-test@example.com",
                "phone": "+1444444444",
            }
        ).insert()

        # Serial with starting KM (simulates check-out)
        self.serial = frappe.get_doc(
            {
                "doctype": "Bike Serial",
                "registration_no": "PR-SER-001",
                "chassis_no": "CH-PR-SER-001",
                "bike_model": self.bike_model.name,
                "hub": self.hub.name,
                "status": "Rented",
                "current_km": 1000,
            }
        ).insert()

        # Active booking (2-day rental at $40/day = $80)
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
                "status": "Active",
            }
        ).insert()

    def tearDown(self):
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

    def test_calculate_charges_excess_km(self):
        """Excess KM beyond included KM charged at per_km_rate."""
        charges = calculate_charges(self.booking, end_km=1200, end_datetime=now_datetime())
        # km_driven=200, included=100, excess=100 @ $2 = $200
        self.assertEqual(charges["excess_km_charges"], 200.00)
        self.assertAlmostEqual(charges["total"], 280.00)  # $80 base + $200 excess

    def test_calculate_charges_no_excess(self):
        """Within KM allowance = no excess charge."""
        charges = calculate_charges(self.booking, end_km=1050, end_datetime=now_datetime())
        # km_driven=50, included=100, no excess
        self.assertEqual(charges["excess_km_charges"], 0)
        self.assertEqual(charges["total"], 80.00)  # base only

    def test_calculate_charges_late_return(self):
        """Late return charged at 50% hourly rate per hour late."""
        late_end = add_to_date(self.booking.return_datetime, hours=3)
        charges = calculate_charges(self.booking, end_km=1000, end_datetime=late_end)
        # 3h late @ $10/h * 50% = $15
        self.assertEqual(charges["late_return_fee"], 15.00)
        self.assertAlmostEqual(charges["total"], 95.00)  # $80 base + $15 late

    def test_calculate_charges_with_damage(self):
        """Damage amount included in total."""
        charges = calculate_charges(self.booking, end_km=1000, end_datetime=now_datetime(), damage_amount=50.00)
        self.assertEqual(charges["damage_charges"], 50.00)
        self.assertAlmostEqual(charges["total"], 130.00)

    def test_calculate_charges_line_items(self):
        """Line items include only non-zero charges."""
        charges = calculate_charges(self.booking, end_km=1000, end_datetime=now_datetime())
        self.assertEqual(len(charges["line_items"]), 1)  # base only
        self.assertEqual(charges["line_items"][0]["description"], "Base Rental")

    def test_calculate_charges_zero_km_driven(self):
        """Exactly zero KM driven = no excess charge."""
        charges = calculate_charges(self.booking, end_km=1000, end_datetime=now_datetime())
        # start_km=1000, end_km=1000, km_driven=0
        self.assertEqual(charges["excess_km_charges"], 0)
        self.assertEqual(charges["total"], 80.00)

    def test_calculate_charges_multi_day_late_return(self):
        """Very late return (days) accumulates large fee."""
        very_late = add_to_date(self.booking.return_datetime, days=2)
        charges = calculate_charges(self.booking, end_km=1000, end_datetime=very_late)
        # 48h late @ $10/h * 50% = $240
        self.assertEqual(charges["late_return_fee"], 240.00)
        self.assertAlmostEqual(charges["total"], 320.00)  # $80 base + $240 late

    def test_calculate_charges_mixed_excess_and_late_and_damage(self):
        """All charge types combined."""
        late_end = add_to_date(self.booking.return_datetime, hours=2)
        charges = calculate_charges(self.booking, end_km=1300, end_datetime=late_end, damage_amount=30.00)
        # km_driven=300, included=100, excess=200 @ $2 = $400
        # 2h late @ $10/h * 50% = $10
        # damage = $30
        # total = $80 + $400 + $10 + $30 = $520
        self.assertEqual(charges["excess_km_charges"], 400.00)
        self.assertEqual(charges["late_return_fee"], 10.00)
        self.assertEqual(charges["damage_charges"], 30.00)
        self.assertAlmostEqual(charges["total"], 520.00)
        self.assertEqual(len(charges["line_items"]), 4)  # all line items present

    # --- Dynamic Pricing (Story 2.7) ---

    def test_get_effective_rate_no_overrides(self):
        """No overrides configured = base rates returned."""
        pickup = add_to_date(now_datetime(), days=1)
        return_dt = add_to_date(now_datetime(), days=3)
        hourly, daily = get_effective_rate(self.bike_model, pickup, return_dt)
        self.assertEqual(hourly, 10.00)
        self.assertEqual(daily, 40.00)

    def test_get_effective_rate_peak_season(self):
        """Peak season override applies when booking overlaps."""
        from datetime import date, timedelta
        today = date.today()
        # Add peak override
        self.bike_model.append("rate_overrides", {
            "start_date": today + timedelta(days=1),
            "end_date": today + timedelta(days=5),
            "override_rate_hourly": 15.00,
            "override_rate_daily": 60.00,
            "label": "Peak Season",
        })
        self.bike_model.save()

        pickup = add_to_date(now_datetime(), days=1)
        return_dt = add_to_date(now_datetime(), days=3)
        hourly, daily = get_effective_rate(self.bike_model, pickup, return_dt)
        self.assertEqual(hourly, 15.00)
        self.assertEqual(daily, 60.00)

    def test_get_effective_rate_weekend(self):
        """Weekend override via day_of_week filter."""
        from datetime import date, timedelta
        today = date.today()
        # Find next Saturday
        days_until_sat = (5 - today.weekday()) % 7
        if days_until_sat == 0:
            days_until_sat = 7
        saturday = today + timedelta(days=days_until_sat)

        self.bike_model.append("rate_overrides", {
            "start_date": saturday,
            "end_date": saturday + timedelta(days=1),
            "day_of_week": "Saturday",
            "override_rate_hourly": 12.00,
            "override_rate_daily": 50.00,
            "label": "Weekend",
        })
        self.bike_model.save()

        # Booking on Saturday
        pickup = add_to_date(now_datetime(), days=days_until_sat)
        return_dt = add_to_date(pickup, days=1)
        hourly, daily = get_effective_rate(self.bike_model, pickup, return_dt)
        self.assertEqual(hourly, 12.00)
        self.assertEqual(daily, 50.00)

    def test_peak_season_overrides_weekend(self):
        """Peak season (date range) takes precedence over weekend."""
        from datetime import date, timedelta
        today = date.today()
        days_until_sat = (5 - today.weekday()) % 7
        if days_until_sat == 0:
            days_until_sat = 7
        saturday = today + timedelta(days=days_until_sat)

        # Weekend override (lower priority)
        self.bike_model.append("rate_overrides", {
            "start_date": saturday,
            "end_date": saturday + timedelta(days=1),
            "day_of_week": "Saturday",
            "override_rate_hourly": 12.00,
            "override_rate_daily": 50.00,
            "label": "Weekend",
        })
        # Peak season override (higher priority) — same date range
        self.bike_model.append("rate_overrides", {
            "start_date": saturday,
            "end_date": saturday + timedelta(days=1),
            "override_rate_hourly": 18.00,
            "override_rate_daily": 70.00,
            "label": "Peak Season",
        })
        self.bike_model.save()

        pickup = add_to_date(now_datetime(), days=days_until_sat)
        return_dt = add_to_date(pickup, days=1)
        hourly, daily = get_effective_rate(self.bike_model, pickup, return_dt)
        # Peak season rate wins
        self.assertEqual(hourly, 18.00)
        self.assertEqual(daily, 70.00)

    def test_no_override_when_dates_dont_overlap(self):
        """Override outside booking date range has no effect."""
        from datetime import date, timedelta
        today = date.today()
        self.bike_model.append("rate_overrides", {
            "start_date": today + timedelta(days=30),
            "end_date": today + timedelta(days=35),
            "override_rate_hourly": 15.00,
            "override_rate_daily": 60.00,
            "label": "Peak Season",
        })
        self.bike_model.save()

        pickup = add_to_date(now_datetime(), days=1)
        return_dt = add_to_date(now_datetime(), days=3)
        hourly, daily = get_effective_rate(self.bike_model, pickup, return_dt)
        self.assertEqual(hourly, 10.00)  # base rate, no override
        self.assertEqual(daily, 40.00)

    def test_compute_base_rental_override_applied(self):
        """Base rental computed from override rates."""
        base = compute_base_rental(15.00, 60.00, self.booking.pickup_datetime, self.booking.return_datetime)
        # 2-day rental @ $60/day = $120
        self.assertAlmostEqual(base, 120.00)

    def test_peak_override_affects_charges_total(self):
        """Peak override changes total in calculate_charges."""
        from datetime import date, timedelta
        today = date.today()
        self.bike_model.append("rate_overrides", {
            "start_date": today + timedelta(days=1),
            "end_date": today + timedelta(days=5),
            "override_rate_hourly": 15.00,
            "override_rate_daily": 60.00,
            "label": "Peak Season",
        })
        self.bike_model.save()

        charges = calculate_charges(self.booking, end_km=1000, end_datetime=now_datetime())
        # Base rental recalculated: 2 days @ $60 + 0h @ $15 = $120
        self.assertAlmostEqual(charges["base_rental"], 120.00)
        self.assertAlmostEqual(charges["total"], 120.00)  # no excess/late/damage

    def test_discount_override_lower_than_base(self):
        """Override with discount rate (lower than base)."""
        from datetime import date, timedelta
        today = date.today()
        self.bike_model.append("rate_overrides", {
            "start_date": today + timedelta(days=1),
            "end_date": today + timedelta(days=5),
            "override_rate_hourly": 8.00,
            "override_rate_daily": 30.00,
            "label": "Discount",
        })
        self.bike_model.save()

        charges = calculate_charges(self.booking, end_km=1000, end_datetime=now_datetime())
        # 2 days @ $30 = $60
        self.assertAlmostEqual(charges["base_rental"], 60.00)
        self.assertAlmostEqual(charges["total"], 60.00)

    def test_late_fee_with_override_rate(self):
        """Late return fee uses effective hourly rate from override."""
        from datetime import date, timedelta
        today = date.today()
        self.bike_model.append("rate_overrides", {
            "start_date": today + timedelta(days=1),
            "end_date": today + timedelta(days=5),
            "override_rate_hourly": 20.00,
            "override_rate_daily": 80.00,
            "label": "Peak Season",
        })
        self.bike_model.save()

        late_end = add_to_date(self.booking.return_datetime, hours=2)
        charges = calculate_charges(self.booking, end_km=1000, end_datetime=late_end)
        # Late fee: 2h @ $20/h * 50% = $20
        self.assertEqual(charges["late_return_fee"], 20.00)
        # Base: 2 days @ $80 = $160
        self.assertAlmostEqual(charges["base_rental"], 160.00)
        self.assertAlmostEqual(charges["total"], 180.00)

    def test_first_peak_override_wins(self):
        """Two peak overrides — first in table order wins."""
        from datetime import date, timedelta
        today = date.today()
        # First override (lower priority in table, but first)
        self.bike_model.append("rate_overrides", {
            "start_date": today + timedelta(days=1),
            "end_date": today + timedelta(days=5),
            "override_rate_hourly": 12.00,
            "override_rate_daily": 50.00,
            "label": "Low Peak",
        })
        # Second override (same date range)
        self.bike_model.append("rate_overrides", {
            "start_date": today + timedelta(days=1),
            "end_date": today + timedelta(days=5),
            "override_rate_hourly": 18.00,
            "override_rate_daily": 70.00,
            "label": "High Peak",
        })
        self.bike_model.save()

        hourly, daily = get_effective_rate(self.bike_model,
            self.booking.pickup_datetime, self.booking.return_datetime)
        # First override wins ($12/$50)
        self.assertEqual(hourly, 12.00)
        self.assertEqual(daily, 50.00)

    def test_dow_override_covers_multi_day_booking(self):
        """Weekend DOW override: Sat-only with Fri-to-Mon booking."""
        from datetime import date, timedelta
        today = date.today()
        days_until_fri = (4 - today.weekday()) % 7
        if days_until_fri == 0:
            days_until_fri = 7
        friday = today + timedelta(days=days_until_fri)
        saturday = friday + timedelta(days=1)
        monday = saturday + timedelta(days=2)

        self.bike_model.append("rate_overrides", {
            "start_date": saturday,
            "end_date": saturday,
            "day_of_week": "Saturday",
            "override_rate_hourly": 15.00,
            "override_rate_daily": 60.00,
            "label": "Weekend",
        })
        self.bike_model.save()

        # Fri to Mon booking should trigger the Saturday override
        pickup = add_to_date(now_datetime(), days=days_until_fri)
        return_dt = add_to_date(pickup, days=3)
        hourly, daily = get_effective_rate(self.bike_model, pickup, return_dt)
        self.assertEqual(hourly, 15.00)
        self.assertEqual(daily, 60.00)
