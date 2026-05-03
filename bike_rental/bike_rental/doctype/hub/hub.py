from __future__ import unicode_literals

import frappe
from frappe.model.document import Document


class Hub(Document):
    pass


@frappe.whitelist()
def get_available_count(bike_model, hub):
    """Return count of Available Bike Serials for a model at a specific hub.

    Excludes serials in Rented, Maintenance, or Scrapped status (FR-36).
    """
    return frappe.db.count(
        "Bike Serial",
        filters={
            "bike_model": bike_model,
            "hub": hub,
            "status": "Available",
        },
    )


@frappe.whitelist()
def initiate_transfer(serial_name, to_hub):
    """Initiate a hub transfer for a Bike Serial (FR-37).

    Sets status to In Transit and assigns the destination hub immediately.
    In Transit bikes are excluded from availability at all hubs.
    Blocks transfer if bike is currently Rented.
    """
    serial = frappe.get_doc("Bike Serial", serial_name)

    if serial.status == "Rented":
        frappe.throw(
            "Cannot transfer a rented bike. Complete rental first.",
            frappe.ValidationError,
        )

    serial.db_set("hub", to_hub)
    serial.db_set("status", "In Transit")
    return serial


@frappe.whitelist()
def confirm_arrival(serial_name):
    """Confirm a Bike Serial has arrived at its destination hub (FR-37).

    Sets status back to Available. The hub field already points to
    the destination hub from initiate_transfer.
    """
    serial = frappe.get_doc("Bike Serial", serial_name)
    serial.db_set("status", "Available")
    return serial
