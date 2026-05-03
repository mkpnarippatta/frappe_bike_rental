import frappe
from datetime import timedelta
from frappe.utils import get_datetime


def get_effective_rate(bike_model, pickup_datetime, return_datetime):
    """Determine effective hourly/daily rates considering rate overrides.

    Precedence: peak season (date range without day_of_week) >
                weekend (date range with day_of_week) >
                base rate.

    NOTE: When an override matches, its rates are applied to the entire
    booking duration, not just the overlapping portion. This is intentional
    for simplicity — a booking that falls within a peak season period is
    billed at peak rates for its full duration.

    Args:
        bike_model: Bike Model document (with rate_overrides child table).
        pickup_datetime: Booking pickup datetime.
        return_datetime: Booking return datetime.

    Returns:
        tuple of (effective_hourly, effective_daily)
    """
    overrides = bike_model.get("rate_overrides") or []
    if not overrides:
        return bike_model.base_rate_hourly, bike_model.base_rate_daily

    pickup_date = get_datetime(pickup_datetime).date()
    return_date = get_datetime(return_datetime).date()

    peak_overrides = []  # date range without day_of_week
    dow_overrides = []   # date range with day_of_week

    for o in overrides:
        if o.get("day_of_week"):
            dow_overrides.append(o)
        else:
            peak_overrides.append(o)

    effective_hourly = bike_model.base_rate_hourly
    effective_daily = bike_model.base_rate_daily
    peak_applied = False

    # Peak season overrides (highest precedence)
    for o in peak_overrides:
        if pickup_date <= o.end_date and return_date >= o.start_date:
            effective_hourly = o.override_rate_hourly or effective_hourly
            effective_daily = o.override_rate_daily or effective_daily
            peak_applied = True
            break

    # Day-of-week overrides (only if no peak override matched)
    if not peak_applied:
        for o in dow_overrides:
            if pickup_date <= o.end_date and return_date >= o.start_date:
                days_of_week = [
                    "Monday", "Tuesday", "Wednesday",
                    "Thursday", "Friday", "Saturday", "Sunday",
                ]
                target = days_of_week.index(o.day_of_week)
                current = max(pickup_date, o.start_date)
                overlap_end = min(return_date, o.end_date)
                while current <= overlap_end:
                    if current.weekday() == target:
                        effective_hourly = o.override_rate_hourly or effective_hourly
                        effective_daily = o.override_rate_daily or effective_daily
                        break
                    current += timedelta(days=1)
                if effective_hourly != bike_model.base_rate_hourly:
                    break

    return effective_hourly, effective_daily


def compute_base_rental(effective_hourly, effective_daily, pickup_datetime, return_datetime):
    """Compute base rental amount from effective rates and booking duration.

    Args:
        effective_hourly: Effective hourly rate (after overrides).
        effective_daily: Effective daily rate (after overrides).
        pickup_datetime: Booking pickup datetime.
        return_datetime: Booking return datetime.

    Returns:
        float: Computed base rental total.
    """
    pickup = get_datetime(pickup_datetime)
    return_dt = get_datetime(return_datetime)
    total_hours = (return_dt - pickup).total_seconds() / 3600
    full_days = int(total_hours // 24)
    remaining_hours = total_hours % 24
    return round((full_days * effective_daily) + (remaining_hours * effective_hourly), 2)


def _rate_changed(hourly, daily, bike_model):
    """Check if effective rates differ from base rates."""
    return hourly != bike_model.base_rate_hourly or daily != bike_model.base_rate_daily


def calculate_charges(booking, end_km, end_datetime, damage_amount=0):
    """Calculate check-in charges for a Rental Booking.

    Computes base rental (with dynamic rate overrides), excess KM charges,
    late return fees, and totals. Returns a dict with line items and amounts.

    Args:
        booking: Rental Booking document (loaded from DB).
        end_km: Odometer reading at return.
        end_datetime: Actual return datetime.
        damage_amount: Staff-entered damage repair cost.

    Returns:
        dict with line_items (list), individual amounts, and total.
    """
    bike_model = frappe.get_doc("Bike Model", booking.bike_model)
    serial = frappe.get_doc("Bike Serial", booking.bike_serial)

    # Compute base rental with rate overrides
    effective_hourly, effective_daily = get_effective_rate(
        bike_model, booking.pickup_datetime, booking.return_datetime
    )

    if _rate_changed(effective_hourly, effective_daily, bike_model):
        # Override applies — recalculate from effective rates
        base_rental = compute_base_rental(
            effective_hourly, effective_daily,
            booking.pickup_datetime, booking.return_datetime,
        )
    else:
        # No override — use stored total_amount
        base_rental = booking.total_amount or 0

    # KM driven = ending KM - starting KM (set during check-out)
    start_km = serial.current_km or 0
    km_driven = max(0, end_km - start_km)

    included_km = bike_model.included_km or 0
    per_km_rate = bike_model.per_km_rate or 0
    hourly_rate = effective_hourly  # Use effective hourly for late fee

    # Excess KM charges
    excess_km = max(0, km_driven - included_km)
    excess_km_charges = round(excess_km * per_km_rate, 2)

    # Late return fee: 50% of hourly rate per hour late
    scheduled_end = get_datetime(booking.return_datetime)
    actual_end = get_datetime(end_datetime)
    late_fee = 0
    if actual_end > scheduled_end:
        hours_late = (actual_end - scheduled_end).total_seconds() / 3600
        late_fee = round(hours_late * hourly_rate * 0.5, 2)

    damage = damage_amount or 0
    total = round(base_rental + excess_km_charges + late_fee + damage, 2)

    line_items = []
    if base_rental:
        line_items.append({"description": "Base Rental", "amount": base_rental})
    if excess_km_charges:
        line_items.append(
            {"description": "Excess KM Charges", "amount": excess_km_charges}
        )
    if late_fee:
        line_items.append({"description": "Late Return Fee", "amount": late_fee})
    if damage:
        line_items.append({"description": "Damage Charges", "amount": damage})

    return {
        "line_items": line_items,
        "base_rental": base_rental,
        "excess_km_charges": excess_km_charges,
        "late_return_fee": late_fee,
        "damage_charges": damage,
        "total": total,
    }
