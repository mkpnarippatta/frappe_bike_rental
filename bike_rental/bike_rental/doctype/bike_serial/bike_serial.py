from __future__ import unicode_literals

import frappe
from frappe.model.document import Document


class BikeSerial(Document):
    def before_save(self):
        self._validate_status_transition()
        self._log_status_change()

    def _validate_status_transition(self):
        old_doc = self.get_doc_before_save()
        if old_doc and old_doc.status in ("Rented", "Maintenance") and self.status == "Scrapped":
            frappe.throw(
                "Release bike from Rented/Maintenance before scrapping",
                frappe.ValidationError,
            )

    def _log_status_change(self):
        old_doc = self.get_doc_before_save()
        if old_doc and old_doc.status != self.status:
            frappe.get_doc(
                {
                    "doctype": "Notification Log",
                    "subject": f"Bike Serial {self.registration_no}: {old_doc.status} → {self.status}",
                    "type": "Alert",
                    "document_type": "Bike Serial",
                    "document_name": self.name,
                    "for_user": "Administrator",
                }
            ).insert(ignore_permissions=True)


@frappe.whitelist()
def get_total_capacity(bike_model, hub=None):
    """Return total capacity for a Bike Model, optionally filtered by hub.

    Total Capacity = count of Bike Serials where status is Available or Rented.
    Excludes Scrapped, In Transit, and Maintenance (FR-03, FR-28).
    """
    filters = {
        "bike_model": bike_model,
        "status": ["not in", ["Scrapped", "In Transit", "Maintenance"]],
    }
    if hub:
        filters["hub"] = hub

    return frappe.db.count("Bike Serial", filters=filters)
