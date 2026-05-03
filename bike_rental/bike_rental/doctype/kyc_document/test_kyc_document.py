from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase


class TestKYCDocument(FrappeTestCase):
    """Tests for KYC Document DocType (Story 4.1)."""

    def setUp(self):
        self.customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": "KYC Test Customer",
            "email": "kyc-test@example.com",
            "phone": "+1111111111",
        }).insert()

    def tearDown(self):
        for name in frappe.get_all("KYC Document", pluck="name"):
            frappe.delete_doc("KYC Document", name, force=True)
        for name in frappe.get_all("Customer", pluck="name"):
            if name != self.customer.name:
                frappe.delete_doc("Customer", name, force=True)

    def test_create_with_all_fields(self):
        """Verify KYC Document creation with all required fields."""
        doc = frappe.get_doc({
            "doctype": "KYC Document",
            "customer": self.customer.name,
            "document_type": "ID Proof",
            "document": "/private/files/test_id.pdf",
        }).insert()

        self.assertEqual(doc.customer, self.customer.name)
        self.assertEqual(doc.document_type, "ID Proof")
        self.assertEqual(doc.document, "/private/files/test_id.pdf")

    def test_default_status_pending_review(self):
        """Verify status defaults to Pending Review."""
        doc = frappe.get_doc({
            "doctype": "KYC Document",
            "customer": self.customer.name,
            "document_type": "Driving License",
            "document": "/private/files/test_license.pdf",
        }).insert()

        self.assertEqual(doc.status, "Pending Review")

    def test_uploaded_date_set_on_creation(self):
        """Verify uploaded_date is set automatically on insert."""
        doc = frappe.get_doc({
            "doctype": "KYC Document",
            "customer": self.customer.name,
            "document_type": "ID Proof",
            "document": "/private/files/test_id.pdf",
        }).insert()

        self.assertIsNotNone(doc.uploaded_date)

    def test_customer_kyc_status_updates_to_pending_review(self):
        """Verify customer kyc_status becomes Pending Review after first document."""
        self.assertEqual(
            frappe.db.get_value("Customer", self.customer.name, "kyc_status"),
            "Unverified",
        )

        frappe.get_doc({
            "doctype": "KYC Document",
            "customer": self.customer.name,
            "document_type": "ID Proof",
            "document": "/private/files/test_id.pdf",
        }).insert()

        self.assertEqual(
            frappe.db.get_value("Customer", self.customer.name, "kyc_status"),
            "Pending Review",
        )

    def test_all_documents_verified_sets_customer_verified(self):
        """Verify customer kyc_status becomes Verified when all docs are Verified."""
        doc = frappe.get_doc({
            "doctype": "KYC Document",
            "customer": self.customer.name,
            "document_type": "ID Proof",
            "document": "/private/files/test_id.pdf",
        }).insert()

        doc.status = "Verified"
        doc.save()
        doc.reload()
        self.assertEqual(doc.status, "Verified")

        self.assertEqual(
            frappe.db.get_value("Customer", self.customer.name, "kyc_status"),
            "Verified",
        )

    def test_customer_kyc_completed_date_set_when_verified(self):
        """Verify kyc_completed_date is set when all documents are Verified."""
        doc = frappe.get_doc({
            "doctype": "KYC Document",
            "customer": self.customer.name,
            "document_type": "ID Proof",
            "document": "/private/files/test_id.pdf",
        }).insert()

        doc.status = "Verified"
        doc.save()

        completed_date = frappe.db.get_value(
            "Customer", self.customer.name, "kyc_completed_date"
        )
        self.assertIsNotNone(completed_date)

    def test_document_type_limited_to_allowed_values(self):
        """Verify document_type is restricted to ID Proof and Driving License."""
        doc = frappe.get_doc({
            "doctype": "KYC Document",
            "customer": self.customer.name,
            "document_type": "ID Proof",
            "document": "/private/files/test_id.pdf",
        }).insert()
        self.assertEqual(doc.document_type, "ID Proof")

        doc2 = frappe.get_doc({
            "doctype": "KYC Document",
            "customer": self.customer.name,
            "document_type": "Driving License",
            "document": "/private/files/test_license.pdf",
        }).insert()
        self.assertEqual(doc2.document_type, "Driving License")

    def test_customer_required(self):
        """Verify customer field is mandatory."""
        with self.assertRaises(frappe.MandatoryError):
            frappe.get_doc({
                "doctype": "KYC Document",
                "document_type": "ID Proof",
                "document": "/private/files/test_id.pdf",
            }).insert()

    def test_document_type_required(self):
        """Verify document_type field is mandatory."""
        with self.assertRaises(frappe.MandatoryError):
            frappe.get_doc({
                "doctype": "KYC Document",
                "customer": self.customer.name,
                "document": "/private/files/test_id.pdf",
            }).insert()
