from __future__ import unicode_literals

import frappe
from frappe.model.document import Document


class NotificationQueue(Document):
    def validate(self):
        if self.status == "Processing" and not self.last_retry_at:
            self.last_retry_at = frappe.utils.now_datetime()
