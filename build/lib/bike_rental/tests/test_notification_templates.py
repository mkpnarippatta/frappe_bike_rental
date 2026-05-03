from __future__ import unicode_literals

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime, add_to_date

from bike_rental.notification.queue import (
    enqueue_notification,
    _render_template,
    _handle_delivery_failure,
)
from bike_rental.notification.business_hours import (
    is_business_hour,
    next_business_hour_datetime,
    is_critical_event,
    enqueue_with_business_hours,
)
from bike_rental.notification.event_handlers import (
    on_booking_confirmed,
    on_kyc_status_change,
    on_payment_receipt,
)


class TestNotificationTemplates(FrappeTestCase):
    """Tests for notification templates, business hours, and event handlers (Story 5.2)."""

    def tearDown(self):
        for name in frappe.get_all("Notification Queue", pluck="name"):
            frappe.delete_doc("Notification Queue", name, force=True)
        for name in frappe.get_all("Notification Template", pluck="name"):
            frappe.delete_doc("Notification Template", name, force=True)
        for name in frappe.get_all("Notification Log", pluck="name"):
            frappe.delete_doc("Notification Log", name, force=True)

    # ── Template Rendering ──

    def test_render_file_template_with_variables(self):
        """File-based .j2 template renders with variables."""
        subject, message = _render_template(
            "booking_confirmation", "Email",
            {"customer_name": "John", "booking_id": "B-001", "hub_name": "Downtown Hub",
             "model_name": "City Cruiser", "start_date": "2026-05-03", "start_time": "10:00",
             "end_date": "2026-05-04", "end_time": "10:00", "amount": "50"},
        )
        self.assertIn("John", subject)
        self.assertIn("B-001", message)
        self.assertIn("Downtown Hub", message)

    def test_render_file_template_missing_variables(self):
        """Missing variables render as blank, no crash."""
        subject, message = _render_template(
            "booking_confirmation", "Email",
            {"customer_name": "John"},
        )
        self.assertIn("John", subject)
        # Other variables like {{ booking_id }} render as blank — should not crash

    def test_render_template_fallback_to_variables(self):
        """Non-existent template file falls back to variables defaults."""
        subject, message = _render_template(
            "nonexistent_template", "Email",
            {"subject": "Custom Subject", "message": "Custom Body"},
        )
        self.assertEqual(subject, "Custom Subject")
        self.assertEqual(message, "Custom Body")

    def test_render_kyc_template(self):
        """KYC template renders with KYC-specific variables."""
        subject, message = _render_template(
            "kyc_status_change", "Email",
            {"customer_name": "Jane", "kyc_status": "Verified"},
        )
        self.assertIn("Jane", subject)
        self.assertIn("Verified", message)

    def test_render_sms_template(self):
        """SMS template renders correctly."""
        subject, message = _render_template(
            "booking_confirmation", "SMS",
            {"customer_name": "John", "booking_id": "B-001", "hub_name": "Downtown Hub",
             "start_date": "2026-05-03", "start_time": "10:00",
             "end_date": "2026-05-04", "end_time": "10:00"},
        )
        self.assertIn("John", message)
        self.assertEqual(subject, "Booking Confirmed")

    # ── Business Hours ──

    def test_is_business_hour_during(self):
        """10 AM is a business hour."""
        dt = now_datetime().replace(hour=10, minute=0)
        self.assertTrue(is_business_hour(dt))

    def test_is_business_hour_before(self):
        """5 AM is not a business hour."""
        dt = now_datetime().replace(hour=5, minute=0)
        self.assertFalse(is_business_hour(dt))

    def test_is_business_hour_after(self):
        """11 PM is not a business hour."""
        dt = now_datetime().replace(hour=23, minute=0)
        self.assertFalse(is_business_hour(dt))

    def test_next_business_hour_during(self):
        """During business hours, next_business_hour returns dt unchanged."""
        dt = now_datetime().replace(hour=14, minute=30)
        result = next_business_hour_datetime(dt)
        self.assertEqual(result, dt)

    def test_next_business_hour_before(self):
        """Before 7 AM, next_business_hour returns 7 AM same day."""
        dt = now_datetime().replace(hour=5, minute=0)
        result = next_business_hour_datetime(dt)
        self.assertEqual(result.hour, 7)
        self.assertEqual(result.minute, 0)

    def test_next_business_hour_after(self):
        """After 10 PM, next_business_hour returns 7 AM next day."""
        dt = now_datetime().replace(hour=23, minute=0)
        result = next_business_hour_datetime(dt)
        self.assertEqual(result.hour, 7)
        self.assertEqual(result.minute, 0)
        self.assertNotEqual(result.date(), dt.date())

    def test_is_critical_event(self):
        """KYC Status Change and Payment Receipt are critical."""
        self.assertTrue(is_critical_event("KYC Status Change"))
        self.assertTrue(is_critical_event("Payment Receipt"))
        self.assertFalse(is_critical_event("Booking Confirmation"))
        self.assertFalse(is_critical_event("Check-Out Reminder"))

    def test_enqueue_during_business_hours(self):
        """Enqueue during business hours processes immediately."""
        name = enqueue_with_business_hours(
            "Booking Confirmation", "test@example.com", "Email",
            variables={"subject": "Test", "message": "Test"},
        )
        entry = frappe.get_doc("Notification Queue", name)
        self.assertEqual(entry.status, "Queued")
        # next_retry_at should be NULL (immediate processing)
        self.assertIsNone(entry.next_retry_at)

    def test_critical_event_outside_hours(self):
        """Critical events are enqueued immediately even outside business hours."""
        name = enqueue_with_business_hours(
            "KYC Status Change", "test@example.com", "Email",
            variables={"subject": "Critical", "message": "Test"},
        )
        entry = frappe.get_doc("Notification Queue", name)
        self.assertEqual(entry.status, "Queued")
        self.assertIsNone(entry.next_retry_at)

    # ── DocType Template Lookup ──

    def test_doc_template_override(self):
        """Notification Template DocType overrides file-based template."""
        template = frappe.get_doc({
            "doctype": "Notification Template",
            "event": "Booking Confirmation",
            "channel": "Email",
            "subject": "Custom: {{ customer_name }}",
            "message": "Hello {{ customer_name }}, your booking {{ booking_id }} is confirmed!",
            "enabled": 1,
        })
        template.insert(ignore_permissions=True)

        subject, message = _render_template(
            "Booking Confirmation", "Email",
            {"customer_name": "Alice", "booking_id": "B-999"},
        )
        self.assertEqual(subject, "Custom: Alice")
        self.assertIn("B-999", message)

    def test_doc_template_hub_specific(self):
        """Hub-specific Notification Template overrides system default."""
        # System default
        frappe.get_doc({
            "doctype": "Notification Template",
            "event": "Booking Confirmation",
            "channel": "Email",
            "subject": "Default: {{ customer_name }}",
            "message": "Default message",
            "enabled": 1,
        }).insert(ignore_permissions=True)

        # Hub-specific (for some hub)
        frappe.get_doc({
            "doctype": "Notification Template",
            "event": "Booking Confirmation",
            "channel": "Email",
            "hub": "Downtown Hub",
            "subject": "Hub: {{ customer_name }}",
            "message": "Hub-specific message",
            "enabled": 1,
        }).insert(ignore_permissions=True)

        # With hub specified — should use hub-specific
        subject, message = _render_template(
            "Booking Confirmation", "Email",
            {"customer_name": "Bob", "booking_id": "B-888"},
            hub="Downtown Hub",
        )
        self.assertEqual(subject, "Hub: Bob")

        # Without hub — should use system default
        subject, message = _render_template(
            "Booking Confirmation", "Email",
            {"customer_name": "Bob", "booking_id": "B-888"},
        )
        self.assertEqual(subject, "Default: Bob")

    def test_doc_template_fallback_chain(self):
        """Fallback: hub template -> system default -> file -> variables."""
        # No DocType template — falls through to file-based
        subject, message = _render_template(
            "booking_confirmation", "Email",
            {"customer_name": "Charlie", "booking_id": "B-777",
             "hub_name": "Test Hub", "model_name": "Model",
             "start_date": "2026-05-03", "start_time": "10:00",
             "end_date": "2026-05-04", "end_time": "10:00", "amount": "30"},
        )
        self.assertIn("Charlie", message)

    # ── Queue Fixes: error_log ──

    def test_error_log_single_entry(self):
        """Error log stores a single entry correctly."""
        name = enqueue_notification("test@test.com", "In-App", variables={"subject": "Err"})
        _handle_delivery_failure(name, "Connection error")

        entry = frappe.get_doc("Notification Queue", name)
        log = json.loads(entry.error_log)
        self.assertIsInstance(log, list)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["attempt"], 1)
        self.assertEqual(log[0]["error"], "Connection error")

    def test_error_log_multiple_entries(self):
        """Error log appends entries on subsequent failures."""
        name = enqueue_notification("test@test.com", "In-App", variables={"subject": "MultiErr"})

        _handle_delivery_failure(name, "Error 1")
        _handle_delivery_failure(name, "Error 2")
        _handle_delivery_failure(name, "Error 3")

        entry = frappe.get_doc("Notification Queue", name)
        log = json.loads(entry.error_log)
        self.assertEqual(len(log), 3)
        self.assertEqual(log[0]["attempt"], 1)
        self.assertEqual(log[1]["attempt"], 2)
        self.assertEqual(log[2]["attempt"], 3)

    # ── Queue Fixes: channel validation ──

    def test_enqueue_disabled_channel_raises(self):
        """Enqueue with a disabled channel raises ValidationError."""
        # Disable SMS channel in settings
        settings = frappe.get_single("Rental Notification Settings")
        settings.enable_sms_channel = 0
        settings.save(ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError):
            enqueue_notification("+1234567890", "SMS", variables={"subject": "Test"})

        # Re-enable
        settings.enable_sms_channel = 1
        settings.save(ignore_permissions=True)

    # ── Event Handlers ──

    def test_event_handler_creates_queue_entry(self):
        """Event handlers create notification queue entries."""
        from frappe.utils import getdate

        # Create a minimal mock booking
        class MockBooking:
            name = "B-001"
            customer = "C-001"
            hub = "Downtown Hub"
            bike_model = "City Cruiser"
            customer_name = "John Doe"
            start_date = getdate()
            end_date = getdate()
            start_time = None
            end_time = None
            total_amount = 100.0

        with patch.object(type(frappe), "get_cached_doc") as mock_get_doc:
            mock_customer = frappe._dict(
                customer_name="John Doe",
                email="john@test.com",
                phone="+1234567890",
            )
            mock_get_doc.return_value = mock_customer

            on_booking_confirmed(MockBooking())

        entries = frappe.get_all(
            "Notification Queue",
            filters={"recipient": "john@test.com"},
            fields=["channel", "subject"],
        )
        self.assertGreater(len(entries), 0)
        channels = {e.channel for e in entries}
        self.assertIn("Email", channels)

    def test_payment_receipt_handler(self):
        """Payment receipt handler creates queue entry."""
        class MockBooking:
            name = "B-002"
            customer = "C-001"
            hub = "Downtown Hub"
            total_amount = 75.0

        with patch.object(type(frappe), "get_cached_doc") as mock_get_doc:
            mock_customer = frappe._dict(
                customer_name="Jane",
                email="jane@test.com",
                phone=None,
            )
            mock_get_doc.return_value = mock_customer

            on_payment_receipt(MockBooking(), 75.0, "Card")

        entries = frappe.get_all(
            "Notification Queue",
            filters={"reference_docname": "B-002"},
            pluck="recipient",
        )
        self.assertIn("jane@test.com", entries)
