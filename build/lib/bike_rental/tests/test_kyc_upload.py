from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase

from bike_rental.api.kyc import upload_kyc_document, get_kyc_documents, get_kyc_status


class TestKYCUploadAPI(FrappeTestCase):
    """Tests for KYC upload/query API endpoints (Story 4.1)."""

    def setUp(self):
        self.customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": "KYC API Customer",
            "email": "kyc-api@example.com",
            "phone": "+1222222222",
        }).insert()

        self.file = frappe.get_doc({
            "doctype": "File",
            "file_name": "test_doc.pdf",
            "file_url": "/private/files/test_doc.pdf",
            "is_private": 1,
            "file_size": 512000,
            "content_hash": "abc123",
        }).insert()

    def tearDown(self):
        for name in frappe.get_all("KYC Document", pluck="name"):
            frappe.delete_doc("KYC Document", name, force=True)
        for name in frappe.get_all("File", pluck="name"):
            frappe.delete_doc("File", name, force=True)
        for name in frappe.get_all("Customer", pluck="name"):
            if name != self.customer.name:
                frappe.delete_doc("Customer", name, force=True)

    def test_upload_valid_document(self):
        """Upload a valid KYC document succeeds."""
        result = upload_kyc_document(
            self.customer.name, "ID Proof", self.file.file_url
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["kyc_document"]["customer"], self.customer.name)
        self.assertEqual(result["kyc_document"]["document_type"], "ID Proof")
        self.assertEqual(result["kyc_document"]["status"], "Pending Review")
        self.assertIn("file_url", result["kyc_document"])

    def test_upload_updates_customer_kyc_status(self):
        """Upload sets customer kyc_status to Pending Review."""
        upload_kyc_document(
            self.customer.name, "ID Proof", self.file.file_url
        )

        kyc_status = frappe.db.get_value(
            "Customer", self.customer.name, "kyc_status"
        )
        self.assertEqual(kyc_status, "Pending Review")

    def test_upload_invalid_customer(self):
        """Upload with nonexistent customer is rejected."""
        with self.assertRaises(frappe.ValidationError):
            upload_kyc_document(
                "NONEXISTENT-CUSTOMER", "ID Proof", self.file.file_url
            )

    def test_upload_invalid_document_type(self):
        """Upload with invalid document_type is rejected."""
        with self.assertRaises(frappe.ValidationError):
            upload_kyc_document(
                self.customer.name, "Passport", self.file.file_url
            )

    def test_upload_nonexistent_file(self):
        """Upload with nonexistent file URL is rejected."""
        with self.assertRaises(frappe.ValidationError):
            upload_kyc_document(
                self.customer.name,
                "ID Proof",
                "/private/files/nonexistent.pdf",
            )

    def test_get_documents_returns_all_for_customer(self):
        """get_kyc_documents returns all KYC documents for the customer."""
        upload_kyc_document(
            self.customer.name, "ID Proof", self.file.file_url
        )

        result = get_kyc_documents(self.customer.name)
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["documents"]), 1)
        self.assertEqual(result["documents"][0]["document_type"], "ID Proof")
        self.assertEqual(result["documents"][0]["status"], "Pending Review")

    def test_get_documents_multiple_docs(self):
        """get_kyc_documents returns multiple documents."""
        file2 = frappe.get_doc({
            "doctype": "File",
            "file_name": "test_license.pdf",
            "file_url": "/private/files/test_license.pdf",
            "is_private": 1,
            "file_size": 256000,
            "content_hash": "def456",
        }).insert()

        upload_kyc_document(self.customer.name, "ID Proof", self.file.file_url)
        upload_kyc_document(
            self.customer.name, "Driving License", file2.file_url
        )

        result = get_kyc_documents(self.customer.name)
        self.assertEqual(len(result["documents"]), 2)

    def test_get_status_summary(self):
        """get_kyc_status returns correct summary."""
        upload_kyc_document(
            self.customer.name, "ID Proof", self.file.file_url
        )

        result = get_kyc_status(self.customer.name)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["kyc_status"], "Pending Review")
        self.assertEqual(len(result["documents"]), 1)

    def test_get_status_unverified_when_no_docs(self):
        """get_kyc_status returns Unverified when no documents exist."""
        result = get_kyc_status(self.customer.name)
        self.assertEqual(result["kyc_status"], "Unverified")
        self.assertEqual(result["documents"], [])

    def test_upload_confirmation_message(self):
        """Upload returns confirmation message with expected review timeframe."""
        result = upload_kyc_document(
            self.customer.name, "ID Proof", self.file.file_url
        )

        self.assertIn("successfully", result["message"].lower())
        self.assertIn("24 hours", result["message"])

    def test_upload_rejects_unsupported_file_extension(self):
        """Upload a file with unsupported extension is rejected."""
        bad_file = frappe.get_doc({
            "doctype": "File",
            "file_name": "test.doc",
            "file_url": "/private/files/test.doc",
            "is_private": 1,
            "file_size": 512000,
            "content_hash": "ghi789",
        }).insert()

        with self.assertRaises(frappe.ValidationError) as ctx:
            upload_kyc_document(
                self.customer.name, "ID Proof", bad_file.file_url
            )
        self.assertIn("format", str(ctx.exception).lower())

    def test_upload_rejects_oversized_file(self):
        """Upload a file exceeding 10MB is rejected."""
        big_file = frappe.get_doc({
            "doctype": "File",
            "file_name": "big_doc.pdf",
            "file_url": "/private/files/big_doc.pdf",
            "is_private": 1,
            "file_size": 15 * 1024 * 1024,
            "content_hash": "jkl012",
        }).insert()

        with self.assertRaises(frappe.ValidationError) as ctx:
            upload_kyc_document(
                self.customer.name, "ID Proof", big_file.file_url
            )
        self.assertIn("10MB", str(ctx.exception))
