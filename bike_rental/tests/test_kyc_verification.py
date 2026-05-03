from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from bike_rental.api.kyc import (
    get_kyc_verification_queue,
    approve_kyc_document,
    reject_kyc_document,
    upload_kyc_document,
)


class TestKYCVerificationAPI(FrappeTestCase):
    """Tests for KYC verification workflow (Story 4.2)."""

    def setUp(self):
        self.customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": "KYC Verify Customer",
            "email": "kyc-verify@example.com",
            "phone": "+1333333333",
        }).insert()

        self.file1 = frappe.get_doc({
            "doctype": "File",
            "file_name": "verify_id.pdf",
            "file_url": "/private/files/verify_id.pdf",
            "is_private": 1,
            "file_size": 512000,
            "content_hash": "abc123",
        }).insert()

    def tearDown(self):
        for name in frappe.get_all("Notification Log", pluck="name"):
            frappe.delete_doc("Notification Log", name, force=True)
        for name in frappe.get_all("KYC Document", pluck="name"):
            frappe.delete_doc("KYC Document", name, force=True)
        for name in frappe.get_all("File", pluck="name"):
            frappe.delete_doc("File", name, force=True)
        for name in frappe.get_all("Customer", pluck="name"):
            if name != self.customer.name:
                frappe.delete_doc("Customer", name, force=True)

    # ── Helpers ──

    def _create_pending_doc(self, document_type="ID Proof", customer=None):
        """Create a KYC document in Pending Review status."""
        c = customer or self.customer
        result = upload_kyc_document(c.name, document_type, self.file1.file_url)
        return result["kyc_document"]["name"]

    # ── Verification Queue Tests ──

    def test_queue_returns_pending_docs_sorted_by_date(self):
        """Queue returns pending documents sorted by upload_date ascending."""
        doc1 = self._create_pending_doc("ID Proof")
        doc2 = self._create_pending_doc("Driving License")

        result = get_kyc_verification_queue()
        self.assertEqual(result["status"], "success")
        self.assertGreaterEqual(len(result["documents"]), 2)

        # Verify order: oldest first
        dates = [d.uploaded_date for d in result["documents"]]
        self.assertEqual(dates, sorted(dates))

    def test_queue_excludes_non_pending(self):
        """Queue excludes Verified and Rejected documents."""
        doc_name = self._create_pending_doc("ID Proof")
        approve_kyc_document(doc_name)

        result = get_kyc_verification_queue()
        for d in result["documents"]:
            self.assertNotEqual(d.name, doc_name)

    def test_queue_includes_customer_name(self):
        """Each queue entry includes the resolved customer name."""
        self._create_pending_doc("ID Proof")
        result = get_kyc_verification_queue()
        self.assertGreater(len(result["documents"]), 0)
        for d in result["documents"]:
            self.assertTrue(hasattr(d, "customer_name"))
            self.assertIsNotNone(d.customer_name)

    # ── Approve Tests ──

    def test_approve_sets_verified_with_reviewer_info(self):
        """Approve sets status=Verified, reviewed_by, and review_date."""
        doc_name = self._create_pending_doc("ID Proof")

        result = approve_kyc_document(doc_name)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["kyc_document"]["status"], "Verified")
        self.assertIsNotNone(result["kyc_document"]["reviewed_by"])
        self.assertIsNotNone(result["kyc_document"]["review_date"])

        doc = frappe.get_doc("KYC Document", doc_name)
        self.assertEqual(doc.status, "Verified")
        self.assertIsNotNone(doc.reviewed_by)
        self.assertIsNotNone(doc.review_date)

    def test_approve_updates_customer_kyc_status_when_all_verified(self):
        """Customer kyc_status becomes Verified when all docs are approved."""
        doc_name = self._create_pending_doc("ID Proof")
        approve_kyc_document(doc_name)

        kyc_status = frappe.db.get_value("Customer", self.customer.name, "kyc_status")
        self.assertEqual(kyc_status, "Verified")

    def test_approve_customer_stays_pending_with_mixed_statuses(self):
        """Customer stays Pending Review when some docs remain unverified."""
        file2 = frappe.get_doc({
            "doctype": "File",
            "file_name": "verify_license.pdf",
            "file_url": "/private/files/verify_license.pdf",
            "is_private": 1,
            "file_size": 256000,
            "content_hash": "def456",
        }).insert()

        doc1 = self._create_pending_doc("ID Proof")
        upload_kyc_document(self.customer.name, "Driving License", file2.file_url)

        approve_kyc_document(doc1)

        kyc_status = frappe.db.get_value("Customer", self.customer.name, "kyc_status")
        self.assertEqual(kyc_status, "Pending Review")

    def test_approve_creates_notification(self):
        """Approve creates a Notification Log for the customer."""
        doc_name = self._create_pending_doc("ID Proof")
        approve_kyc_document(doc_name)

        notifications = frappe.get_all(
            "Notification Log",
            filters={
                "for_user": "kyc-verify@example.com",
                "document_name": doc_name,
            },
            fields=["subject"],
        )
        self.assertGreater(len(notifications), 0)
        self.assertIn("approved", notifications[0].subject.lower())

    def test_approve_verified_complete_notification(self):
        """Approve creates a 'verification complete' notification when all docs verified."""
        doc_name = self._create_pending_doc("ID Proof")
        approve_kyc_document(doc_name)

        notifications = frappe.get_all(
            "Notification Log",
            filters={
                "for_user": "kyc-verify@example.com",
                "document_type": "Customer",
            },
            fields=["subject"],
        )
        self.assertGreater(len(notifications), 0)
        self.assertIn("complete", notifications[0].subject.lower())

    def test_approve_already_approved_raises_error(self):
        """Approving an already-approved document raises an error."""
        doc_name = self._create_pending_doc("ID Proof")
        approve_kyc_document(doc_name)

        with self.assertRaises(frappe.ValidationError):
            approve_kyc_document(doc_name)

    # ── Reject Tests ──

    def test_reject_sets_rejected_with_reason(self):
        """Reject sets status=Rejected with rejection_reason and reviewer info."""
        doc_name = self._create_pending_doc("ID Proof")

        result = reject_kyc_document(doc_name, "Document is blurry")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["kyc_document"]["status"], "Rejected")
        self.assertEqual(result["kyc_document"]["rejection_reason"], "Document is blurry")

        doc = frappe.get_doc("KYC Document", doc_name)
        self.assertEqual(doc.status, "Rejected")
        self.assertEqual(doc.rejection_reason, "Document is blurry")
        self.assertIsNotNone(doc.reviewed_by)
        self.assertIsNotNone(doc.review_date)

    def test_reject_validates_reason_required(self):
        """Reject with empty reason raises ValidationError."""
        doc_name = self._create_pending_doc("ID Proof")

        with self.assertRaises(frappe.ValidationError):
            reject_kyc_document(doc_name, "")

        with self.assertRaises(frappe.ValidationError):
            reject_kyc_document(doc_name, "   ")

        with self.assertRaises(frappe.ValidationError):
            reject_kyc_document(doc_name, None)

    def test_reject_creates_notification(self):
        """Reject creates a Notification Log with rejection reason."""
        doc_name = self._create_pending_doc("ID Proof")
        reject_kyc_document(doc_name, "Illegible text")

        notifications = frappe.get_all(
            "Notification Log",
            filters={
                "for_user": "kyc-verify@example.com",
                "document_name": doc_name,
            },
            fields=["subject", "email_content"],
        )
        self.assertGreater(len(notifications), 0)
        self.assertIn("rejected", notifications[0].subject.lower())
        self.assertIn("Illegible text", notifications[0].email_content)

    def test_reject_updates_customer_kyc_status(self):
        """Customer kyc_status becomes Rejected when all docs are rejected."""
        doc_name = self._create_pending_doc("ID Proof")
        reject_kyc_document(doc_name, "Blurry photo")

        kyc_status = frappe.db.get_value("Customer", self.customer.name, "kyc_status")
        self.assertEqual(kyc_status, "Rejected")

    def test_reject_already_rejected_raises_error(self):
        """Rejecting an already-rejected document raises an error."""
        doc_name = self._create_pending_doc("ID Proof")
        reject_kyc_document(doc_name, "Blurry")

        with self.assertRaises(frappe.ValidationError):
            reject_kyc_document(doc_name, "Still blurry")

    # ── Re-upload After Rejection ──

    def test_reupload_after_rejection_allowed(self):
        """Customer can upload a new document after rejection (duplicate check allows)."""
        doc_name = self._create_pending_doc("ID Proof")
        reject_kyc_document(doc_name, "Blurry image")

        file2 = frappe.get_doc({
            "doctype": "File",
            "file_name": "reupload_id.pdf",
            "file_url": "/private/files/reupload_id.pdf",
            "is_private": 1,
            "file_size": 256000,
            "content_hash": "ghi789",
        }).insert()

        result = upload_kyc_document(self.customer.name, "ID Proof", file2.file_url)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["kyc_document"]["document_type"], "ID Proof")
        self.assertEqual(result["kyc_document"]["status"], "Pending Review")

    def test_reupload_resets_customer_kyc_status_to_pending(self):
        """After rejection + re-upload, customer kyc_status becomes Pending Review."""
        doc_name = self._create_pending_doc("ID Proof")
        reject_kyc_document(doc_name, "Blurry")

        file2 = frappe.get_doc({
            "doctype": "File",
            "file_name": "reupload2_id.pdf",
            "file_url": "/private/files/reupload2_id.pdf",
            "is_private": 1,
            "file_size": 256000,
            "content_hash": "jkl012",
        }).insert()

        upload_kyc_document(self.customer.name, "ID Proof", file2.file_url)

        kyc_status = frappe.db.get_value("Customer", self.customer.name, "kyc_status")
        self.assertEqual(kyc_status, "Pending Review")

    def test_approve_reuploaded_document_after_rejection(self):
        """After reject + re-upload + approve, customer kyc_status becomes Verified."""
        # First upload gets rejected
        doc_name = self._create_pending_doc("ID Proof")
        reject_kyc_document(doc_name, "Blurry")

        # Re-upload
        file2 = frappe.get_doc({
            "doctype": "File",
            "file_name": "reupload_approve.pdf",
            "file_url": "/private/files/reupload_approve.pdf",
            "is_private": 1,
            "file_size": 512000,
            "content_hash": "new789",
        }).insert()

        result = upload_kyc_document(self.customer.name, "ID Proof", file2.file_url)
        new_doc_name = result["kyc_document"]["name"]

        # Approve the re-uploaded document
        approve_result = approve_kyc_document(new_doc_name)
        self.assertEqual(approve_result["status"], "success")
        self.assertEqual(approve_result["kyc_document"]["status"], "Verified")

        # Customer status should be Verified (old rejected doc is superseded)
        kyc_status = frappe.db.get_value("Customer", self.customer.name, "kyc_status")
        self.assertEqual(kyc_status, "Verified")

    # ── KYC Status Rollup Tests ──

    def test_rollup_pending_when_mixed(self):
        """One Verified + one Pending Review = customer Pending Review."""
        file2 = frappe.get_doc({
            "doctype": "File",
            "file_name": "rollup_license.pdf",
            "file_url": "/private/files/rollup_license.pdf",
            "is_private": 1,
            "file_size": 256000,
            "content_hash": "mno345",
        }).insert()

        doc1 = self._create_pending_doc("ID Proof")
        upload_kyc_document(self.customer.name, "Driving License", file2.file_url)

        approve_kyc_document(doc1)

        kyc_status = frappe.db.get_value("Customer", self.customer.name, "kyc_status")
        self.assertEqual(kyc_status, "Pending Review")

    def test_rollup_all_verified(self):
        """All Verified = customer Verified."""
        doc1 = self._create_pending_doc("ID Proof")
        approve_kyc_document(doc1)
        kyc_status = frappe.db.get_value("Customer", self.customer.name, "kyc_status")
        self.assertEqual(kyc_status, "Verified")

    def test_rollup_rejected_no_pending(self):
        """Rejected with no Pending docs = customer Rejected."""
        doc1 = self._create_pending_doc("ID Proof")
        reject_kyc_document(doc1, "Blurry")
        kyc_status = frappe.db.get_value("Customer", self.customer.name, "kyc_status")
        self.assertEqual(kyc_status, "Rejected")

    # ── Non-staff Access Tests ──

    def test_queue_returns_success_for_staff(self):
        """get_kyc_verification_queue returns success for staff users (System Manager)."""
        result = get_kyc_verification_queue()
        self.assertEqual(result["status"], "success")

    # ── Document Existence Tests ──

    def test_approve_nonexistent_document(self):
        """Approving a nonexistent document raises an error."""
        with self.assertRaises(frappe.ValidationError):
            approve_kyc_document("NONEXISTENT-DOC")

    def test_reject_nonexistent_document(self):
        """Rejecting a nonexistent document raises an error."""
        with self.assertRaises(frappe.ValidationError):
            reject_kyc_document("NONEXISTENT-DOC", "Test reason")
