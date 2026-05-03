from __future__ import unicode_literals

import frappe
from frappe.model.document import Document


class BikeModel(Document):
    def before_delete(self):
        """Prevent deletion if active or future Rental Bookings reference this model."""
        bookings = frappe.get_all(
            "Rental Booking",
            filters={
                "bike_model": self.name,
                "status": ["in", ["Draft", "Confirmed", "Active"]],
            },
            limit=1,
        )
        if bookings:
            frappe.throw(
                "Cannot delete Bike Model with active or future bookings",
                frappe.ValidationError,
            )
