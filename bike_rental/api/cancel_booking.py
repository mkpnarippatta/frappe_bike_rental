import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime


def calculate_refund(booking):
    """Determine refund amount based on cancellation policy (FR-16 to FR-19).

    Policy:
    - Cancellation > 48h before pickup: full refund (100% of total_amount)
    - Cancellation 24-48h before pickup: 50% refund
    - Cancellation < 24h before pickup (or after): no refund
    - Active booking (checked out): pro-rata refund minus 50% cancellation fee

    Args:
        booking: Rental Booking document.

    Returns:
        dict with refund_amount, policy_description
    """
    base = booking.total_amount or 0
    now = now_datetime()
    pickup = get_datetime(booking.pickup_datetime)
    hours_to_pickup = (pickup - now).total_seconds() / 3600

    if booking.status == "Active":
        # Pro-rata: refund unused time minus 50% cancellation fee
        return_dt = get_datetime(booking.return_datetime)
        total_hours = (return_dt - pickup).total_seconds() / 3600
        elapsed_hours = max(0, (now - pickup).total_seconds() / 3600)
        if total_hours > 0 and elapsed_hours < total_hours:
            unused_fraction = (total_hours - elapsed_hours) / total_hours
            pro_rata = base * unused_fraction
            refund_amount = max(0, round(pro_rata * 0.5, 2))  # 50% after fee
        else:
            refund_amount = 0
        policy = "Pro-rata refund minus 50% cancellation fee"
    elif hours_to_pickup > 48:
        refund_amount = base
        policy = "Full refund (>48h before pickup)"
    elif hours_to_pickup > 24:
        refund_amount = round(base * 0.5, 2)
        policy = "50% refund (24-48h before pickup)"
    else:
        refund_amount = 0
        policy = "No refund (<24h before pickup or after pickup)"

    return {
        "refund_amount": refund_amount,
        "policy": policy,
    }


@frappe.whitelist()
def cancel_booking(booking_name, reason=None):
    """Cancel a Rental Booking and process refund per policy.

    Applicable from Draft, Confirmed, or Active status.
    For Active bookings, releases the bike serial back to Available.
    """
    booking = frappe.get_doc("Rental Booking", booking_name)

    if booking.status == "Completed":
        frappe.throw(
            _("Cannot cancel a completed booking"),
            frappe.ValidationError,
        )
    if booking.status == "Cancelled":
        frappe.throw(
            _("Booking is already cancelled"),
            frappe.ValidationError,
        )
    if booking.status == "Expired":
        frappe.throw(
            _("Cannot cancel an expired booking"),
            frappe.ValidationError,
        )

    # Calculate refund
    refund_info = calculate_refund(booking)

    # If Active, validate and release the serial
    if booking.status == "Active" and booking.bike_serial:
        serial = frappe.get_doc("Bike Serial", booking.bike_serial)
        if serial.status != "Rented":
            frappe.throw(
                _("Bike Serial is not in Rented status"),
                frappe.ValidationError,
            )
        serial.db_set("status", "Available")

    # Update booking status with optimistic lock
    rows = frappe.db.set_value(
        "Rental Booking",
        booking_name,
        "status",
        "Cancelled",
        update_modified=True,
    )
    if not rows:
        frappe.throw(
            _("Booking could not be cancelled (concurrent update detected)."),
            frappe.ValidationError,
        )

    if reason:
        frappe.db.set_value("Rental Booking", booking_name, "cancellation_reason", reason)
    if refund_info["refund_amount"]:
        frappe.db.set_value(
            "Rental Booking", booking_name, "cancellation_refund_amount", refund_info["refund_amount"]
        )
    frappe.db.set_value("Rental Booking", booking_name, "deposit_released", 1)

    # Send cancellation notification via notification engine
    try:
        from bike_rental.notification.event_handlers import on_cancellation
        booking_doc = frappe.get_doc("Rental Booking", booking_name)
        booking_doc.refund_amount = refund_info["refund_amount"]
        on_cancellation(booking_doc, reason)
    except Exception as e:
        frappe.log_error(
            title="Cancellation Notification Failed",
            message="Booking {0}: {1}".format(booking_name, str(e)),
        )

    # Log notification
    subject = _("Booking {0} cancelled. {1}. Refund: {2}").format(
        booking_name,
        refund_info["policy"],
        refund_info["refund_amount"],
    )
    frappe.get_doc(
        {
            "doctype": "Notification Log",
            "subject": subject,
            "type": "Alert",
            "document_type": "Rental Booking",
            "document_name": booking_name,
        }
    ).insert(ignore_permissions=True)

    return {
        "status": "success",
        "booking_name": booking_name,
        "booking_status": "Cancelled",
        "refund": refund_info,
    }
