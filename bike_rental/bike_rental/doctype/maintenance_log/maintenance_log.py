from __future__ import unicode_literals

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class MaintenanceLog(Document):
    def before_insert(self):
        if not self.reported_date:
            self.reported_date = now_datetime()
        if not self.reported_by:
            self.reported_by = frappe.session.user

        if not frappe.db.exists("Bike Serial", self.serial_no):
            frappe.throw(
                f"Bike Serial {self.serial_no} does not exist",
                frappe.ValidationError,
            )

        serial = frappe.get_doc("Bike Serial", self.serial_no)
        if serial.status in ("Maintenance", "Scrapped", "Rented"):
            frappe.throw(
                f"Bike Serial {self.serial_no} is {serial.status} — cannot mark for maintenance",
                frappe.ValidationError,
            )

    def after_insert(self):
        serial = frappe.get_doc("Bike Serial", self.serial_no)
        serial.db_set("status", "Maintenance")

        frappe.get_doc(
            {
                "doctype": "Notification Log",
                "subject": f"Bike Serial {self.serial_no} marked for maintenance: {self.issue_description}",
                "type": "Alert",
                "document_type": "Maintenance Log",
                "document_name": self.name,
                "for_user": self.reported_by,
            }
        ).insert(ignore_permissions=True)

    def validate(self):
        if self.status == "Resolved" and not self.resolution_notes:
            frappe.throw(
                "Resolution notes are required before resolving a maintenance log",
                frappe.ValidationError,
            )

    def before_save(self):
        old_doc = self.get_doc_before_save()
        if old_doc and old_doc.status != "Resolved" and self.status == "Resolved":
            self.resolved_date = now_datetime()
            self.resolved_by = frappe.session.user

    def on_update(self):
        old_doc = self.get_doc_before_save()
        if not old_doc:
            return

        if old_doc.status != "Resolved" and self.status == "Resolved":
            other_unresolved = frappe.db.count(
                "Maintenance Log",
                filters={
                    "serial_no": self.serial_no,
                    "status": "In Progress",
                    "name": ["!=", self.name],
                },
            )

            if other_unresolved == 0:
                serial = frappe.get_doc("Bike Serial", self.serial_no)
                # Only restore if serial is still in Maintenance (defense in depth)
                if serial.status == "Maintenance":
                    serial.db_set("status", "Available")

                    frappe.get_doc(
                        {
                            "doctype": "Notification Log",
                            "subject": f"Bike Serial {self.serial_no} restored to service after maintenance",
                            "type": "Alert",
                            "document_type": "Maintenance Log",
                            "document_name": self.name,
                            "for_user": self.resolved_by or self.reported_by,
                        }
                    ).insert(ignore_permissions=True)

    def on_trash(self):
        if self.status == "In Progress":
            frappe.throw(
                "Cannot delete a maintenance log that is still In Progress. Resolve it first.",
                frappe.ValidationError,
            )
