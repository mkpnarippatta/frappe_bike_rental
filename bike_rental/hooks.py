from __future__ import unicode_literals

app_name = "bike_rental"
app_title = "Bike Rental"
app_publisher = "Ali"
app_description = "Bike rental management system for multi-hub operators"
app_email = "admin@example.com"
app_license = "MIT"

# DocType discovery — Frappe auto-discovers all DocTypes under the doctype/ directory
# No manual registration needed

# Scheduled Jobs
scheduler_events = {
    "all": [
        "bike_rental.scheduler.expire_ghost_bookings.expire_ghost_bookings",
        "bike_rental.notification.queue.process_notification_queue"
    ],
    "daily": [
        "bike_rental.scheduler.km_maintenance_alerts.alert_maintenance_thresholds",
        "bike_rental.scheduler.prolonged_maintenance_alerts.alert_prolonged_maintenance",
        "bike_rental.scheduler.expire_kyc_documents.expire_kyc_documents",
        "bike_rental.scheduler.cleanup_expired_otps.cleanup_expired_otps",
    ],
    "hourly": [
        "bike_rental.scheduler.send_overdue_notifications",
        "bike_rental.scheduler.checkout_reminders.send_checkout_reminders",
        "bike_rental.scheduler.return_reminders.send_return_reminders",
    ]
}

# Permission checking
has_permission = {
    "Bike Serial": "bike_rental.api.check_permissions.has_serial_permission",
    "Rental Booking": "bike_rental.api.check_permissions.has_booking_permission",
    "KYC Document": "bike_rental.api.kyc.has_kyc_document_permission",
    "Customer": "bike_rental.bike_rental.doctype.customer.customer.has_customer_permission",
}

# Document email digest
# user_email_frequency = {
#     "Daily": "1d",
#     "Weekly": "1w",
# }

# Fixtures — seed data loaded via `bench --site rental.local install-app`
fixtures = [
    {"dt": "Role", "filters": [["name", "in", ["Customer", "Hub Staff", "Hub Manager"]]]},
    {"dt": "Hub", "filters": [["name", "in", ["Downtown Hub", "Airport Hub"]]]},
    {"dt": "Bike Model", "filters": [["name", "in", ["City Cruiser", "Mountain Explorer", "Electric Glide"]]]},
]
