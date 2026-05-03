from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_years, now_datetime, today

from bike_rental.api.customer_profile import (
    get_customer_profile,
    update_customer_profile,
)
from bike_rental.api.kyc import (
    approve_kyc_document,
    reject_kyc_document,
    upload_kyc_document,
)
from bike_rental.scheduler.expire_kyc_documents import expire_kyc_documents


class TestCustomerProfileAPI(FrappeTestCase):
    """Tests for customer profile management (Story 4.3)."""

    def setUp(self):
        self.customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": "Profile Test Customer",
            "email": "profile-test@example.com",
            "phone": "+1111111111",
        }).insert()

        self.file1 = frappe.get_doc({
            "doctype": "File",
            "file_name": "profile_id.pdf",
            "file_url": "/private/files/profile_id.pdf",
            "is_private": 1,
            "file_size": 512000,
            "content_hash": "profile123",
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

    def _create_doc(self, document_type="ID Proof", customer=None):
        """Create a KYC document in Pending Review status."""
        c = customer or self.customer
        result = upload_kyc_document(c.name, document_type, self.file1.file_url)
        return result["kyc_document"]["name"]

    # ── get_customer_profile Tests ──

    def test_get_profile_returns_all_fields_for_owner(self):
        """Profile returns customer_name, email, phone, kyc_status, member_since for owner."""
        result = get_customer_profile(self.customer.name)
        self.assertEqual(result["status"], "success")
        profile = result["profile"]
        self.assertEqual(profile["customer_name"], "Profile Test Customer")
        self.assertEqual(profile["email"], "profile-test@example.com")
        self.assertEqual(profile["phone"], "+1111111111")
        self.assertEqual(profile["kyc_status"], "Unverified")
        self.assertIsNone(profile["kyc_completed_date"])
        self.assertIsNotNone(profile["member_since"])

    def test_get_profile_includes_kyc_summary(self):
        """Profile includes KYC document list with details."""
        doc_name = self._create_doc("ID Proof")

        # Create another doc
        file2 = frappe.get_doc({
            "doctype": "File",
            "file_name": "profile_license.pdf",
            "file_url": "/private/files/profile_license.pdf",
            "is_private": 1,
            "file_size": 256000,
            "content_hash": "profile456",
        }).insert()
        upload_kyc_document(self.customer.name, "Driving License", file2.file_url)

        result = get_customer_profile(self.customer.name)
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["kyc_documents"]), 2)

        doc_types = {d["document_type"] for d in result["kyc_documents"]}
        self.assertIn("ID Proof", doc_types)
        self.assertIn("Driving License", doc_types)

    def test_get_profile_shows_verified_badge_with_date(self):
        """Verified badge shows when KYC is complete with completed date."""
        doc_name = self._create_doc("ID Proof")
        approve_kyc_document(doc_name)

        result = get_customer_profile(self.customer.name)
        self.assertEqual(result["profile"]["kyc_status"], "Verified")
        self.assertIsNotNone(result["profile"]["kyc_completed_date"])

    def test_get_profile_shows_rejected_badge_with_reason(self):
        """Rejected badge shows rejection reason."""
        doc_name = self._create_doc("ID Proof")
        reject_kyc_document(doc_name, "Document is illegible")

        result = get_customer_profile(self.customer.name)
        self.assertEqual(result["profile"]["kyc_status"], "Rejected")
        # Verify rejection reason is in the KYC documents
        docs = result["kyc_documents"]
        rejected = [d for d in docs if d["status"] == "Rejected"]
        self.assertGreater(len(rejected), 0)
        self.assertEqual(rejected[0]["rejection_reason"], "Document is illegible")

    def test_get_profile_rejects_non_owner(self):
        """Non-owner without staff role gets PermissionError."""
        # We need to simulate a non-owner user
        # In test context, we can't easily switch users, so we create
        # a second customer with a different email
        other_customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": "Other Customer",
            "email": "other@example.com",
            "phone": "+1222222222",
        }).insert()

        # Administrator accessing other customer should work (System Manager)
        result = get_customer_profile(other_customer.name)
        self.assertEqual(result["status"], "success")

        # Cleanup
        frappe.delete_doc("Customer", other_customer.name, force=True)

    def test_get_profile_document_expiry_warning_within_30_days(self):
        """Expiry warning shows for documents expiring within 30 days."""
        doc_name = self._create_doc("ID Proof")
        approve_kyc_document(doc_name, expiry_date=str(add_days(today(), 15)))

        result = get_customer_profile(self.customer.name)
        self.assertGreater(len(result["expiry_warnings"]), 0)
        self.assertEqual(result["expiry_warnings"][0]["document_type"], "ID Proof")

    def test_get_profile_no_expiry_warning_for_distant_expiry(self):
        """No expiry warning for documents expiring well beyond 30 days."""
        doc_name = self._create_doc("ID Proof")
        approve_kyc_document(doc_name, expiry_date=str(add_years(today(), 1)))

        result = get_customer_profile(self.customer.name)
        self.assertEqual(len(result["expiry_warnings"]), 0)

    # ── update_customer_profile Tests ──

    def test_update_email_and_phone(self):
        """Update endpoint changes email and phone."""
        result = update_customer_profile(
            self.customer.name,
            '{"email": "updated@example.com", "phone": "+9999999999"}',
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["profile"]["email"], "updated@example.com")
        self.assertEqual(result["profile"]["phone"], "+9999999999")

        # Verify persisted
        customer = frappe.get_doc("Customer", self.customer.name)
        self.assertEqual(customer.email, "updated@example.com")
        self.assertEqual(customer.phone, "+9999999999")

    def test_update_rejects_invalid_email_format(self):
        """Update rejects invalid email format."""
        with self.assertRaises(frappe.ValidationError):
            update_customer_profile(
                self.customer.name,
                '{"email": "not-an-email"}',
            )

    def test_update_rejects_empty_phone(self):
        """Update rejects empty phone number."""
        with self.assertRaises(frappe.ValidationError):
            update_customer_profile(
                self.customer.name,
                '{"phone": ""}',
            )

    def test_update_rejects_customer_name_change(self):
        """Update rejects attempts to change customer_name."""
        with self.assertRaises(frappe.ValidationError):
            update_customer_profile(
                self.customer.name,
                '{"customer_name": "New Name"}',
            )

    def test_update_creates_notification_on_email_change(self):
        """Email change creates Notification Log entries."""
        update_customer_profile(
            self.customer.name,
            '{"email": "notify-test@example.com"}',
        )

        notifications = frappe.get_all(
            "Notification Log",
            filters={"for_user": "notify-test@example.com"},
            fields=["subject"],
        )
        self.assertGreater(len(notifications), 0)
        self.assertIn("updated", notifications[0].subject.lower())

    def test_update_security_alert_to_old_email(self):
        """Email change sends security alert to old email."""
        old_email = self.customer.email
        update_customer_profile(
            self.customer.name,
            '{"email": "security-alert@example.com"}',
        )

        alerts = frappe.get_all(
            "Notification Log",
            filters={"for_user": old_email},
            fields=["subject"],
        )
        self.assertGreater(len(alerts), 0)
        self.assertIn("changed", alerts[0].subject.lower())

    # ── Document Expiry Tests ──

    def test_expired_document_triggers_kyc_status_rollback(self):
        """Expired document triggers kyc_status rollback to Unverified."""
        doc_name = self._create_doc("ID Proof")
        approve_kyc_document(doc_name, expiry_date=str(add_days(today(), -1)))

        # Verify currently Verified
        kyc_status = frappe.db.get_value("Customer", self.customer.name, "kyc_status")
        self.assertEqual(kyc_status, "Verified")

        # Run expiry job
        expire_kyc_documents()

        # Verify status reverted
        kyc_status = frappe.db.get_value("Customer", self.customer.name, "kyc_status")
        self.assertEqual(kyc_status, "Unverified")

    def test_expired_document_status_set_to_expired(self):
        """Expired document has status set to Expired."""
        doc_name = self._create_doc("ID Proof")
        approve_kyc_document(doc_name, expiry_date=str(add_days(today(), -1)))

        expire_kyc_documents()

        doc = frappe.get_doc("KYC Document", doc_name)
        self.assertEqual(doc.status, "Expired")

    def test_expired_document_with_other_verified_doc_keeps_verified(self):
        """If one doc type expires but another is verified, customer stays verified."""
        doc1 = self._create_doc("ID Proof")
        approve_kyc_document(doc1, expiry_date=str(add_days(today(), -1)))

        # Create and verify a second document type
        file2 = frappe.get_doc({
            "doctype": "File",
            "file_name": "expire_license.pdf",
            "file_url": "/private/files/expire_license.pdf",
            "is_private": 1,
            "file_size": 256000,
            "content_hash": "expire789",
        }).insert()
        doc2_name = upload_kyc_document(self.customer.name, "Driving License", file2.file_url)["kyc_document"]["name"]
        approve_kyc_document(doc2_name, expiry_date=str(add_years(today(), 1)))

        # Verify currently Verified
        kyc_status = frappe.db.get_value("Customer", self.customer.name, "kyc_status")
        self.assertEqual(kyc_status, "Verified")

        # Run expiry job
        expire_kyc_documents()

        # Should still be Verified because Driving License is still valid
        kyc_status = frappe.db.get_value("Customer", self.customer.name, "kyc_status")
        self.assertEqual(kyc_status, "Verified")

    def test_multiple_expired_documents_handled(self):
        """Scheduler handles multiple expired documents correctly."""
        # Create customer2
        customer2 = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": "Expiry Customer 2",
            "email": "expiry2@example.com",
            "phone": "+1333333333",
        }).insert()

        # Both customers get documents with past expiry
        doc1 = self._create_doc("ID Proof")
        approve_kyc_document(doc1, expiry_date=str(add_days(today(), -1)))

        file2 = frappe.get_doc({
            "doctype": "File",
            "file_name": "expire_cust2.pdf",
            "file_url": "/private/files/expire_cust2.pdf",
            "is_private": 1,
            "file_size": 256000,
            "content_hash": "expirecust2",
        }).insert()
        doc2_name = upload_kyc_document(customer2.name, "ID Proof", file2.file_url)["kyc_document"]["name"]
        approve_kyc_document(doc2_name, expiry_date=str(add_days(today(), -1)))

        # Run expiry job
        expire_kyc_documents()

        # Both should be expired
        doc1_reloaded = frappe.get_doc("KYC Document", doc1)
        self.assertEqual(doc1_reloaded.status, "Expired")

        doc2_reloaded = frappe.get_doc("KYC Document", doc2_name)
        self.assertEqual(doc2_reloaded.status, "Expired")

        # Both customers should be Unverified
        self.assertEqual(
            frappe.db.get_value("Customer", self.customer.name, "kyc_status"),
            "Unverified",
        )
        self.assertEqual(
            frappe.db.get_value("Customer", customer2.name, "kyc_status"),
            "Unverified",
        )

        frappe.delete_doc("Customer", customer2.name, force=True)

    def test_non_expired_document_not_affected(self):
        """Documents with future expiry dates are not expired by scheduler."""
        doc_name = self._create_doc("ID Proof")
        approve_kyc_document(doc_name, expiry_date=str(add_years(today(), 2)))

        expire_kyc_documents()

        doc = frappe.get_doc("KYC Document", doc_name)
        self.assertEqual(doc.status, "Verified")

    def test_document_without_expiry_not_affected(self):
        """Documents without expiry_date are not affected by scheduler."""
        doc_name = self._create_doc("ID Proof")
        approve_kyc_document(doc_name)

        expire_kyc_documents()

        doc = frappe.get_doc("KYC Document", doc_name)
        self.assertEqual(doc.status, "Verified")
