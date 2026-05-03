from __future__ import unicode_literals

import frappe
from frappe.utils import today


def expire_kyc_documents():
    """Expire KYC documents past their expiry_date.

    Daily job: finds Verified KYC Documents where expiry_date < today,
    sets status to Expired, and triggers customer KYC status rollup.
    Uses doc.save() to fire on_update hook for rollup.
    """
    docs = frappe.get_all(
        "KYC Document",
        filters={
            "status": "Verified",
            "expiry_date": ["<", today()],
        },
        fields=["name"],
    )

    expired_count = 0
    failed_count = 0
    for d in docs:
        try:
            doc = frappe.get_doc("KYC Document", d.name)
            doc.status = "Expired"
            doc.save()
            expired_count += 1
        except Exception:
            failed_count += 1
            frappe.log_error(
                title="KYC Document Expiry Error",
                message=f"Failed to expire document {d.name}",
            )

    if expired_count or failed_count:
        frappe.logger("scheduler").info(
            f"KYC document expiry: {expired_count} expired, {failed_count} failed."
        )
