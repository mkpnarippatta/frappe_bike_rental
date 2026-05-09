from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, getdate

VALID_TRANSITIONS = {
    "Draft": ["Confirmed", "Cancelled"],
    "Confirmed": ["Active", "Expired", "Cancelled"],
    "Active": ["Completed", "Cancelled"],
    "Completed": [],
    "Cancelled": [],
    "Expired": [],
}


class RentalBooking(Document):
    def before_save(self):
        self._validate_transition()
        self._validate_minimum_duration()

    def before_submit(self):
        self._re_verify_availability()
        self._validate_payment_entry()
        if self.status != "Confirmed":
            self.status = "Confirmed"

    def on_update(self):
        """Trigger notifications on status changes."""
        old_doc = self.get_doc_before_save()
        if not old_doc:
            return
        if old_doc.status != "Confirmed" and self.status == "Confirmed":
            self._notify_booking_confirmed()
        elif old_doc.status == "Confirmed" and self.status == "Cancelled":
            self._notify_cancellation()
        elif old_doc.status == "Active" and self.status == "Completed":
            self._notify_completed()

    def _notify_booking_confirmed(self):
        """Send booking confirmation notifications."""
        try:
            from bike_rental.notification.event_handlers import on_booking_confirmed
            on_booking_confirmed(self)
        except Exception as e:
            frappe.log_error(
                title="Booking Confirmation Notification Failed",
                message="Booking {0}: {1}".format(self.name, str(e)),
            )

    def _notify_cancellation(self):
        """Send cancellation notification."""
        try:
            from bike_rental.notification.event_handlers import on_cancellation
            on_cancellation(self)
        except Exception as e:
            frappe.log_error(
                title="Cancellation Notification Failed",
                message="Booking {0}: {1}".format(self.name, str(e)),
            )

    def _notify_completed(self):
        """Send completion/deposit release notification."""
        try:
            from bike_rental.notification.event_handlers import on_deposit_released
            deposit_amount = 0
            if self.payment_entry and frappe.db.exists("DocType", "Payment Entry"):
                deposit_amount = frappe.db.get_value("Payment Entry", self.payment_entry, "paid_amount") or 0
            on_deposit_released(self, deposit_amount)
        except Exception as e:
            frappe.log_error(
                title="Completion Notification Failed",
                message="Booking {0}: {1}".format(self.name, str(e)),
            )

    def _validate_kyc_status(self):
        """Validate customer KYC status before confirming booking (FR-24, AR-16)."""
        kyc_status = frappe.db.get_value("Customer", self.customer, "kyc_status") or "Unverified"

        if kyc_status == "Unverified":
            frappe.throw(
                _("Please complete KYC verification before confirming your booking. "
                  "Upload your ID documents (ID Proof and Driving License) from your profile."),
                frappe.ValidationError,
            )
        elif kyc_status == "Rejected":
            last_rejection = frappe.get_all(
                "KYC Document",
                filters={"customer": self.customer, "status": "Rejected"},
                fields=["rejection_reason"],
                order_by="review_date desc",
                limit=1,
            )
            reason = ""
            if last_rejection and last_rejection[0].rejection_reason:
                reason = _(" Reason: {0}").format(last_rejection[0].rejection_reason)
            frappe.throw(
                _("Your KYC verification has been rejected.{0} "
                  "Please re-upload your documents from your profile.").format(reason),
                frappe.ValidationError,
            )
        elif kyc_status == "Pending Review":
            frappe.msgprint(
                _("Your KYC documents are under review. "
                  "Documents are typically reviewed within 24 hours. "
                  "You will receive a notification once verified."),
                alert=True,
            )

    def _re_verify_availability(self):
        """Re-verify availability with row-level locking (FR-09, FR-10)."""
        lock_query = """
            SELECT name FROM `tabRental Booking`
            WHERE bike_model = %s
              AND pickup_hub = %s
              AND status IN ('Confirmed', 'Active')
              AND pickup_datetime < %s
              AND return_datetime > %s
            FOR UPDATE
        """
        frappe.db.sql(
            lock_query,
            (
                self.bike_model,
                self.pickup_hub,
                self.return_datetime,
                self.pickup_datetime,
            ),
        )

        occupied = frappe.db.count(
            "Rental Booking",
            filters={
                "bike_model": self.bike_model,
                "pickup_hub": self.pickup_hub,
                "status": ["in", ["Confirmed", "Active"]],
                "pickup_datetime": ["<", self.return_datetime],
                "return_datetime": [">", self.pickup_datetime],
            },
        )

        total = frappe.db.count(
            "Bike Serial",
            filters={
                "bike_model": self.bike_model,
                "hub": self.pickup_hub,
                "status": ["not in", ["Scrapped", "In Transit", "Maintenance"]],
            },
        )

        safety_margin = (
            frappe.db.get_value("Bike Model", self.bike_model, "safety_margin") or 0
        )
        available = total - occupied - safety_margin

        if available < 1:
            frappe.throw(
                _("Sorry, this model is no longer available for these dates"),
                frappe.ValidationError,
            )

    def _validate_payment_entry(self):
        if not frappe.db.exists("DocType", "Payment Entry"):
            return
        if self.payment_method == "Online" and not self.payment_entry:
            frappe.throw(
                _("A Payment Entry must be linked before confirming the booking"),
                frappe.ValidationError,
            )

    def _validate_transition(self):
        old_doc = self.get_doc_before_save()
        if not old_doc:
            return
        if old_doc.status == self.status:
            return
        allowed = VALID_TRANSITIONS.get(old_doc.status, [])
        if self.status not in allowed:
            frappe.throw(
                _("Cannot change status from {0} to {1}").format(
                    old_doc.status, self.status
                ),
                frappe.ValidationError,
            )

    def _validate_minimum_duration(self):
        if not self.pickup_datetime or not self.return_datetime:
            return
        pickup = get_datetime(self.pickup_datetime)
        return_dt = get_datetime(self.return_datetime)
        diff = return_dt - pickup
        if diff.total_seconds() < 86400:
            frappe.throw(
                _("Minimum rental duration is 24 hours"),
                frappe.ValidationError,
            )
