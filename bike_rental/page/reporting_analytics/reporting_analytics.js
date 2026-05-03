frappe.pages["reporting-analytics"].on_page_load = function (wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Reporting & Analytics"),
        single_column: true,
    });

    page.main.html(`
        <div class="reporting-analytics">
            <div class="filter-section" style="margin-bottom: 15px;">
                <div class="row">
                    <div class="col-md-2">
                        <select class="form-control" id="ra-hub-filter">
                            <option value="">${__("All Hubs")}</option>
                        </select>
                    </div>
                    <div class="col-md-2">
                        <input type="date" class="form-control" id="ra-date-from"
                               placeholder="${__("Date From")}">
                    </div>
                    <div class="col-md-2">
                        <input type="date" class="form-control" id="ra-date-to"
                               placeholder="${__("Date To")}">
                    </div>
                    <div class="col-md-2">
                        <select class="form-control" id="ra-granularity" style="display:none;">
                            <option value="Daily">${__("Daily")}</option>
                            <option value="Weekly">${__("Weekly")}</option>
                            <option value="Monthly">${__("Monthly")}</option>
                        </select>
                    </div>
                    <div class="col-md-2">
                        <button class="btn btn-primary btn-sm" id="ra-generate-btn">
                            ${__("Generate")}
                        </button>
                        <button class="btn btn-default btn-sm" id="ra-export-btn" style="display:none;">
                            ${__("Export CSV")}
                        </button>
                    </div>
                </div>
            </div>

            <!-- Report tabs -->
            <ul class="nav nav-tabs" id="ra-tabs" style="margin-bottom: 15px;">
                <li class="active"><a data-tab="revenue" href="#">${__("Revenue")}</a></li>
                <li><a data-tab="utilisation" href="#">${__("Utilisation")}</a></li>
                <li><a data-tab="trends" href="#">${__("Booking Trends")}</a></li>
                <li><a data-tab="maintenance" href="#">${__("Maintenance Costs")}</a></li>
            </ul>

            <div id="ra-loading" style="display:none; text-align:center; padding:40px;">
                <i class="fa fa-spinner fa-spin"></i> ${__("Generating report...")}
            </div>

            <div id="ra-async-notice" style="display:none;"
                 class="alert alert-info">
                <i class="fa fa-clock-o"></i>
                <span id="ra-async-msg">${__("Processing large report in background...")}</span>
            </div>

            <div id="ra-content">
                <p class="text-muted" style="padding:40px; text-align:center;">
                    ${__("Select a report tab and date range, then click Generate.")}
                </p>
            </div>
        </div>
    `);

    // State
    var activeTab = "revenue";
    var reportData = null;

    // Load hubs
    load_hubs(page);

    // Tab switching
    page.main.find("#ra-tabs a").click(function (e) {
        e.preventDefault();
        page.main.find("#ra-tabs li").removeClass("active");
        $(this).closest("li").addClass("active");
        activeTab = $(this).data("tab");

        // Show granularity dropdown only for trends
        if (activeTab === "trends") {
            page.main.find("#ra-granularity").show();
        } else {
            page.main.find("#ra-granularity").hide();
        }

        reportData = null;
        page.main.find("#ra-export-btn").hide();
        page.main.find("#ra-content").html(
            '<p class="text-muted" style="padding:40px; text-align:center;">' +
            __("Click Generate to load report.") + "</p>"
        );
    });

    // Generate button
    page.main.find("#ra-generate-btn").click(function () {
        generate_report(page, activeTab);
    });

    // Export button
    page.main.find("#ra-export-btn").click(function () {
        export_csv(page, activeTab);
    });

    // Listen for async report completion
    frappe.realtime.on("report_ready", function (data) {
        page.main.find("#ra-async-notice").hide();
        frappe.msgprint(__("Report {0} is ready: {1}",
            [data.report_type, data.file_url]));
    });
};

function load_hubs(page) {
    frappe.call({
        method: "frappe.client.get_list",
        args: {
            doctype: "Hub",
            fields: ["name"],
            limit_page_length: 200,
        },
        callback: function (r) {
            if (r.message) {
                var sel = page.main.find("#ra-hub-filter");
                r.message.forEach(function (h) {
                    sel.append('<option value="' + h.name + '">' + h.name + "</option>");
                });
            }
        },
    });
}

function generate_report(page, report_type) {
    var hub = page.main.find("#ra-hub-filter").val();
    var date_from = page.main.find("#ra-date-from").val();
    var date_to = page.main.find("#ra-date-to").val();
    var granularity = page.main.find("#ra-granularity").val() || "Daily";

    page.main.find("#ra-loading").show();
    page.main.find("#ra-content").hide();
    page.main.find("#ra-export-btn").hide();
    page.main.find("#ra-async-notice").hide();

    // Check if date range exceeds 6 months for async processing
    if (is_large_range(date_from, date_to)) {
        frappe.call({
            method: "bike_rental.page.reporting_analytics.reporting_analytics.run_large_report_async",
            args: {
                report_type: report_type,
                hub: hub || undefined,
                date_from: date_from || undefined,
                date_to: date_to || undefined,
            },
            callback: function (r) {
                page.main.find("#ra-loading").hide();
                page.main.find("#ra-async-msg").text(r.message.message);
                page.main.find("#ra-async-notice").show();
            },
        });
        return;
    }

    var method_map = {
        "revenue": "bike_rental.page.reporting_analytics.reporting_analytics.get_revenue_report",
        "utilisation": "bike_rental.page.reporting_analytics.reporting_analytics.get_utilisation_report",
        "trends": "bike_rental.page.reporting_analytics.reporting_analytics.get_booking_trends",
        "maintenance": "bike_rental.page.reporting_analytics.reporting_analytics.get_maintenance_cost_report",
    };

    var args = {
        hub: hub || undefined,
        date_from: date_from || undefined,
        date_to: date_to || undefined,
    };
    if (report_type === "trends") {
        args.granularity = granularity;
    }

    frappe.call({
        method: method_map[report_type],
        args: args,
        callback: function (r) {
            page.main.find("#ra-loading").hide();
            page.main.find("#ra-content").show();

            if (r.message) {
                reportData = r.message;
                render_report(page, report_type, r.message);
                page.main.find("#ra-export-btn").show();
            } else {
                page.main.find("#ra-content").html(
                    '<p class="text-muted" style="padding:20px;">' +
                    __("No data found for the selected filters.") + "</p>"
                );
            }
        },
    });
}

function render_report(page, report_type, data) {
    var html = "";

    switch (report_type) {
        case "revenue":
            html = render_revenue_report(data);
            break;
        case "utilisation":
            html = render_utilisation_report(data);
            break;
        case "trends":
            html = render_trends_report(data);
            break;
        case "maintenance":
            html = render_maintenance_report(data);
            break;
    }

    page.main.find("#ra-content").html(html);
}

function render_revenue_report(data) {
    var html = '<div class="row" style="margin-bottom:15px;">';
    html += '<div class="col-md-4"><div class="panel panel-default"><div class="panel-body text-center">';
    html += '<h3>' + format_currency(data.total_revenue) + '</h3>';
    html += '<small>' + __("Total Revenue") + '</small></div></div></div>';
    html += '<div class="col-md-4"><div class="panel panel-default"><div class="panel-body text-center">';
    html += '<h3>' + data.booking_count + '</h3>';
    html += '<small>' + __("Completed Bookings") + '</small></div></div></div>';
    html += '<div class="col-md-4"><div class="panel panel-default"><div class="panel-body text-center">';
    html += '<h3>' + format_currency(data.average_booking_value) + '</h3>';
    html += '<small>' + __("Avg Booking Value") + '</small></div></div></div>';
    html += "</div>";

    html += '<div class="row"><div class="col-md-6">';
    html += '<h5>' + __("Revenue by Hub") + '</h5>';
    html += '<table class="table table-bordered table-condensed"><thead><tr>';
    html += '<th>' + __("Hub") + '</th><th>' + __("Bookings") + '</th><th>' + __("Revenue") + '</th>';
    html += '</tr></thead><tbody>';
    (data.by_hub || []).forEach(function (h) {
        html += '<tr><td>' + h.hub + '</td><td>' + h.count + '</td><td>' + format_currency(h.revenue) + '</td></tr>';
    });
    html += '</tbody></table></div>';

    html += '<div class="col-md-6">';
    html += '<h5>' + __("Revenue by Model") + '</h5>';
    html += '<table class="table table-bordered table-condensed"><thead><tr>';
    html += '<th>' + __("Model") + '</th><th>' + __("Bookings") + '</th><th>' + __("Revenue") + '</th>';
    html += '</tr></thead><tbody>';
    (data.by_model || []).forEach(function (m) {
        html += '<tr><td>' + m.model + '</td><td>' + m.count + '</td><td>' + format_currency(m.revenue) + '</td></tr>';
    });
    html += '</tbody></table></div></div>';

    return html;
}

function render_utilisation_report(data) {
    var html = '<div class="row" style="margin-bottom:15px;">';
    html += '<div class="col-md-3"><div class="panel panel-default"><div class="panel-body text-center">';
    html += '<h3>' + data.average_utilisation + '%</h3>';
    html += '<small>' + __("Average Utilisation") + '</small></div></div></div>';
    html += '<div class="col-md-3"><div class="panel panel-default"><div class="panel-body text-center">';
    html += '<h3>' + data.peak_utilisation + '%</h3>';
    html += '<small>' + __("Peak") + '</small></div></div></div>';
    html += '<div class="col-md-3"><div class="panel panel-default"><div class="panel-body text-center">';
    html += '<h3>' + data.low_utilisation + '%</h3>';
    html += '<small>' + __("Low") + '</small></div></div></div>';
    html += '<div class="col-md-3"><div class="panel panel-default"><div class="panel-body text-center">';
    html += '<h3>' + data.total_capacity + '</h3>';
    html += '<small>' + __("Total Fleet") + '</small></div></div></div>';
    html += "</div>";

    html += '<h5>' + __("Daily Utilisation") + '</h5>';
    html += '<div style="max-height:400px; overflow-y:auto;">';
    html += '<table class="table table-bordered table-condensed"><thead><tr>';
    html += '<th>' + __("Date") + '</th><th>' + __("Rented") + '</th><th>' + __("Total") + '</th><th>' + __("Utilisation %") + '</th>';
    html += '</tr></thead><tbody>';
    (data.days || []).forEach(function (d) {
        var bar_pct = Math.min(d.utilisation_pct, 100);
        html += '<tr><td>' + d.date + '</td><td>' + d.rented + '</td><td>' + d.total + '</td>';
        html += '<td><div class="progress" style="margin:0; height:18px;">';
        html += '<div class="progress-bar" style="width:' + bar_pct + '%;">' + d.utilisation_pct + '%</div>';
        html += '</div></td></tr>';
    });
    html += '</tbody></table></div>';

    return html;
}

function render_trends_report(data) {
    var html = '<div class="row" style="margin-bottom:15px;">';
    html += '<div class="col-md-4"><div class="panel panel-default"><div class="panel-body text-center">';
    html += '<h3>' + data.total_bookings + '</h3>';
    html += '<small>' + __("Total Bookings") + '</small></div></div></div>';
    html += '<div class="col-md-4"><div class="panel panel-default"><div class="panel-body text-center">';
    html += '<h3>' + (data.periods ? data.periods.length : 0) + '</h3>';
    html += '<small>' + __("Periods") + '</small></div></div></div>';
    html += '<div class="col-md-4"><div class="panel panel-default"><div class="panel-body text-center">';
    html += '<h3>' + data.granularity + '</h3>';
    html += '<small>' + __("Granularity") + '</small></div></div></div>';
    html += "</div>";

    html += '<h5>' + __("Booking Trends") + '</h5>';
    html += '<div style="max-height:400px; overflow-y:auto;">';
    html += '<table class="table table-bordered table-condensed"><thead><tr>';
    html += '<th>' + __("Period") + '</th><th>' + __("Bookings") + '</th><th>' + __("Revenue") + '</th>';
    html += '</tr></thead><tbody>';
    (data.periods || []).forEach(function (p) {
        html += '<tr><td>' + p.period + '</td><td>' + p.count + '</td><td>' + format_currency(p.revenue) + '</td></tr>';
    });
    html += '</tbody></table></div>';

    return html;
}

function render_maintenance_report(data) {
    var html = '<div class="row" style="margin-bottom:15px;">';
    html += '<div class="col-md-6"><div class="panel panel-default"><div class="panel-body text-center">';
    html += '<h3>' + format_currency(data.total_cost) + '</h3>';
    html += '<small>' + __("Total Maintenance Cost") + '</small></div></div></div>';
    html += '<div class="col-md-6"><div class="panel panel-default"><div class="panel-body text-center">';
    html += '<h3>' + data.maintenance_count + '</h3>';
    html += '<small>' + __("Maintenance Jobs") + '</small></div></div></div>';
    html += "</div>";

    html += '<div class="row"><div class="col-md-6">';
    html += '<h5>' + __("Cost by Model") + '</h5>';
    html += '<table class="table table-bordered table-condensed"><thead><tr>';
    html += '<th>' + __("Model") + '</th><th>' + __("Jobs") + '</th><th>' + __("Cost") + '</th>';
    html += '</tr></thead><tbody>';
    (data.by_model || []).forEach(function (m) {
        html += '<tr><td>' + m.model + '</td><td>' + m.count + '</td><td>' + format_currency(m.cost) + '</td></tr>';
    });
    html += '</tbody></table></div>';

    html += '<div class="col-md-6">';
    html += '<h5>' + __("Cost by Service Type") + '</h5>';
    html += '<table class="table table-bordered table-condensed"><thead><tr>';
    html += '<th>' + __("Service Type") + '</th><th>' + __("Jobs") + '</th><th>' + __("Cost") + '</th>';
    html += '</tr></thead><tbody>';
    (data.by_type || []).forEach(function (t) {
        html += '<tr><td>' + t.service_type + '</td><td>' + t.count + '</td><td>' + format_currency(t.cost) + '</td></tr>';
    });
    html += '</tbody></table></div></div>';

    return html;
}

function export_csv(page, report_type) {
    if (!reportData) return;

    frappe.call({
        method: "bike_rental.page.reporting_analytics.reporting_analytics.export_report_csv",
        args: {
            report_type: get_report_label(report_type),
            data_json: reportData,
        },
        callback: function (r) {
            if (r.message) {
                frappe.msgprint(__("CSV exported: <a href='{0}' target='_blank'>{1}</a>",
                    [r.message.file_url, r.message.file_name]));
            }
        },
    });
}

function get_report_label(report_type) {
    var map = {
        revenue: "Revenue",
        utilisation: "Utilisation",
        trends: "Booking Trends",
        maintenance: "Maintenance Costs",
    };
    return map[report_type] || report_type;
}

function is_large_range(date_from, date_to) {
    if (!date_from || !date_to) return false;
    var from = new Date(date_from);
    var to = new Date(date_to);
    var months = (to.getFullYear() - from.getFullYear()) * 12 +
                  (to.getMonth() - from.getMonth());
    return months > 6;
}

function format_currency(amount) {
    if (!amount && amount !== 0) return "0.00";
    return parseFloat(amount).toFixed(2);
}
