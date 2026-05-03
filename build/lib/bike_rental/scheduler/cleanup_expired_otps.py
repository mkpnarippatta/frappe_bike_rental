import frappe
from frappe.utils import add_to_date, now_datetime


def cleanup_expired_otps():
    """Delete OTP Request records older than 24 hours."""
    cutoff = add_to_date(now_datetime(), hours=-24)

    old_otps = frappe.get_all(
        "OTP Request",
        filters={"creation": ["<", cutoff]},
        pluck="name",
    )

    for name in old_otps:
        frappe.delete_doc("OTP Request", name, force=True, ignore_permissions=True)

    frappe.db.commit()
