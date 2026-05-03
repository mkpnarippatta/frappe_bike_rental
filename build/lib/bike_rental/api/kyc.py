from __future__ import unicode_literals

import os

import frappe
from frappe import _
from frappe.utils import now_datetime

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB in bytes


@frappe.whitelist()
def upload_kyc_document(customer, document_type, file_url):
    """Upload a KYC document against a customer profile.

    Validates customer exists, document_type is valid, file format and size.
    Creates KYC Document record with Pending Review status and updates
    Customer kyc_status if needed (FR-23).
    """
    _validate_customer(customer)
    _validate_document_type(document_type)

    file_doc = _validate_file(file_url)

    # Prevent duplicate upload of same document_type with pending/verified status
    existing = frappe.db.exists("KYC Document", {
        "customer": customer,
        "document_type": document_type,
        "status": ["in", ["Pending Review", "Verified"]],
    })
    if existing:
        frappe.throw(
            _("A {0} document already exists with status Pending Review or Verified. "
              "Upload a new document only if the previous one was rejected.").format(document_type),
            frappe.ValidationError,
        )

    kyc_doc = frappe.get_doc({
        "doctype": "KYC Document",
        "customer": customer,
        "document_type": document_type,
        "document": file_url,
        "status": "Pending Review",
    })
    kyc_doc.insert(ignore_permissions=True)

    customer_kyc_status = frappe.db.get_value("Customer", customer, "kyc_status")

    return {
        "status": "success",
        "kyc_document": {
            "name": kyc_doc.name,
            "customer": customer,
            "document_type": document_type,
            "status": "Pending Review",
            "uploaded_date": kyc_doc.uploaded_date,
            "file_url": file_url,
        },
        "customer_kyc_status": customer_kyc_status,
        "message": _(
            "Document uploaded successfully. "
            "Documents are typically reviewed within 24 hours. "
            "You will receive a notification once reviewed."
        ),
    }


@frappe.whitelist()
def get_kyc_documents(customer):
    """Return all KYC documents for a customer.

    AR-09: Owner-only reads + Hub Manager/Staff override.
    """
    _validate_customer(customer)

    if not _can_access_customer_kyc(customer):
        frappe.throw(
            _("You do not have permission to view KYC documents for this customer"),
            frappe.PermissionError,
        )

    documents = frappe.get_all(
        "KYC Document",
        filters={"customer": customer},
        fields=["name", "document_type", "status", "uploaded_date", "document", "rejection_reason"],
        order_by="uploaded_date desc",
    )

    return {
        "status": "success",
        "documents": documents,
    }


@frappe.whitelist()
def get_kyc_status(customer):
    """Return the current KYC status summary for a customer.

    AR-09: Owner-only reads + Hub Manager/Staff override.
    """
    _validate_customer(customer)

    if not _can_access_customer_kyc(customer):
        frappe.throw(
            _("You do not have permission to view KYC documents for this customer"),
            frappe.PermissionError,
        )

    kyc_status = frappe.db.get_value("Customer", customer, "kyc_status")
    documents = frappe.get_all(
        "KYC Document",
        filters={"customer": customer},
        fields=["document_type", "status"],
    )

    return {
        "status": "success",
        "kyc_status": kyc_status or "Unverified",
        "documents": documents,
    }


# ── Staff Verification API (Story 4.2) ──


@frappe.whitelist()
def get_kyc_verification_queue():
    """Return all pending KYC documents for staff review.

    FR-25: Staff review queue. Only Hub Staff/Manager/System Manager.
    Returns documents sorted by upload_date ascending (oldest first).
    """
    _check_staff_role()

    documents = frappe.get_all(
        "KYC Document",
        filters={"status": "Pending Review"},
        fields=["name", "customer", "document_type", "uploaded_date", "document"],
        order_by="uploaded_date asc",
    )

    # Resolve customer names for display
    for doc in documents:
        doc.customer_name = frappe.db.get_value("Customer", doc.customer, "customer_name")

    return {
        "status": "success",
        "documents": documents,
    }


@frappe.whitelist()
def approve_kyc_document(document_name, expiry_date=None):
    """Approve a KYC document.

    Sets status to Verified, records reviewer info, sends notification.
    Uses frappe.get_doc().save() to trigger on_update hook for status rollup.
    Optionally sets an expiry_date for the document (Story 4.3).
    """
    _check_staff_role()

    if not frappe.db.exists("KYC Document", document_name):
        frappe.throw(_("KYC Document {0} not found").format(document_name), frappe.ValidationError)

    doc = frappe.get_doc("KYC Document", document_name)

    if doc.status == "Verified":
        frappe.throw(
            _("KYC Document {0} is already verified").format(document_name),
            frappe.ValidationError,
        )

    if doc.status != "Pending Review":
        frappe.throw(
            _("KYC Document {0} cannot be approved because its status is {1}").format(
                document_name, doc.status
            ),
            frappe.ValidationError,
        )

    doc.status = "Verified"
    doc.reviewed_by = frappe.session.user
    doc.review_date = now_datetime()
    if expiry_date:
        from frappe.utils import today
        if expiry_date < today():
            frappe.throw(
                _("Expiry date must be today or in the future"),
                frappe.ValidationError,
            )
        doc.expiry_date = expiry_date

    # Create per-doc notification BEFORE save so a notification failure
    # prevents the status change (rollback safety)
    _create_kyc_notification(
        doc,
        _("Your KYC document ({0}) has been approved").format(doc.document_type),
        _("Your {0} has been reviewed and approved.").format(doc.document_type),
    )

    doc.save()

    # Check if all documents are now verified and notify if so
    # (reads from DB, must be after save)
    _notify_kyc_verified_if_complete(doc.customer)

    return {
        "status": "success",
        "kyc_document": {
            "name": doc.name,
            "status": doc.status,
            "reviewed_by": doc.reviewed_by,
            "review_date": doc.review_date,
        },
    }


@frappe.whitelist()
def reject_kyc_document(document_name, rejection_reason=None):
    """Reject a KYC document with a reason.

    Sets status to Rejected, records reviewer info and reason, sends notification.
    """
    _check_staff_role()

    if not rejection_reason or not rejection_reason.strip():
        frappe.throw(
            _("Rejection reason is required when rejecting a KYC document"),
            frappe.ValidationError,
        )

    if not frappe.db.exists("KYC Document", document_name):
        frappe.throw(_("KYC Document {0} not found").format(document_name), frappe.ValidationError)

    doc = frappe.get_doc("KYC Document", document_name)

    if doc.status == "Rejected":
        frappe.throw(
            _("KYC Document {0} is already rejected").format(document_name),
            frappe.ValidationError,
        )

    if doc.status != "Pending Review":
        frappe.throw(
            _("KYC Document {0} cannot be rejected because its status is {1}").format(
                document_name, doc.status
            ),
            frappe.ValidationError,
        )

    doc.status = "Rejected"
    doc.reviewed_by = frappe.session.user
    doc.review_date = now_datetime()
    doc.rejection_reason = rejection_reason.strip()

    # Create per-doc notification BEFORE save so a notification failure
    # prevents the status change (rollback safety)
    _create_kyc_notification(
        doc,
        _("Your KYC document ({0}) has been rejected").format(doc.document_type),
        _("Your {0} has been rejected.\nReason: {1}\n\nPlease upload a new document.").format(
            doc.document_type, rejection_reason
        ),
    )

    doc.save()

    return {
        "status": "success",
        "kyc_document": {
            "name": doc.name,
            "status": doc.status,
            "reviewed_by": doc.reviewed_by,
            "review_date": doc.review_date,
            "rejection_reason": doc.rejection_reason,
        },
    }


# ── Internal Notification Helpers (Story 4.2) ──


def _check_staff_role():
    """Verify the current user has staff-level access."""
    roles = frappe.get_roles()
    if not ("Hub Staff" in roles or "Hub Manager" in roles or "System Manager" in roles):
        frappe.throw(
            _("You do not have permission to verify KYC documents"),
            frappe.PermissionError,
        )


def _create_kyc_notification(kyc_doc, subject, content):
    """Create an in-app Notification Log for the customer."""
    customer_email = frappe.db.get_value("Customer", kyc_doc.customer, "email")
    if not customer_email:
        frappe.logger().info(
            "KYC notification skipped: Customer %s has no email", kyc_doc.customer
        )
        return

    notification = frappe.get_doc({
        "doctype": "Notification Log",
        "subject": subject,
        "email_content": content,
        "for_user": customer_email,
        "document_type": "KYC Document",
        "document_name": kyc_doc.name,
    })
    notification.insert(ignore_permissions=True)


def _notify_kyc_verified_if_complete(customer_name):
    """Notify customer if all their KYC documents are now Verified."""
    docs = frappe.get_all(
        "KYC Document",
        filters={"customer": customer_name},
        pluck="status",
    )
    if not docs:
        return

    # Exclude Expired docs (they are filtered in the rollup logic too)
    active_statuses = {s for s in docs if s != "Expired"}
    if not active_statuses:
        return

    if active_statuses == {"Verified"}:
        customer_email = frappe.db.get_value("Customer", customer_name, "email")
        if customer_email:
            notification = frappe.get_doc({
                "doctype": "Notification Log",
                "subject": _("Your KYC verification is complete. You can now rent bikes."),
                "email_content": _(
                    "All your KYC documents have been verified. "
                    "You are now ready to rent bikes."
                ),
                "for_user": customer_email,
                "document_type": "Customer",
                "document_name": customer_name,
            })
            notification.insert(ignore_permissions=True)


@frappe.whitelist()
def check_kyc_booking_status(customer):
    """Return KYC requirements status for booking confirmation.

    Lightweight check endpoint for frontends to determine if a customer
    can proceed with booking. Returns user-facing guidance messages
    consistent with the acceptance criteria (Story 4.4).

    AR-09: Owner-only reads + Hub Manager/Staff override.
    """
    _validate_customer(customer)

    if not _can_access_customer_kyc(customer):
        frappe.throw(
            _("You do not have permission to view KYC status for this customer"),
            frappe.PermissionError,
        )

    kyc_status = frappe.db.get_value("Customer", customer, "kyc_status") or "Unverified"

    result = {
        "status": "success",
        "kyc_status": kyc_status,
    }

    if kyc_status == "Verified":
        kyc_completed = frappe.db.get_value("Customer", customer, "kyc_completed_date")
        result["can_book"] = True
        result["message"] = _("Your KYC is verified. You can proceed with the booking.")
        result["kyc_completed_date"] = str(kyc_completed) if kyc_completed else None
    elif kyc_status == "Pending Review":
        # Find pending_since: earliest uploaded_date of pending docs
        pending_docs = frappe.get_all(
            "KYC Document",
            filters={"customer": customer, "status": "Pending Review"},
            fields=["uploaded_date"],
            order_by="uploaded_date asc",
            limit=1,
        )
        result["can_book"] = True
        result["message"] = _(
            "Your KYC documents are under review. "
            "Documents are typically reviewed within 24 hours. "
            "You will receive a notification once verified."
        )
        result["estimated_review_time"] = _("Documents are typically reviewed within 24 hours")
        result["pending_since"] = str(pending_docs[0].uploaded_date) if pending_docs else None
    elif kyc_status == "Rejected":
        last_rejection = frappe.get_all(
            "KYC Document",
            filters={"customer": customer, "status": "Rejected"},
            fields=["rejection_reason"],
            order_by="review_date desc",
            limit=1,
        )
        result["can_book"] = False
        result["message"] = _(
            "Your KYC verification has been rejected. "
            "Please re-upload your documents from your profile."
        )
        if last_rejection and last_rejection[0].rejection_reason:
            result["rejection_reason"] = last_rejection[0].rejection_reason
    else:  # Unverified
        result["can_book"] = False
        result["message"] = _(
            "Please complete KYC verification before confirming your booking. "
            "Upload your ID documents (ID Proof and Driving License) from your profile."
        )
        result["required_document_types"] = ["ID Proof", "Driving License"]

    return result


# ── Permission hook (registered in hooks.py) ──

def has_kyc_document_permission(doc, ptype, user):
    """Enforce AR-09: owner-only reads + Hub Manager/Staff override.

    Customers can only read their own KYC documents.
    Hub Staff and Hub Managers can read all KYC documents.
    """
    if ptype == "read":
        if "Hub Staff" in frappe.get_roles(user) or "Hub Manager" in frappe.get_roles(user) or "System Manager" in frappe.get_roles(user):
            return True
        customer_email = frappe.db.get_value("Customer", doc.customer, "email")
        if customer_email and customer_email == user:
            return True
        return False

    return "Hub Staff" in frappe.get_roles(user) or "Hub Manager" in frappe.get_roles(user) or "System Manager" in frappe.get_roles(user)


# ── Internal helpers ──

def _validate_customer(customer):
    if not frappe.db.exists("Customer", customer):
        frappe.throw(
            _("Customer {0} does not exist").format(customer),
            frappe.ValidationError,
        )


def _validate_document_type(document_type):
    allowed = ["ID Proof", "Driving License"]
    if document_type not in allowed:
        frappe.throw(
            _("Invalid document type. Select: {0}").format(", ".join(allowed)),
            frappe.ValidationError,
        )


def _validate_file(file_url):
    if not frappe.db.exists("File", {"file_url": file_url}):
        frappe.throw(
            _("File {0} not found. Upload the file first.").format(file_url),
            frappe.ValidationError,
        )

    file_doc = frappe.get_doc("File", {"file_url": file_url})

    if not file_doc.file_name:
        frappe.throw(
            _("File has no name. Upload the file again."),
            frappe.ValidationError,
        )

    ext = os.path.splitext(file_doc.file_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        frappe.throw(
            _("Unsupported file format. Accepted formats: PDF, JPG, PNG"),
            frappe.ValidationError,
        )

    if file_doc.file_size is not None and file_doc.file_size > MAX_FILE_SIZE:
        frappe.throw(
            _("File size exceeds the 10MB limit. Please compress the file and try again."),
            frappe.ValidationError,
        )

    # Enforce private file storage for PII documents (NFR-03)
    if not file_doc.is_private:
        frappe.throw(
            _("KYC documents must be uploaded as private files."),
            frappe.ValidationError,
        )

    return file_doc


def _can_access_customer_kyc(customer_name):
    """Check if the current user can access KYC data for this customer."""
    roles = frappe.get_roles()
    if "Hub Manager" in roles or "Hub Staff" in roles or "System Manager" in roles:
        return True
    customer_email = frappe.db.get_value("Customer", customer_name, "email")
    return customer_email and frappe.session.user == customer_email
