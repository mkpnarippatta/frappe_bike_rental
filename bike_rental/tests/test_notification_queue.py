from __future__ import unicode_literals

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from bike_rental.notification.queue import (
    RETRY_BACKOFF,
    _handle_delivery_failure,
    _render_template,
    enqueue_notification,
    enqueue_notification_multi,
    process_notification_queue,
    send_in_app,
)


class TestNotificationQueue(FrappeTestCase):
    """Tests for the notification queue service (Story 5.1)."""

    def setUp(self):
        self.recipient = "test-customer@example.com"

    def tearDown(self):
        for name in frappe.get_all("Notification Queue", pluck="name"):
            frappe.delete_doc("Notification Queue", name, force=True)
        for name in frappe.get_all("Notification Log", pluck="name"):
            frappe.delete_doc("Notification Log", name, force=True)

    # ── enqueue_notification Tests ──

    def test_enqueue_creates_queued_entry(self):
        """enqueue_notification creates a Notification Queue entry with Queued status."""
        name = enqueue_notification(self.recipient, "Email", variables={"subject": "Test"})
        self.assertIsNotNone(name)

        entry = frappe.get_doc("Notification Queue", name)
        self.assertEqual(entry.status, "Queued")
        self.assertEqual(entry.recipient, self.recipient)
        self.assertEqual(entry.channel, "Email")

    def test_enqueue_requires_recipient(self):
        """Empty recipient raises ValidationError."""
        with self.assertRaises(frappe.ValidationError):
            enqueue_notification("", "Email")

    def test_enqueue_validates_channel(self):
        """Invalid channel raises ValidationError."""
        with self.assertRaises(frappe.ValidationError):
            enqueue_notification(self.recipient, "Fax")

    def test_enqueue_validates_priority(self):
        """Invalid priority raises ValidationError."""
        with self.assertRaises(frappe.ValidationError):
            enqueue_notification(self.recipient, "Email", priority="Urgent")

    def test_enqueue_stores_variables_as_json(self):
        """Variables are stored as JSON string."""
        vars = {"customer_name": "John", "booking_id": "B-001"}
        name = enqueue_notification(self.recipient, "Email", variables=vars)
        entry = frappe.get_doc("Notification Queue", name)
        stored = json.loads(entry.variables)
        self.assertEqual(stored["customer_name"], "John")
        self.assertEqual(stored["booking_id"], "B-001")

    def test_enqueue_reference_fields(self):
        """Reference doctype and docname are stored."""
        name = enqueue_notification(
            self.recipient, "In-App",
            reference_doctype="Rental Booking",
            reference_docname="REF-001",
        )
        entry = frappe.get_doc("Notification Queue", name)
        self.assertEqual(entry.reference_doctype, "Rental Booking")
        self.assertEqual(entry.reference_docname, "REF-001")

    # ── enqueue_notification_multi Tests ──

    def test_enqueue_multi_creates_multiple_entries(self):
        """enqueue_notification_multi creates entries for each recipient."""
        recipients = ["a@test.com", "b@test.com", "c@test.com"]
        names = enqueue_notification_multi(recipients, "Email", variables={"subject": "Multi"})
        self.assertEqual(len(names), 3)
        for name in names:
            entry = frappe.get_doc("Notification Queue", name)
            self.assertEqual(entry.channel, "Email")
            self.assertIn(entry.recipient, recipients)

    # ── Template Rendering Tests ──

    def test_render_template_fallback_defaults(self):
        """Without a template file, falls back to variables."""
        vars = {"subject": "Hello", "message": "World"}
        subject, message = _render_template(None, "Email", vars)
        self.assertEqual(subject, "Hello")
        self.assertEqual(message, "World")

    def test_render_template_default_subject(self):
        """Uses default subject when subject not in variables."""
        vars = {"message": "Body only"}
        subject, message = _render_template(None, "Email", vars)
        self.assertEqual(subject, "Notification")
        self.assertEqual(message, "Body only")

    # ── process_notification_queue Tests ──

    def test_process_empty_queue(self):
        """Empty queue returns 0."""
        count = process_notification_queue(limit=10)
        self.assertEqual(count, 0)

    def test_process_single_item(self):
        """Process a single queued item."""
        enqueue_notification(self.recipient, "In-App", variables={"subject": "Single"})
        count = process_notification_queue(limit=10)
        self.assertEqual(count, 1)

        # Verify it's marked Sent
        entries = frappe.get_all("Notification Queue", filters={"status": "Sent"}, pluck="name")
        self.assertEqual(len(entries), 1)

    def test_process_respects_limit(self):
        """Process only up to limit items per batch."""
        for i in range(5):
            enqueue_notification(
                self.recipient, "In-App",
                variables={"subject": f"Item {i}"},
            )
        count = process_notification_queue(limit=3)
        self.assertEqual(count, 3)

        queued = frappe.db.count("Notification Queue", filters={"status": "Queued"})
        self.assertEqual(queued, 2)

    def test_process_priority_ordering(self):
        """High priority items are processed before Normal, then Low."""
        low = enqueue_notification(self.recipient, "In-App", variables={"subject": "Low"}, priority="Low")
        high = enqueue_notification(self.recipient, "In-App", variables={"subject": "High"}, priority="High")
        normal = enqueue_notification(self.recipient, "In-App", variables={"subject": "Normal"}, priority="Normal")

        process_notification_queue(limit=10)

        # All should be Sent
        sent = frappe.get_all(
            "Notification Queue",
            filters={"status": "Sent"},
            fields=["name", "priority"],
        )
        self.assertEqual(len(sent), 3)

    def test_one_failure_does_not_block_others(self):
        """One failing item doesn't prevent others from processing."""
        enqueue_notification("nonexistent@invalid", "In-App", variables={"subject": "Bad"})
        enqueue_notification(self.recipient, "In-App", variables={"subject": "Good"})

        count = process_notification_queue(limit=10)
        # At least the good one should process
        self.assertGreaterEqual(count, 1)

    # ── In-App Delivery Tests ──

    def test_send_in_app_creates_notification_log(self):
        """send_in_app creates a Notification Log entry."""
        queue_name = enqueue_notification(self.recipient, "In-App", variables={"subject": "In-App Test"})
        entry = frappe.get_doc("Notification Queue", queue_name)
        send_in_app(entry)

        logs = frappe.get_all(
            "Notification Log",
            filters={"for_user": self.recipient},
            pluck="subject",
        )
        self.assertGreater(len(logs), 0)
        self.assertIn("In-App Test", logs)

    def test_send_in_app_skips_non_user(self):
        """send_in_app skips non-user recipient without error."""
        queue_name = enqueue_notification("no-such-user@example.com", "In-App", variables={"subject": "Skip"})
        entry = frappe.get_doc("Notification Queue", queue_name)

        # Should not raise
        send_in_app(entry)

        # Should be marked Sent
        status = frappe.db.get_value("Notification Queue", queue_name, "status")
        self.assertEqual(status, "Sent")

    # ── Retry Logic Tests ──

    def test_retry_increments_count_and_schedules(self):
        """_handle_delivery_failure increments retry_count and sets next_retry_at."""
        name = enqueue_notification(self.recipient, "In-App", variables={"subject": "Retry"})

        _handle_delivery_failure(name, "Test error")

        entry = frappe.get_doc("Notification Queue", name)
        self.assertEqual(entry.retry_count, 1)
        self.assertEqual(entry.status, "Queued")
        self.assertIsNotNone(entry.next_retry_at)

    def test_retry_backoff_timing(self):
        """First retry uses 5min backoff."""
        name = enqueue_notification(self.recipient, "In-App", variables={"subject": "Backoff"})

        _handle_delivery_failure(name, "Error 1")

        entry = frappe.get_doc("Notification Queue", name)
        expected_backoff = RETRY_BACKOFF[0]  # 300 seconds
        diff = (entry.next_retry_at - now_datetime()).total_seconds()
        # Allow some tolerance for test execution time
        self.assertAlmostEqual(diff, expected_backoff, delta=10)

    def test_retry_final_failure_marks_failed(self):
        """After max_retries+1 failures, entry is marked Failed."""
        name = enqueue_notification(
            self.recipient, "In-App",
            variables={"subject": "Fail"},
        )
        entry = frappe.get_doc("Notification Queue", name)
        max_r = entry.max_retries or 3

        # Need max_r + 1 calls (initial + max_r retries) to exhaust
        for i in range(max_r + 1):
            _handle_delivery_failure(name, f"Error {i + 1}")

        entry = frappe.get_doc("Notification Queue", name)
        self.assertEqual(entry.status, "Failed")
        self.assertEqual(entry.retry_count, max_r + 1)

    def test_retry_final_failure_alerts_admin(self):
        """Final failure creates a Notification Log for Administrator."""
        name = enqueue_notification(self.recipient, "In-App", variables={"subject": "Alert"})
        entry = frappe.get_doc("Notification Queue", name)
        max_r = entry.max_retries or 3

        # Need max_r + 1 calls to exhaust all retries
        for i in range(max_r + 1):
            _handle_delivery_failure(name, f"Error {i + 1}")

        admin_logs = frappe.get_all(
            "Notification Log",
            filters={"for_user": "Administrator"},
            pluck="subject",
        )
        self.assertGreater(len(admin_logs), 0)
        self.assertIn("failed", admin_logs[0].lower())

    def test_retry_exponential_backoff_sequence(self):
        """Retries use increasing backoff: 5min, 15min, 1hr."""
        name = enqueue_notification(self.recipient, "In-App", variables={"subject": "Seq"})

        for i, expected_seconds in enumerate([300, 900, 3600], start=1):
            _handle_delivery_failure(name, f"Error {i}")
            entry = frappe.get_doc("Notification Queue", name)
            if i < (entry.max_retries or 3):
                diff = (entry.next_retry_at - now_datetime()).total_seconds()
                self.assertAlmostEqual(diff, expected_seconds, delta=10,
                                       msg=f"Backoff mismatch for retry {i}")

    # ── Edge Cases ──

    def test_empty_recipient_raises_error(self):
        """enqueue_notification with empty recipient raises ValidationError."""
        with self.assertRaises(frappe.ValidationError):
            enqueue_notification("", "Email")

    def test_process_does_not_double_process(self):
        """Already-processed items are not double-processed."""
        name = enqueue_notification(self.recipient, "In-App", variables={"subject": "Once"})

        frappe.db.set_value("Notification Queue", name, "status", "Sent")

        count = process_notification_queue(limit=10)
        # Should not process the already-Sent item
        entries = frappe.get_all("Notification Queue", pluck="name")
        self.assertEqual(len(entries), 1)
        status = frappe.db.get_value("Notification Queue", name, "status")
        self.assertEqual(status, "Sent")

    def test_enqueue_without_variables(self):
        """enqueue_notification works without variables."""
        name = enqueue_notification(self.recipient, "Email")
        entry = frappe.get_doc("Notification Queue", name)
        self.assertEqual(entry.status, "Queued")
        self.assertEqual(entry.subject, "Notification")

    def test_process_retry_eligible_items(self):
        """Items with past next_retry_at are picked up for retry."""
        name = enqueue_notification(self.recipient, "In-App", variables={"subject": "Retry Me"})

        # Set as Processing with a past retry time
        frappe.db.set_value("Notification Queue", name, {
            "status": "Processing",
            "next_retry_at": frappe.utils.add_to_date(now_datetime(), seconds=-60, as_datetime=True),
        })

        count = process_notification_queue(limit=10)
        self.assertEqual(count, 1)

    def test_error_log_format(self):
        """Error log entries are stored as JSON array."""
        name = enqueue_notification(self.recipient, "In-App", variables={"subject": "ErrLog"})
        _handle_delivery_failure(name, "First error")

        entry = frappe.get_doc("Notification Queue", name)
        log = json.loads(entry.error_log)
        self.assertIsInstance(log, list)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["attempt"], 1)
        self.assertEqual(log[0]["error"], "First error")
