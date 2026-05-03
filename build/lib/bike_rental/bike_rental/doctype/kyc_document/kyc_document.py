from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class KYCDocument(Document):
    def before_insert(self):
        self.uploaded_date = now_datetime()

        if not self.status:
            self.status = "Pending Review"

        # Validate the authenticated user owns this customer record
        customer_user = frappe.db.get_value("Customer", self.customer, "email")
        if not customer_user:
            frappe.throw(
                _("Customer {0} has no email address").format(self.customer),
                frappe.ValidationError,
            )

        roles = frappe.get_roles()
        is_staff = "Hub Staff" in roles or "Hub Manager" in roles or "System Manager" in roles
        if not is_staff:
            user_email = frappe.session.user
            if user_email != customer_user and user_email != "Administrator":
                frappe.throw(
                    _("You can only create KYC documents for your own customer profile"),
                    frappe.PermissionError,
                )

    def after_insert(self):
        _update_customer_kyc_status(self.customer)

    def on_update(self):
        old_doc = self.get_doc_before_save()
        if old_doc and old_doc.status != self.status:
            _update_customer_kyc_status(self.customer)


def _update_customer_kyc_status(customer_name):
    """Recalculate and update the customer's kyc_status based on their documents.

    Sends notification to customer on status change (Story 4.4 AC3).
    """
    # Read current status before changing
    old_status = frappe.db.get_value("Customer", customer_name, "kyc_status")

    docs = frappe.get_all(
        "KYC Document",
        filters={"customer": customer_name},
        fields=["status", "document_type"],
    )

    if not docs:
        frappe.db.set_value("Customer", customer_name, "kyc_status", "Unverified")
        frappe.db.set_value("Customer", customer_name, "kyc_completed_date", None)
        _notify_kyc_status_change(customer_name, old_status, "Unverified")
        return

    # Identify document_types that have at least one Verified doc
    # Rejected/Expired docs for those types are superseded by re-upload + approval
    types_with_verified = {d.document_type for d in docs if d.status == "Verified"}

    # Build effective statuses excluding superseded rejected and expired docs
    effective_statuses = set()
    for d in docs:
        if d.status == "Rejected" and d.document_type in types_with_verified:
            continue  # Superseded by a verified re-upload of the same type
        if d.status == "Expired":
            continue  # Expired docs don't affect current KYC status
        effective_statuses.add(d.status)

    if not effective_statuses:
        new_status = "Unverified"
        frappe.db.set_value("Customer", customer_name, "kyc_completed_date", None)
    elif "Pending Review" in effective_statuses:
        new_status = "Pending Review"
        frappe.db.set_value("Customer", customer_name, "kyc_completed_date", None)
    elif "Rejected" in effective_statuses:
        new_status = "Rejected"
        frappe.db.set_value("Customer", customer_name, "kyc_completed_date", None)
    elif effective_statuses == {"Verified"}:
        new_status = "Verified"
        frappe.db.set_value("Customer", customer_name, "kyc_completed_date", frappe.utils.today())
    else:
        new_status = "Unverified"
        frappe.db.set_value("Customer", customer_name, "kyc_completed_date", None)

    frappe.db.set_value("Customer", customer_name, "kyc_status", new_status)

    # Notify on status change (skip if old_status was None — first-time init)
    if old_status is not None and old_status != new_status:
        _notify_kyc_status_change(customer_name, old_status, new_status)


def _notify_kyc_status_change(customer_name, old_status, new_status):
    """Send Notification Log to customer when their KYC status changes.

    Also triggers email/SMS notification via the notification engine (Story 5.2).
    """
    # Trigger email/SMS via the notification engine
    try:
        from bike_rental.notification.event_handlers import on_kyc_status_change
        on_kyc_status_change(customer_name, old_status, new_status)
    except Exception:
        frappe.log_error(
            title="KYC Notification Failed",
            message="Customer {0}: {1} -> {2}".format(customer_name, old_status, new_status),
        )

    customer_email = frappe.db.get_value("Customer", customer_name, "email")
    if not customer_email:
        return

    subject_map = {
        ("Unverified", "Verified"): _("Your KYC verification is complete! You are now ready to rent bikes."),
        ("Pending Review", "Verified"): _("Your KYC verification is complete! You are now ready to rent bikes."),
        ("Rejected", "Verified"): _("Your KYC verification is complete! You are now ready to rent bikes."),
        ("Verified", "Unverified"): _("Your KYC documents have expired. Please upload new documents to continue renting."),
        ("Verified", "Pending Review"): _("New KYC documents uploaded and are under review."),
    }

    transition = (old_status, new_status)

    if transition in subject_map:
        subject = subject_map[transition]
        content_map = {
            ("Unverified", "Verified"): _(
                "Your KYC verification is complete. You can now rent bikes."
            ),
            ("Pending Review", "Verified"): _(
                "Your KYC verification is complete. You can now rent bikes."
            ),
            ("Rejected", "Verified"): _(
                "Your KYC verification is complete. You can now rent bikes."
            ),
            ("Verified", "Unverified"): _(
                "Your KYC documents have expired. Please upload new documents from your profile to continue renting."
            ),
            ("Verified", "Pending Review"): _(
                "Your new KYC documents have been received and are under review. "
                "Documents are typically reviewed within 24 hours."
            ),
        }
        email_content = content_map[transition]
    elif new_status == "Pending Review":
        subject = _("Your KYC documents are under review")
        email_content = _(
            "Your KYC documents have been received and are under review. "
            "Documents are typically reviewed within 24 hours."
        )
    elif new_status == "Rejected":
        subject = _("Your KYC documents have been rejected")
        # Fetch the most recent rejection reason
        last_rejection = frappe.get_all(
            "KYC Document",
            filters={"customer": customer_name, "status": "Rejected"},
            fields=["rejection_reason"],
            order_by="review_date desc",
            limit=1,
        )
        reason = ""
        if last_rejection and last_rejection[0].rejection_reason:
            reason = _("\nReason: {0}").format(last_rejection[0].rejection_reason)
        email_content = _(
            "Your KYC documents have been rejected.{0}\n\n"
            "Please upload new documents from your profile.").format(reason)
    elif new_status == "Unverified":
        subject = _("Your KYC status has been reset")
        email_content = _(
            "Your KYC status has been reset. "
            "Please upload your documents from your profile."
        )
    else:
        return

    notification = frappe.get_doc({
        "doctype": "Notification Log",
        "subject": subject,
        "email_content": email_content,
        "for_user": customer_email,
        "document_type": "Customer",
        "document_name": customer_name,
    })
    notification.insert(ignore_permissions=True)
