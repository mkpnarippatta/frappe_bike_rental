frappe.pages["booking-management"].on_page_load = function (wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Booking Management"),
        single_column: true,
    });

    page.main.html(`
        <div class="booking-management">
            <div class="filter-section" style="margin-bottom: 15px;">
                <div class="row">
                    <div class="col-md-2">
                        <select class="form-control" id="bm-status-filter">
                            <option value="">${__("All Status")}</option>
                            <option value="Draft">${__("Draft")}</option>
                            <option value="Confirmed">${__("Confirmed")}</option>
                            <option value="Active">${__("Active")}</option>
                            <option value="Completed">${__("Completed")}</option>
                            <option value="Cancelled">${__("Cancelled")}</option>
                            <option value="Expired">${__("Expired")}</option>
                        </select>
                    </div>
                    <div class="col-md-2">
                        <input type="date" class="form-control" id="bm-date-from" placeholder="${__("Date From")}">
                    </div>
                    <div class="col-md-2">
                        <input type="date" class="form-control" id="bm-date-to" placeholder="${__("Date To")}">
                    </div>
                    <div class="col-md-2">
                        <input type="text" class="form-control" id="bm-customer-search"
                               placeholder="${__("Customer Name")}">
                    </div>
                    <div class="col-md-2">
                        <input type="text" class="form-control" id="bm-id-search"
                               placeholder="${__("Booking ID")}">
                    </div>
                    <div class="col-md-2">
                        <button class="btn btn-primary btn-sm" id="bm-search-btn">
                            ${__("Search")}
                        </button>
                        <button class="btn btn-default btn-sm" id="bm-refresh-btn">
                            ${__("Refresh")}
                        </button>
                    </div>
                </div>
            </div>

            <div id="bm-loading" style="text-align: center; padding: 40px;">
                <i class="fa fa-spinner fa-spin"></i> ${__("Loading bookings...")}
            </div>

            <div id="bm-booking-list" style="display: none;">
                <table class="table table-bordered table-hover" id="bm-table">
                    <thead>
                        <tr>
                            <th>${__("Booking ID")}</th>
                            <th>${__("Customer")}</th>
                            <th>${__("Model")}</th>
                            <th>${__("Hub")}</th>
                            <th>${__("Status")}</th>
                            <th>${__("Start")}</th>
                            <th>${__("End")}</th>
                            <th>${__("Amount")}</th>
                            <th>${__("KYC Status")}</th>
                            <th>${__("Actions")}</th>
                        </tr>
                    </thead>
                    <tbody id="bm-table-body"></tbody>
                </table>
            </div>

            <div id="bm-empty" style="display: none; text-align: center; padding: 40px;">
                <p>${__("No bookings found matching your filters.")}</p>
            </div>
        </div>
    `);

    // Event handlers
    page.main.find("#bm-search-btn").click(function () {
        load_bookings(page);
    });

    page.main.find("#bm-refresh-btn").click(function () {
        // Clear filters
        page.main.find("#bm-status-filter").val("");
        page.main.find("#bm-date-from").val("");
        page.main.find("#bm-date-to").val("");
        page.main.find("#bm-customer-search").val("");
        page.main.find("#bm-id-search").val("");
        load_bookings(page);
    });

    // Enter key triggers search
    page.main.find("#bm-customer-search, #bm-id-search").keypress(function (e) {
        if (e.which === 13) load_bookings(page);
    });

    load_bookings(page);
};

function load_bookings(page) {
    var status = page.main.find("#bm-status-filter").val();
    var date_from = page.main.find("#bm-date-from").val();
    var date_to = page.main.find("#bm-date-to").val();
    var customer = page.main.find("#bm-customer-search").val();
    var booking_id = page.main.find("#bm-id-search").val();

    page.main.find("#bm-loading").show();
    page.main.find("#bm-booking-list").hide();
    page.main.find("#bm-empty").hide();

    frappe.call({
        method: "bike_rental.page.booking_management.booking_management.get_bookings",
        args: {
            status: status || undefined,
            date_from: date_from || undefined,
            date_to: date_to || undefined,
            customer: customer || undefined,
            booking_id: booking_id || undefined,
            limit: 50,
        },
        callback: function (r) {
            page.main.find("#bm-loading").hide();

            if (r.message && r.message.length > 0) {
                render_booking_table(page, r.message);
                page.main.find("#bm-booking-list").show();
            } else {
                page.main.find("#bm-empty").show();
            }
        },
    });
}

function render_booking_table(page, bookings) {
    var tbody = page.main.find("#bm-table-body");
    tbody.empty();

    bookings.forEach(function (b) {
        var statusClass = get_status_class(b.status);
        var kycClass = get_kyc_class(b.kyc_status);

        var actions = "";
        if (b.status === "Confirmed") {
            actions += `<button class="btn btn-success btn-xs action-checkout"
                data-booking="${b.name}">${__("Check Out")}</button> `;
        }
        if (b.status === "Active") {
            actions += `<button class="btn btn-info btn-xs action-checkin"
                data-booking="${b.name}">${__("Check In")}</button> `;
        }
        if (["Draft", "Confirmed", "Active"].indexOf(b.status) >= 0) {
            actions += `<button class="btn btn-danger btn-xs action-cancel"
                data-booking="${b.name}">${__("Cancel")}</button>`;
        }
        if (!actions) actions = '<span class="text-muted">--</span>';

        var row = $(`<tr>
            <td><a href="/app/rental-booking/${b.name}">${b.name}</a></td>
            <td><a href="/app/customer/${b.customer}">${b.customer_name || b.customer}</a></td>
            <td>${b.bike_model || "--"}</td>
            <td>${b.hub}</td>
            <td><span class="label ${statusClass}">${b.status}</span></td>
            <td>${b.start_date}</td>
            <td>${b.end_date}</td>
            <td>${format_currency(b.total_amount)}</td>
            <td><span class="label ${kycClass}">${b.kyc_status}</span></td>
            <td class="actions-cell">${actions}</td>
        </tr>`);

        tbody.append(row);
    });

    // Bind action buttons
    tbody.find(".action-checkout").click(function () {
        show_checkout_modal($(this).data("booking"), page);
    });

    tbody.find(".action-checkin").click(function () {
        show_checkin_modal($(this).data("booking"), page);
    });

    tbody.find(".action-cancel").click(function () {
        show_cancel_modal($(this).data("booking"), page);
    });
}

function show_checkout_modal(booking_name, page) {
    frappe.prompt([
        {
            fieldname: "serial_no",
            fieldtype: "Data",
            label: __("Bike Serial No"),
            reqd: 1,
        },
    ], function (values) {
        frappe.call({
            method: "bike_rental.page.booking_management.booking_management.process_checkout",
            args: {
                booking_name: booking_name,
                serial_no: values.serial_no,
            },
            callback: function (r) {
                if (r.message && !r.message.exc) {
                    frappe.msgprint(__("Check-out completed successfully!"));
                    load_bookings(page);
                }
            },
        });
    }, __("Check-Out Booking: {0}", [booking_name]), __("Confirm Check-Out"));
}

function show_checkin_modal(booking_name, page) {
    frappe.prompt([
        {
            fieldname: "end_km",
            fieldtype: "Int",
            label: __("End Odometer Reading"),
            reqd: 1,
        },
        {
            fieldname: "end_battery",
            fieldtype: "Int",
            label: __("Battery Level (%)"),
        },
        {
            fieldname: "damage_notes",
            fieldtype: "Small Text",
            label: __("Damage Notes"),
        },
        {
            fieldname: "damage_amount",
            fieldtype: "Currency",
            label: __("Damage Charges"),
        },
    ], function (values) {
        frappe.call({
            method: "bike_rental.api.check_in.check_in",
            args: {
                booking_name: booking_name,
                end_km: values.end_km,
                end_battery: values.end_battery || undefined,
                damage_notes: values.damage_notes || undefined,
                damage_amount: values.damage_amount || 0,
            },
            callback: function (r) {
                if (r.message && !r.message.exc) {
                    frappe.msgprint(__("Check-in completed successfully!"));
                    load_bookings(page);
                }
            },
        });
    }, __("Check-In Booking: {0}", [booking_name]), __("Confirm Check-In"));
}

function show_cancel_modal(booking_name, page) {
    frappe.prompt([
        {
            fieldname: "reason",
            fieldtype: "Small Text",
            label: __("Cancellation Reason"),
            reqd: 1,
        },
    ], function (values) {
        frappe.call({
            method: "bike_rental.page.booking_management.booking_management.process_cancellation",
            args: {
                booking_name: booking_name,
                reason: values.reason,
            },
            callback: function (r) {
                if (r.message && !r.message.exc) {
                    frappe.msgprint(__("Booking cancelled successfully! Refund: {0}",
                        [format_currency(r.message.refund ? r.message.refund.refund_amount : 0)]));
                    load_bookings(page);
                }
            },
        });
    }, __("Cancel Booking: {0}", [booking_name]), __("Confirm Cancellation"));
}

function get_status_class(status) {
    var map = {
        "Draft": "label-default",
        "Confirmed": "label-primary",
        "Active": "label-success",
        "Completed": "label-info",
        "Cancelled": "label-danger",
        "Expired": "label-warning",
    };
    return map[status] || "label-default";
}

function get_kyc_class(status) {
    var map = {
        "Verified": "label-success",
        "Pending Review": "label-warning",
        "Rejected": "label-danger",
        "Unverified": "label-default",
    };
    return map[status] || "label-default";
}

function format_currency(amount) {
    if (!amount) return "0.00";
    return parseFloat(amount).toFixed(2);
}
