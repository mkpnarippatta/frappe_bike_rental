from __future__ import unicode_literals

import frappe
from frappe.utils import now_datetime
from frappe import _


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        {
            "fieldname": "serial_no",
            "label": _("Bike Serial"),
            "fieldtype": "Link",
            "options": "Bike Serial",
            "width": 150,
        },
        {
            "fieldname": "bike_model",
            "label": _("Bike Model"),
            "fieldtype": "Link",
            "options": "Bike Model",
            "width": 130,
        },
        {
            "fieldname": "hub",
            "label": _("Hub"),
            "fieldtype": "Link",
            "options": "Hub",
            "width": 120,
        },
        {
            "fieldname": "issue_description",
            "label": _("Issue"),
            "fieldtype": "Data",
            "width": 250,
        },
        {
            "fieldname": "reported_date",
            "label": _("Reported Date"),
            "fieldtype": "Datetime",
            "width": 160,
        },
        {
            "fieldname": "days_in_maintenance",
            "label": _("Days in Maintenance"),
            "fieldtype": "Int",
            "width": 140,
        },
        {
            "fieldname": "maintenance_log",
            "label": _("Maintenance Log"),
            "fieldtype": "Link",
            "options": "Maintenance Log",
            "width": 150,
        },
    ]


def get_data(filters):
    conditions = ["ml.status = 'In Progress'"]
    filter_params = {}

    if filters and filters.get("hub"):
        conditions.append("ml.hub = %(hub)s")
        filter_params["hub"] = filters["hub"]
    if filters and filters.get("min_days"):
        conditions.append("ml.reported_date <= DATE_SUB(NOW(), INTERVAL %(min_days)s DAY)")
        filter_params["min_days"] = filters["min_days"]

    where_clause = " AND ".join(conditions)

    data = frappe.db.sql(
        """
        SELECT
            ml.name AS maintenance_log,
            ml.serial_no,
            ml.bike_model,
            ml.hub,
            ml.issue_description,
            ml.reported_date,
            DATEDIFF(NOW(), ml.reported_date) AS days_in_maintenance
        FROM `tabMaintenance Log` ml
        WHERE {where_clause}
        ORDER BY ml.reported_date ASC
    """.format(where_clause=where_clause),
        filter_params,
        as_dict=True,
    )

    return data
