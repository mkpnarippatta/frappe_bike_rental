from __future__ import unicode_literals

import frappe
from frappe.model.document import Document
from frappe.utils import add_to_date, now_datetime


class OTPRequest(Document):
    def validate(self):
        if not self.expires_at:
            self.expires_at = add_to_date(now_datetime(), minutes=5)
