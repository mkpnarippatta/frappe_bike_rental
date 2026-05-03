from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from bike_rental.api.kyc import (
    approve_kyc_document,
    check_kyc_booking_status,
    reject_kyc_document,
    upload_kyc_document,
)
from bike_rental.api.payments import create_cash_payment
from bike_rental.bike_rental.doctype.kyc_document.kyc_document import _update_customer_kyc_status


class TestKYCBookingIntegration(FrappeTestCase):
    """Tests for KYC status integration at booking time (Story 4.4)."""

    def setUp(self):
        self.customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": "KYC Booking Test Customer",
            "email": "kyc-booking-test@example.com",
            "phone": "+1111111111",
        }).insert()

        self.file = frappe.get_doc({
            "doctype": "File",
            "file_name": "kyc_booking_test.pdf",
            "file_url": "/private/files/kyc_booking_test.pdf",
            "is_private": 1,
            "file_size": 512000,
            "content_hash": "kyc_booking_123",
        }).insert()

        self.hub = frappe.get_doc({
            "doctype": "Hub",
            "hub_name": "KYC Test Hub",
            "address": "123 Test St",
            "phone": "+911234567890",
            "operating_hours": "6AM-10PM",
        }).insert()

        self.bike_model = frappe.get_doc({
            "doctype": "Bike Model",
            "model_name": "KYC Test Cruiser",
            "category": "City",
            "daily_rate": 500,
        }).insert()

        self.bike_serial = frappe.get_doc({
            "doctype": "Bike Serial",
            "bike_model": self.bike_model.name,
            "registration_no": "KYC-TEST-001",
            "hub": self.hub.name,
            "status": "Available",
            "current_km": 100,
            "battery_level": 90,
        }).insert()

    def tearDown(self):
        for name in frappe.get_all("Notification Log", pluck="name"):
            frappe.delete_doc("Notification Log", name, force=True)
        # Cancel and delete Payment Entries first (child docs)
        for name in frappe.get_all("Payment Entry", pluck="name"):
            try:
                frappe.get_doc("Payment Entry", name).cancel()
            except Exception:
                pass
            frappe.delete_doc("Payment Entry", name, force=True)
        for name in frappe.get_all("Rental Booking", pluck="name"):
            frappe.delete_doc("Rental Booking", name, force=True)
        for name in frappe.get_all("KYC Document", pluck="name"):
            frappe.delete_doc("KYC Document", name, force=True)
        for name in frappe.get_all("File", pluck="name"):
            frappe.delete_doc("File", name, force=True)
        for name in frappe.get_all("Bike Serial", pluck="name"):
            frappe.delete_doc("Bike Serial", name, force=True)
        for name in frappe.get_all("Bike Model", pluck="name"):
            frappe.delete_doc("Bike Model", name, force=True)
        for name in frappe.get_all("Hub", pluck="name"):
            frappe.delete_doc("Hub", name, force=True)
        for name in frappe.get_all("Customer", pluck="name"):
            frappe.delete_doc("Customer", name, force=True)

    # ── Helpers ──

    def _create_draft_booking(self):
        """Create a draft Rental Booking for testing."""
        booking = frappe.get_doc({
            "doctype": "Rental Booking",
            "bike_model": self.bike_model.name,
            "customer": self.customer.name,
            "pickup_hub": self.hub.name,
            "return_hub": self.hub.name,
            "pickup_datetime": "2026-06-01 10:00:00",
            "return_datetime": "2026-06-02 10:00:00",
        })
        booking.insert()
        return booking

    def _set_kyc_status(self, status):
        """Directly set customer KYC status for testing."""
        frappe.db.set_value("Customer", self.customer.name, "kyc_status", status)
        if status == "Verified":
            frappe.db.set_value("Customer", self.customer.name, "kyc_completed_date", "2026-05-01")
        else:
            frappe.db.set_value("Customer", self.customer.name, "kyc_completed_date", None)

    # ── _validate_kyc_status Tests ──

    def test_validate_kyc_status_blocks_unverified(self):
        """Unverified customer cannot submit a booking."""
        self._set_kyc_status("Unverified")
        booking = self._create_draft_booking()
        with self.assertRaises(frappe.ValidationError) as ctx:
            booking.submit()
        self.assertIn("KYC", str(ctx.exception))

    def test_validate_kyc_status_blocks_rejected(self):
        """Rejected customer cannot submit a booking."""
        self._set_kyc_status("Rejected")
        booking = self._create_draft_booking()
        with self.assertRaises(frappe.ValidationError) as ctx:
            booking.submit()
        self.assertIn("rejected", str(ctx.exception).lower())

    def test_validate_kyc_status_allows_pending_review(self):
        """Pending Review customer can submit with informational message."""
        self._set_kyc_status("Pending Review")
        booking = self._create_draft_booking()
        # Submit via payment flow to satisfy the full before_submit chain
        result = create_cash_payment(booking.name, 100.00)
        self.assertEqual(result["status"], "Confirmed")

    def test_validate_kyc_status_allows_verified(self):
        """Verified customer can submit without issues."""
        self._set_kyc_status("Verified")
        booking = self._create_draft_booking()
        result = create_cash_payment(booking.name, 100.00)
        self.assertEqual(result["status"], "Confirmed")

    def test_before_submit_chain_order_kyc_first(self):
        """KYC check runs before availability check in before_submit."""
        # This is verified by the method call order in before_submit:
        # _validate_kyc_status() is called first, before _re_verify_availability()
        # If KYC fails, availability check should never run
        self._set_kyc_status("Unverified")
        booking = self._create_draft_booking()
        with self.assertRaises(frappe.ValidationError) as ctx:
            booking.submit()
        self.assertIn("KYC", str(ctx.exception))
        # Verify booking is still Draft (not Confirmed)
        self.assertEqual(frappe.db.get_value("Rental Booking", booking.name, "status"), "Draft")

    # ── check_kyc_booking_status Tests ──

    def test_check_kyc_status_unverified_cannot_book(self):
        """Unverified returns can_book=False and lists required docs."""
        self._set_kyc_status("Unverified")
        result = check_kyc_booking_status(self.customer.name)
        self.assertEqual(result["kyc_status"], "Unverified")
        self.assertFalse(result["can_book"])
        self.assertIn("ID Proof", result["required_document_types"])

    def test_check_kyc_status_rejected_cannot_book(self):
        """Rejected returns can_book=False."""
        self._set_kyc_status("Rejected")
        result = check_kyc_booking_status(self.customer.name)
        self.assertEqual(result["kyc_status"], "Rejected")
        self.assertFalse(result["can_book"])

    def test_check_kyc_status_pending_review_can_book(self):
        """Pending Review returns can_book=True with review message."""
        self._set_kyc_status("Pending Review")
        result = check_kyc_booking_status(self.customer.name)
        self.assertEqual(result["kyc_status"], "Pending Review")
        self.assertTrue(result["can_book"])
        self.assertIn("24 hours", result["estimated_review_time"])

    def test_check_kyc_status_verified_can_book(self):
        """Verified returns can_book=True with completed date."""
        self._set_kyc_status("Verified")
        result = check_kyc_booking_status(self.customer.name)
        self.assertEqual(result["kyc_status"], "Verified")
        self.assertTrue(result["can_book"])
        self.assertIsNotNone(result["kyc_completed_date"])

    def test_check_kyc_status_rejected_includes_reason(self):
        """Rejected response includes rejection_reason from latest rejected doc."""
        # Upload and reject a document
        doc_name = self._upload_and_get_doc_name()
        from bike_rental.api.kyc import reject_kyc_document
        reject_kyc_document(doc_name, "Document is not clear")

        result = check_kyc_booking_status(self.customer.name)
        self.assertEqual(result["kyc_status"], "Rejected")
        self.assertFalse(result["can_book"])
        self.assertEqual(result["rejection_reason"], "Document is not clear")

    def test_check_kyc_status_pending_review_includes_pending_since(self):
        """Pending Review response includes pending_since date."""
        doc_name = self._upload_and_get_doc_name()
        result = check_kyc_booking_status(self.customer.name)
        self.assertEqual(result["kyc_status"], "Pending Review")
        self.assertTrue(result["can_book"])
        self.assertIsNotNone(result["pending_since"])

    def test_check_kyc_status_unverified_includes_required_doc_types(self):
        """Unverified response lists required document types."""
        self._set_kyc_status("Unverified")
        result = check_kyc_booking_status(self.customer.name)
        self.assertEqual(result["kyc_status"], "Unverified")
        self.assertFalse(result["can_book"])
        self.assertIn("ID Proof", result["required_document_types"])
        self.assertIn("Driving License", result["required_document_types"])

    def test_check_kyc_status_access_control_non_owner(self):
        """Non-owner without staff role is denied access."""
        original_user = frappe.session.user
        frappe.session.user = "other-user@example.com"
        try:
            with self.assertRaises(frappe.PermissionError):
                check_kyc_booking_status(self.customer.name)
        finally:
            frappe.session.user = original_user

    # ── Notification Tests ──

    def test_notification_on_unverified_to_pending_review(self):
        """Notification created when status changes Unverified → Pending Review."""
        self._set_kyc_status("Unverified")
        # Upload triggers status change via after_insert
        doc_name = self._upload_and_get_doc_name()
        notifications = frappe.get_all(
            "Notification Log",
            filters={"for_user": self.customer.email},
            pluck="subject",
        )
        status_msgs = [s for s in notifications if "under review" in s.lower()]
        self.assertTrue(len(status_msgs) > 0, "No Pending Review notification found")

    def test_notification_on_pending_review_to_verified(self):
        """Notification created when status changes Pending Review → Verified."""
        doc_name = self._upload_and_get_doc_name()
        # Clear notification logs from upload
        for name in frappe.get_all("Notification Log", pluck="name"):
            frappe.delete_doc("Notification Log", name, force=True)
        # Approve the document
        approve_kyc_document(doc_name)
        notifications = frappe.get_all(
            "Notification Log",
            filters={"for_user": self.customer.email},
            pluck="subject",
        )
        complete_msgs = [s for s in notifications if "complete" in s.lower()]
        self.assertTrue(len(complete_msgs) > 0, "No Verified notification found")

    def test_notification_on_pending_review_to_rejected(self):
        """Notification created when status changes Pending Review → Rejected."""
        doc_name = self._upload_and_get_doc_name()
        # Clear notification logs from upload
        for name in frappe.get_all("Notification Log", pluck="name"):
            frappe.delete_doc("Notification Log", name, force=True)
        # Reject the document
        reject_kyc_document(doc_name, "Invalid document")
        notifications = frappe.get_all(
            "Notification Log",
            filters={"for_user": self.customer.email},
            pluck="subject",
        )
        rejected_msgs = [s for s in notifications if "rejected" in s.lower()]
        self.assertTrue(len(rejected_msgs) > 0, "No Rejected notification found")

    def test_notification_not_created_on_no_status_change(self):
        """No notification when status remains unchanged."""
        self._set_kyc_status("Unverified")
        # Clear any existing notifications
        for name in frappe.get_all("Notification Log", pluck="name"):
            frappe.delete_doc("Notification Log", name, force=True)
        # Set same status — no change
        _update_customer_kyc_status(self.customer.name)
        notifications = frappe.get_all("Notification Log", pluck="name")
        self.assertEqual(len(notifications), 0, "Notification created without status change")

    # ── Helpers ──

    def _upload_and_get_doc_name(self):
        """Upload a KYC document and return its name."""
        result = upload_kyc_document(self.customer.name, "ID Proof", self.file.file_url)
        return result["kyc_document"]["name"]
