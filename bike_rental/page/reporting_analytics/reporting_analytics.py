from __future__ import unicode_literals

import csv
import io
import json

import frappe
from frappe import _
from frappe.utils import now_datetime, today


@frappe.whitelist()
def get_revenue_report(hub=None, date_from=None, date_to=None):
    """Return revenue report data grouped by hub and bike model."""
    hub = _scope_to_user_hub(hub)
    filters = {"docstatus": 1, "status": "Completed"}

    if hub:
        filters["hub"] = hub
    if date_from:
        filters["start_date"] = [">=", date_from]
    if date_to:
        filters["end_date"] = ["<=", date_to]

    bookings = frappe.get_all(
        "Rental Booking",
        filters=filters,
        fields=["name", "hub", "bike_model", "total_amount", "start_date", "customer_name"],
        order_by="start_date desc",
    )

    total_revenue = 0.0
    by_hub = {}
    by_model = {}

    for b in bookings:
        amount = float(b.total_amount or 0)
        total_revenue += amount

        by_hub.setdefault(b.hub, {"hub": b.hub, "count": 0, "revenue": 0.0})
        by_hub[b.hub]["count"] += 1
        by_hub[b.hub]["revenue"] += amount

        by_model.setdefault(b.bike_model, {"model": b.bike_model, "count": 0, "revenue": 0.0})
        by_model[b.bike_model]["count"] += 1
        by_model[b.bike_model]["revenue"] += amount

    avg_booking_value = round(total_revenue / len(bookings), 2) if bookings else 0.0

    return {
        "total_revenue": round(total_revenue, 2),
        "booking_count": len(bookings),
        "average_booking_value": avg_booking_value,
        "by_hub": sorted(by_hub.values(), key=lambda x: x["revenue"], reverse=True),
        "by_model": sorted(by_model.values(), key=lambda x: x["revenue"], reverse=True),
        "hub": hub,
    }


@frappe.whitelist()
def get_utilisation_report(hub=None, date_from=None, date_to=None):
    """Return fleet utilisation percentages per day."""
    hub = _scope_to_user_hub(hub)
    hub_filter = {"hub": hub} if hub else {}

    # Total bike capacity (exclude Scrapped, In Transit)
    capacity_filters = {"status": ["not in", ["Scrapped", "In Transit"]]}
    if hub:
        capacity_filters["hub"] = hub
    total_bikes = frappe.db.count("Bike Serial", filters=capacity_filters)

    if total_bikes == 0:
        return {"total_capacity": 0, "days": [], "hub": hub}

    # Date range
    start = date_from or add_days(today(), -30)
    end = date_to or today()

    # Get all active bookings in range
    bookings = frappe.get_all(
        "Rental Booking",
        filters={
            "docstatus": 1,
            "status": ["in", ["Active", "Completed"]],
            "start_date": ["<=", end],
        },
        fields=["name", "start_date", "end_date", "status", "hub"],
    )

    # Build per-day utilisation map
    from frappe.utils import getdate, add_days as add_day

    daily_map = {}
    current = getdate(start)
    end_date = getdate(end)

    while current <= end_date:
        ds = str(current)
        daily_map[ds] = {"date": ds, "rented": 0, "total": total_bikes}
        current = add_day(current, 1)

    for b in bookings:
        b_start = getdate(b.start_date)
        b_end = getdate(b.end_date or b.start_date)
        c = b_start
        while c <= b_end:
            ds = str(c)
            if ds in daily_map:
                daily_map[ds]["rented"] += 1
            c = add_day(c, 1)

    days = []
    for ds in sorted(daily_map.keys()):
        entry = daily_map[ds]
        pct = round((entry["rented"] / entry["total"]) * 100, 1) if entry["total"] else 0.0
        days.append({
            "date": ds,
            "rented": entry["rented"],
            "total": entry["total"],
            "utilisation_pct": pct,
        })

    # Peak / low periods
    all_pcts = [d["utilisation_pct"] for d in days]
    avg_utilisation = round(sum(all_pcts) / len(all_pcts), 1) if all_pcts else 0.0
    peak = max(all_pcts) if all_pcts else 0.0
    low = min(all_pcts) if all_pcts else 0.0

    return {
        "total_capacity": total_bikes,
        "days": days,
        "average_utilisation": avg_utilisation,
        "peak_utilisation": peak,
        "low_utilisation": low,
        "hub": hub,
    }


@frappe.whitelist()
def get_booking_trends(hub=None, date_from=None, date_to=None, granularity="Daily"):
    """Return booking volume trends grouped by day/week/month."""
    hub = _scope_to_user_hub(hub)
    filters = {"docstatus": 1}

    if hub:
        filters["hub"] = hub
    if date_from:
        filters["start_date"] = [">=", date_from]
    if date_to:
        filters["end_date"] = ["<=", date_to]

    bookings = frappe.get_all(
        "Rental Booking",
        filters=filters,
        fields=["name", "start_date", "status", "total_amount", "hub"],
        order_by="start_date asc",
    )

    if not bookings:
        return {"total_bookings": 0, "periods": [], "granularity": granularity, "hub": hub}

    from frappe.utils import getdate

    periods = {}
    for b in bookings:
        dt = getdate(b.start_date)
        if granularity == "Weekly":
            # ISO week: year-Www
            key = "{}-W{:02d}".format(dt.isocalendar()[0], dt.isocalendar()[1])
        elif granularity == "Monthly":
            key = "{}-{:02d}".format(dt.year, dt.month)
        else:
            key = str(dt)

        periods.setdefault(key, {"period": key, "count": 0, "revenue": 0.0})
        periods[key]["count"] += 1
        periods[key]["revenue"] += float(b.total_amount or 0)

    sorted_periods = sorted(periods.values(), key=lambda x: x["period"])
    total = sum(p["count"] for p in sorted_periods)

    return {
        "total_bookings": total,
        "periods": sorted_periods,
        "granularity": granularity,
        "hub": hub,
    }


@frappe.whitelist()
def get_maintenance_cost_report(hub=None, date_from=None, date_to=None):
    """Return maintenance cost breakdown by model and hub."""
    hub = _scope_to_user_hub(hub)
    filters = {"docstatus": 1}

    if hub:
        filters["hub"] = hub
    if date_from:
        filters["modified"] = [">=", date_from]
    if date_to:
        filters["modified"] = ["<=", date_to]

    logs = frappe.get_all(
        "Maintenance Log",
        filters=filters,
        fields=["name", "serial_no", "bike_model", "hub", "service_type",
                "cost", "modified", "description"],
        order_by="modified desc",
    )

    total_cost = 0.0
    by_model = {}
    by_type = {}

    for log in logs:
        cost = float(log.cost or 0)
        total_cost += cost

        model = log.bike_model or "Unknown"
        by_model.setdefault(model, {"model": model, "count": 0, "cost": 0.0})
        by_model[model]["count"] += 1
        by_model[model]["cost"] += cost

        st = log.service_type or "General"
        by_type.setdefault(st, {"service_type": st, "count": 0, "cost": 0.0})
        by_type[st]["count"] += 1
        by_type[st]["cost"] += cost

    return {
        "total_cost": round(total_cost, 2),
        "maintenance_count": len(logs),
        "by_model": sorted(by_model.values(), key=lambda x: x["cost"], reverse=True),
        "by_type": sorted(by_type.values(), key=lambda x: x["cost"], reverse=True),
        "hub": hub,
    }


@frappe.whitelist()
def export_report_csv(report_type, data_json, filename=None):
    """Generate a CSV file from report data and return the file URL."""
    data = json.loads(data_json) if isinstance(data_json, str) else data_json

    output = io.StringIO()
    writer = csv.writer(output)

    if report_type == "Revenue":
        writer.writerow(["Hub", "Bike Model", "Customer", "Amount", "Date"])
        writer.writerow([])
        writer.writerow(["Summary"])
        writer.writerow(["Total Revenue", data.get("total_revenue", 0)])
        writer.writerow(["Total Bookings", data.get("booking_count", 0)])
        writer.writerow(["Average Booking Value", data.get("average_booking_value", 0)])
        writer.writerow([])
        writer.writerow(["Revenue by Hub"])
        writer.writerow(["Hub", "Bookings", "Revenue"])
        for h in data.get("by_hub", []):
            writer.writerow([h["hub"], h["count"], h["revenue"]])
        writer.writerow([])
        writer.writerow(["Revenue by Model"])
        writer.writerow(["Model", "Bookings", "Revenue"])
        for m in data.get("by_model", []):
            writer.writerow([m["model"], m["count"], m["revenue"]])

    elif report_type == "Utilisation":
        writer.writerow(["Date", "Rented", "Total Capacity", "Utilisation %"])
        for d in data.get("days", []):
            writer.writerow([d["date"], d["rented"], d["total"], d["utilisation_pct"]])

    elif report_type == "Booking Trends":
        granularity = data.get("granularity", "Daily")
        writer.writerow(["Period ({})".format(granularity), "Bookings", "Revenue"])
        for p in data.get("periods", []):
            writer.writerow([p["period"], p["count"], p["revenue"]])

    elif report_type == "Maintenance Costs":
        writer.writerow(["Model", "Count", "Cost"])
        writer.writerow([])
        writer.writerow(["Total Cost", data.get("total_cost", 0)])
        writer.writerow(["Total Jobs", data.get("maintenance_count", 0)])
        writer.writerow([])
        writer.writerow(["By Model"])
        writer.writerow(["Model", "Jobs", "Cost"])
        for m in data.get("by_model", []):
            writer.writerow([m["model"], m["count"], m["cost"]])
        writer.writerow([])
        writer.writerow(["By Service Type"])
        writer.writerow(["Service Type", "Jobs", "Cost"])
        for t in data.get("by_type", []):
            writer.writerow([t["service_type"], t["count"], t["cost"]])

    content = output.getvalue()
    output.close()

    fname = filename or "report_{}_{}.csv".format(report_type.lower().replace(" ", "_"), today())
    _file = frappe.get_doc({
        "doctype": "File",
        "file_name": fname,
        "content": content,
        "is_private": 1,
    })
    _file.save(ignore_permissions=True)

    return {
        "file_url": _file.file_url,
        "file_name": fname,
    }


@frappe.whitelist()
def run_large_report_async(report_type, hub=None, date_from=None, date_to=None):
    """Enqueue a large-report generation in the background."""
    from frappe.utils.background_jobs import enqueue

    job = enqueue(
        "bike_rental.page.reporting_analytics.reporting_analytics._generate_large_report",
        queue="long",
        timeout=3600,
        report_type=report_type,
        hub=hub,
        date_from=date_from,
        date_to=date_to,
        user=frappe.session.user,
    )

    return {
        "job_id": job.id,
        "status": "queued",
        "message": _("Report is being generated. You will be notified when it is ready."),
    }


def _generate_large_report(report_type, hub, date_from, date_to, user):
    """Background task: generate report and notify user on completion."""
    frappe.set_user(user)

    if report_type == "Revenue":
        data = get_revenue_report(hub=hub, date_from=date_from, date_to=date_to)
    elif report_type == "Utilisation":
        data = get_utilisation_report(hub=hub, date_from=date_from, date_to=date_to)
    elif report_type == "Booking Trends":
        data = get_booking_trends(hub=hub, date_from=date_from, date_to=date_to)
    elif report_type == "Maintenance Costs":
        data = get_maintenance_cost_report(hub=hub, date_from=date_from, date_to=date_to)
    else:
        return

    result = export_report_csv(report_type, json.dumps(data))

    frappe.publish_realtime(
        "report_ready",
        {
            "report_type": report_type,
            "file_url": result["file_url"],
            "file_name": result["file_name"],
        },
        user=user,
    )


def _scope_to_user_hub(hub):
    """Override hub param for non-System-Manager users."""
    roles = frappe.get_roles()
    if "System Manager" not in roles:
        user_hub = _get_user_hub(frappe.session.user)
        if user_hub:
            return user_hub
    return hub


def _get_user_hub(user):
    """Determine the hub assigned to a non-System-Manager user."""
    user_hub = frappe.db.get_value("User", user, "hub")
    if user_hub:
        return user_hub
    hub = frappe.db.get_value("Hub", {"hub_manager": user}, "name")
    if hub:
        return hub
    return None


def add_days(date_str, days):
    """Add/subtract days from a date string and return YYYY-MM-DD."""
    from frappe.utils import getdate, add_days as _add
    return str(_add(getdate(date_str), days))
