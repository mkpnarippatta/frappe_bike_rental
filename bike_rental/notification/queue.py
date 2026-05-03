from __future__ import unicode_literals

import json
import os

import frappe
from frappe import _
from frappe.utils import now_datetime

# Backoff intervals in seconds: 5min, 15min, 1hr
RETRY_BACKOFF = [300, 900, 3600]

VALID_CHANNELS = {"Email", "SMS", "In-App", "WhatsApp"}
VALID_PRIORITIES = {"High", "Normal", "Low"}
PRIORITY_ORDER = {"High": 0, "Normal": 1, "Low": 2}

ALLOWED_TEMPLATE_NAMES = {
    "booking_confirmation", "checkout_reminder", "checkin_reminder",
    "kyc_status_change", "cancellation_confirmation", "deposit_release",
    "booking_extension", "maintenance_alert", "payment_receipt",
}

EVENT_TYPE_MAP = {
    "Booking Confirmation": "booking_confirmation",
    "Check-Out Reminder": "checkout_reminder",
    "Check-In Reminder": "checkin_reminder",
    "KYC Status Change": "kyc_status_change",
    "Cancellation Confirmation": "cancellation_confirmation",
    "Deposit Release": "deposit_release",
    "Booking Extension": "booking_extension",
    "Maintenance Alert": "maintenance_alert",
    "Payment Receipt": "payment_receipt",
}


# ── Queue Service ──


def enqueue_notification(
    recipient,
    channel,
    template=None,
    variables=None,
    priority="Normal",
    reference_doctype=None,
    reference_docname=None,
    hub=None,
):
    """Create a Notification Queue entry for asynchronous delivery.

    Renders the subject and message from the template + variables at enqueue
    time so the queue processor doesn't need template access.

    Returns the name of the created Notification Queue document.
    """
    if not recipient:
        frappe.throw(_("Recipient is required"), frappe.ValidationError)
    if channel not in VALID_CHANNELS:
        frappe.throw(
            _("Invalid channel: {0}. Must be one of: Email, SMS, In-App").format(channel),
            frappe.ValidationError,
        )
    if priority not in VALID_PRIORITIES:
        frappe.throw(
            _("Invalid priority: {0}. Must be one of: High, Normal, Low").format(priority),
            frappe.ValidationError,
        )

    # Check channel is enabled in settings
    _check_channel_enabled(channel)

    variables = variables or {}
    subject, message = _render_template(template, channel, variables, hub)

    settings = frappe.get_single("Rental Notification Settings")
    max_retries = settings.get("max_retries") or 3

    queue_entry = frappe.get_doc({
        "doctype": "Notification Queue",
        "recipient": recipient,
        "channel": channel,
        "subject": subject,
        "message": message,
        "template": template,
        "variables": json.dumps(variables),
        "priority": priority,
        "status": "Queued",
        "max_retries": max_retries,
        "reference_doctype": reference_doctype,
        "reference_docname": reference_docname,
    })
    queue_entry.insert(ignore_permissions=True)
    return queue_entry.name


def enqueue_notification_multi(recipients, channel, template=None, variables=None,
                               priority="Normal", reference_doctype=None,
                               reference_docname=None, hub=None):
    """Create Notification Queue entries for multiple recipients."""
    names = []
    for recipient in recipients:
        name = enqueue_notification(
            recipient, channel, template, variables, priority,
            reference_doctype, reference_docname, hub,
        )
        names.append(name)
    return names


# ── Queue Processing ──


def process_notification_queue(limit=50):
    """Process pending notification queue entries.

    Picks items ordered by priority (High first) then creation date (FIFO).
    Handles retries where next_retry_at has elapsed.
    Processes up to `limit` items per batch.

    Designed to be called from the Frappe scheduler (hooks.py scheduler_events).
    """
    now = now_datetime()

    # Fetch Queued/Processing items where next_retry_at <= now OR is NULL
    queue_items = frappe.db.sql(
        """
        SELECT name, recipient, channel, subject, message, creation,
               reference_doctype, reference_docname, priority,
               retry_count, max_retries, status, next_retry_at
        FROM `tabNotification Queue`
        WHERE status IN (%(status1)s, %(status2)s)
          AND (next_retry_at IS NULL OR next_retry_at <= %(now)s)
        ORDER BY creation ASC
        LIMIT %(limit)s
        """,
        {
            "status1": "Queued",
            "status2": "Processing",
            "now": now,
            "limit": limit,
        },
        as_dict=True,
    )

    if not queue_items:
        return 0

    # Sort by priority (High first) then creation (FIFO within priority)
    queue_items.sort(key=lambda x: (PRIORITY_ORDER.get(x.priority, 1), x.creation))

    processed = 0
    for item in queue_items:
        try:
            lock_ok = _acquire_processing_lock(item.name)
            if not lock_ok:
                continue

            if item.channel == "Email":
                send_email(item)
            elif item.channel == "SMS":
                send_sms(item)
            elif item.channel == "WhatsApp":
                send_whatsapp(item)
            elif item.channel == "In-App":
                send_in_app(item)
            else:
                raise ValueError(_("Unknown channel: {0}").format(item.channel))

            frappe.db.set_value("Notification Queue", item.name, "status", "Sent")
            processed += 1

            # Commit after each successful item to prevent batch-wide rollback
            frappe.db.commit()

        except Exception as e:
            frappe.db.rollback()
            error_msg = str(e)
            frappe.log_error(
                title=_("Notification Delivery Failed"),
                message=_("Queue entry {0}: {1}").format(item.name, error_msg),
            )
            try:
                _handle_delivery_failure(item.name, error_msg)
            except Exception as inner_e:
                frappe.log_error(
                    title=_("Error Handler Failed"),
                    message=_("Queue entry {0}: {1}").format(item.name, str(inner_e)),
                )

    return processed


def _acquire_processing_lock(name):
    """Atomically claim a queue entry for processing.

    Uses a single atomic SQL UPDATE to prevent duplicate processing by
    concurrent scheduler workers. Returns True if the lock was acquired.
    """
    frappe.db.sql(
        """
        UPDATE `tabNotification Queue`
        SET status = 'Processing', last_retry_at = %(now)s
        WHERE name = %(name)s
          AND status IN ('Queued', 'Processing')
        """,
        {"name": name, "now": now_datetime()},
    )
    return frappe.db.sql("SELECT ROW_COUNT()")[0][0] > 0


# ── Delivery Methods ──


def send_email(queue_entry):
    """Send an email notification via Frappe's email queue.

    Uses frappe.sendmail() with HTML content. Generates a plain text
    fallback by stripping HTML tags. Includes unsubscribe message for
    marketing communications.
    """
    from frappe.utils import strip_html

    plain_text = strip_html(queue_entry.message) if queue_entry.message else ""
    kwargs = {
        "recipients": [queue_entry.recipient],
        "subject": queue_entry.subject or _("Notification"),
        "message": queue_entry.message or "",
        "reference_doctype": queue_entry.reference_doctype,
        "reference_name": queue_entry.reference_docname,
        "unsubscribe_message": _("If you do not wish to receive communications, please contact the hub."),
    }

    if plain_text:
        kwargs["content"] = plain_text

    settings = frappe.get_single("Rental Notification Settings")
    sender = settings.get("default_email_sender")
    if sender:
        kwargs["sender"] = sender

    frappe.sendmail(**kwargs)


def send_sms(queue_entry):
    """Send an SMS notification via Twilio (preferred) or generic SMS gateway.

    Reads gateway configuration from Rental Notification Settings Single doctype.
    Auto-truncates messages exceeding 160 characters with "...".
    """
    settings = frappe.get_single("Rental Notification Settings")

    if not settings.get("enable_sms_channel"):
        raise Exception(_("SMS channel is disabled in Rental Notification Settings."))

    message = queue_entry.message or ""
    truncated = False
    if len(message) > 160:
        message = message[:147] + "..."
        truncated = True

    if truncated:
        frappe.logger().warning(
            "SMS truncated for queue entry %s: original length %d",
            queue_entry.name, len(queue_entry.message or ""),
        )

    # Try Twilio first
    twilio_sid = settings.get_password("twilio_account_sid") if settings.twilio_account_sid else None
    twilio_token = settings.get_password("twilio_auth_token") if settings.twilio_auth_token else None
    twilio_from = settings.get("twilio_phone_number")

    if twilio_sid and twilio_token and twilio_from:
        _send_via_twilio(twilio_sid, twilio_token, twilio_from, queue_entry.recipient, message)
        return

    # Fallback to generic HTTP gateway
    gateway_url = settings.get("sms_gateway_url")
    if not gateway_url:
        raise Exception(_("No SMS gateway configured. Configure Twilio or SMS Gateway URL in Rental Notification Settings."))

    try:
        api_key = settings.get_password("sms_api_key")
    except Exception:
        api_key = None

    sender_id = settings.get("sms_sender_id")

    payload = {
        "api_key": api_key or "",
        "sender_id": sender_id or "",
        "recipient": queue_entry.recipient,
        "message": message,
    }

    try:
        frappe.make_post_request(gateway_url, data=payload)
    except Exception as e:
        frappe.log_error(
            title=_("SMS Gateway Error"),
            message=_("Failed to send SMS via {0}: {1}").format(gateway_url, str(e)),
        )
        raise


def send_whatsapp(queue_entry):
    """Send a WhatsApp message via Meta WhatsApp Cloud API.

    Uses the WhatsApp Business API directly at graph.facebook.com.
    Requires a configured phone number ID and access token.

    Sends plain text messages (no template required for active conversations).
    """
    settings = frappe.get_single("Rental Notification Settings")

    if not settings.get("enable_whatsapp_channel"):
        raise Exception(_("WhatsApp channel is disabled in Rental Notification Settings."))

    phone_number_id = settings.get("whatsapp_phone_number_id")
    access_token = settings.get_password("whatsapp_access_token") if settings.whatsapp_access_token else None

    if not phone_number_id or not access_token:
        raise Exception(_("WhatsApp Phone Number ID and Access Token must be configured."))

    recipient = queue_entry.recipient
    if not recipient.startswith("+"):
        recipient = "+" + recipient

    message = queue_entry.message or ""

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {
            "body": message
        }
    }

    url = "https://graph.facebook.com/v22.0/{}/messages".format(phone_number_id)
    headers = {
        "Authorization": "Bearer {}".format(access_token),
        "Content-Type": "application/json",
    }

    try:
        import requests
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code != 200:
            raise Exception(_("WhatsApp API returned {0}: {1}").format(resp.status_code, resp.text))
    except Exception as e:
        frappe.log_error(
            title=_("WhatsApp API Error"),
            message=_("Failed to send WhatsApp to {0}: {1}").format(recipient, str(e)),
        )
        raise


def _send_via_twilio(account_sid, auth_token, from_number, to_number, message):
    """Send SMS using Twilio API."""
    from twilio.rest import Client
    from twilio.base.exceptions import TwilioRestException

    try:
        client = Client(account_sid, auth_token)
        client.messages.create(
            body=message,
            from_=from_number,
            to=to_number,
        )
    except TwilioRestException as e:
        frappe.log_error(
            title=_("Twilio SMS Error"),
            message=_("Twilio error: {0}").format(str(e)),
        )
        raise


def send_in_app(queue_entry):
    """Deliver an in-app notification via Notification Log.

    The recipient must be a valid system user email (Notification Log's
    for_user is a Link field to User doctype). Non-user recipients are
    marked as Failed with a descriptive error.
    """
    if not frappe.db.exists("User", queue_entry.recipient):
        error_msg = _("{0} is not a system user (in-app delivery requires a valid user email)").format(
            queue_entry.recipient
        )
        frappe.logger().info(
            "In-app notification skipped: %s is not a system user (queue: %s)",
            queue_entry.recipient, queue_entry.name,
        )
        raise ValueError(error_msg)

    frappe.get_doc({
        "doctype": "Notification Log",
        "subject": queue_entry.subject or _("Notification"),
        "email_content": queue_entry.message or "",
        "for_user": queue_entry.recipient,
        "document_type": queue_entry.reference_doctype or "Notification Queue",
        "document_name": queue_entry.reference_docname or queue_entry.name,
        "type": "Alert",
    }).insert(ignore_permissions=True)


# ── Retry Logic ──


def _handle_delivery_failure(queue_name, error_message):
    """Handle a delivery failure with retry or final failure.

    Increments retry_count, computes exponential backoff, and either
    schedules a retry or marks the entry as Failed.

    Backoff sequence: 5min -> 15min -> 1hr
    """
    now = now_datetime()
    current = frappe.db.get_value(
        "Notification Queue", queue_name,
        ["retry_count", "max_retries"],
        as_dict=True,
    )
    retry_count = (current.retry_count or 0) + 1
    max_retries = current.max_retries or 3

    # Read existing error log and append new entry
    existing_raw = frappe.db.get_value("Notification Queue", queue_name, "error_log")
    log_entries = json.loads(existing_raw) if existing_raw else []

    log_entries.append({
        "attempt": retry_count,
        "error": error_message,
        "timestamp": str(now),
    })
    error_log = json.dumps(log_entries)

    if retry_count <= max_retries:
        backoff_idx = min(retry_count - 1, len(RETRY_BACKOFF) - 1)
        backoff = RETRY_BACKOFF[backoff_idx]
        next_retry = frappe.utils.add_to_date(now, seconds=backoff, as_datetime=True)
        frappe.db.set_value("Notification Queue", queue_name, {
            "status": "Queued",
            "retry_count": retry_count,
            "next_retry_at": next_retry,
            "error_log": error_log,
        })
    else:
        # Exhausted all retries — mark as Failed and alert admin
        frappe.db.set_value("Notification Queue", queue_name, {
            "status": "Failed",
            "retry_count": retry_count,
            "error_log": error_log,
        })
        try:
            frappe.get_doc({
                "doctype": "Notification Log",
                "subject": _("Notification delivery failed after {0} attempts").format(retry_count),
                "email_content": _(
                    "Queue entry {0} failed after {1} attempts. Last error: {2}"
                ).format(queue_name, retry_count, error_message),
                "for_user": "Administrator",
                "document_type": "Notification Queue",
                "document_name": queue_name,
                "type": "Error",
            }).insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(
                title=_("Admin Alert Failed"),
                message=_("Could not alert admin about queue entry {0}: {1}").format(
                    queue_name, str(e)
                ),
            )

        frappe.log_error(
            title=_("Notification Failed After All Retries"),
            message=_("Queue entry {0}: {1}").format(queue_name, error_message),
        )


# ── Template Rendering ──


def _render_template(template, channel, variables, hub=None):
    """Render a notification subject and message from a template.

    Template lookup chain (first match wins):
    1. DocType: Notification Template for this hub + event + channel
    2. DocType: Notification Template for system default (hub=NULL) + event + channel
    3. File: bike_rental/templates/notifications/{template}.{channel}.j2
    4. Fallback: variables["subject"] and variables["message"]

    Returns (subject, message) tuple.
    """
    subject = variables.get("subject") or _("Notification")
    message = variables.get("message") or ""

    if not template:
        return subject, message

    # Try DocType-based templates (hub-specific first, then system default)
    doc_subject, doc_message = _lookup_template_doc(template, channel, hub)
    if doc_subject:
        subject = doc_subject
        message = doc_message
        rendered_subject = frappe.render_template(subject, variables) if subject else subject
        rendered_message = frappe.render_template(message, variables) if message else message
        return rendered_subject.strip(), rendered_message.strip()

    # Fall back to file-based template
    template_name = template.replace(" ", "_").lower()
    if not _is_safe_template_name(template_name):
        return subject, message

    template_path = (
        frappe.get_app_path("bike_rental", "templates", "notifications",
                            "{0}.{1}.j2".format(template_name, channel.lower()))
    )
    try:
        with open(template_path, "r") as f:
            template_content = f.read()
    except (IOError, OSError):
        return subject, message

    # Separate subject and body by first double newline, or treat as body only
    if template_content.startswith("subject:"):
        parts = template_content.split("\n", 1)
        subject_line = parts[0].replace("subject:", "").strip()
        body = parts[1] if len(parts) > 1 else ""
    else:
        subject_line = subject
        body = template_content

    rendered_subject = frappe.render_template(subject_line, variables) if subject_line else subject
    rendered_message = frappe.render_template(body, variables) if body else message

    return rendered_subject.strip(), rendered_message.strip()


def _lookup_template_doc(template, channel, hub=None):
    """Look up a Notification Template DocType record.

    Checks hub-specific override first, then system default (hub=NULL).
    Returns (subject, message) or (None, None) if not found.
    """
    # Map event type to the stored event name
    event_name = EVENT_TYPE_MAP.get(template) or template.replace("_", " ").title()

    if hub:
        hub_template = frappe.db.get_value(
            "Notification Template",
            {"event": event_name, "channel": channel.capitalize(),
             "hub": hub, "enabled": 1},
            ["subject", "message"],
            as_dict=True,
        )
        if hub_template:
            return hub_template.subject, hub_template.message

    # System default (hub is NULL)
    default_template = frappe.db.get_value(
        "Notification Template",
        {"event": event_name, "channel": channel.capitalize(),
         "hub": ("is", "not set"), "enabled": 1},
        ["subject", "message"],
        as_dict=True,
    )
    if default_template:
        return default_template.subject, default_template.message

    return None, None


def _is_safe_template_name(name):
    """Validate template name to prevent path traversal."""
    if not name:
        return False
    if "/" in name or "\\" in name or ".." in name:
        return False
    # Only allow alphanumeric, underscores, and hyphens
    return all(c.isalnum() or c in ("_", "-") for c in name)


def _check_channel_enabled(channel):
    """Check if a notification channel is enabled in settings."""
    settings = frappe.get_single("Rental Notification Settings")
    field_map = {
        "Email": "enable_email_channel",
        "SMS": "enable_sms_channel",
        "WhatsApp": "enable_whatsapp_channel",
        "In-App": "enable_in_app_channel",
    }
    field = field_map.get(channel)
    if field and not settings.get(field):
        frappe.throw(
            _("{0} channel is disabled in Rental Notification Settings.").format(channel),
            frappe.ValidationError,
        )
