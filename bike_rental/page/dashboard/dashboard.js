frappe.pages["hub-dashboard"].on_page_load = function (wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Hub Dashboard"),
        single_column: true,
    });

    // Build dashboard layout
    page.main.html(`
        <div class="hub-dashboard">
            <div class="dashboard-controls" style="margin-bottom: 20px;">
                <div class="row">
                    <div class="col-md-3">
                        <select class="form-control" id="hub-filter" style="display: none;">
                            <option value="">${__("All Hubs")}</option>
                        </select>
                    </div>
                </div>
            </div>

            <div class="dashboard-stats" id="dashboard-stats">
                <div class="row">
                    <div class="col-md-3 col-sm-6">
                        <div class="card stat-card">
                            <div class="card-body text-center">
                                <h3 class="stat-value" id="stat-active-bookings">-</h3>
                                <p class="stat-label">${__("Active Bookings")}</p>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3 col-sm-6">
                        <div class="card stat-card">
                            <div class="card-body text-center">
                                <h3 class="stat-value" id="stat-available-bikes">-</h3>
                                <p class="stat-label">${__("Available Bikes")}</p>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3 col-sm-6">
                        <div class="card stat-card">
                            <div class="card-body text-center">
                                <h3 class="stat-value" id="stat-rented-bikes">-</h3>
                                <p class="stat-label">${__("Rented Bikes")}</p>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3 col-sm-6">
                        <div class="card stat-card">
                            <div class="card-body text-center">
                                <h3 class="stat-value" id="stat-maintenance-bikes">-</h3>
                                <p class="stat-label">${__("Under Maintenance")}</p>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="row mt-3">
                    <div class="col-md-3 col-sm-6">
                        <div class="card stat-card">
                            <div class="card-body text-center">
                                <h3 class="stat-value" id="stat-pending-kyc">-</h3>
                                <p class="stat-label">${__("Pending KYC")}</p>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3 col-sm-6">
                        <div class="card stat-card">
                            <div class="card-body text-center">
                                <h3 class="stat-value" id="stat-today-checkouts">-</h3>
                                <p class="stat-label">${__("Today's Check-Outs")}</p>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3 col-sm-6">
                        <div class="card stat-card">
                            <div class="card-body text-center">
                                <h3 class="stat-value" id="stat-today-checkins">-</h3>
                                <p class="stat-label">${__("Today's Check-Ins")}</p>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3 col-sm-6">
                        <div class="card stat-card">
                            <div class="card-body text-center">
                                <h3 class="stat-value" id="stat-total-capacity">-</h3>
                                <p class="stat-label">${__("Total Capacity")}</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="row mt-4">
                <div class="col-md-6">
                    <div class="card alert-card" id="kyc-section" style="display: none;">
                        <div class="card-header">
                            <h5>${__("Pending KYC Verifications")}</h5>
                        </div>
                        <div class="card-body" id="kyc-content">
                            <p>${__("No pending verifications.")}</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card alert-card" id="maintenance-section" style="display: none;">
                        <div class="card-header">
                            <h5>${__("Prolonged Maintenance (>7 days)")}</h5>
                        </div>
                        <div class="card-body" id="maintenance-content">
                            <p>${__("No bikes in prolonged maintenance.")}</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `);

    // Load initial data and start auto-refresh
    load_dashboard_data(page);

    // Refresh every 60 seconds
    setInterval(function () {
        load_dashboard_data(page);
    }, 60000);
};

function load_dashboard_data(page) {
    var hub = document.getElementById("hub-filter") ? document.getElementById("hub-filter").value : "";

    frappe.call({
        method: "bike_rental.page.dashboard.dashboard.get_dashboard_data",
        args: { hub: hub || undefined },
        callback: function (r) {
            if (r.message && !r.message.error) {
                update_stat_cards(r.message, page);
            }
        },
    });

    frappe.call({
        method: "bike_rental.page.dashboard.dashboard.get_pending_kyc_highlights",
        args: { hub: hub || undefined },
        callback: function (r) {
            if (r.message) {
                update_kyc_section(r.message);
            }
        },
    });

    frappe.call({
        method: "bike_rental.page.dashboard.dashboard.get_prolonged_maintenance",
        args: { hub: hub || undefined },
        callback: function (r) {
            if (r.message) {
                update_maintenance_section(r.message);
            }
        },
    });
}

function update_stat_cards(data, page) {
    document.getElementById("stat-active-bookings").textContent = data.active_bookings || 0;
    document.getElementById("stat-available-bikes").textContent = data.available_bikes || 0;
    document.getElementById("stat-rented-bikes").textContent = data.rented_bikes || 0;
    document.getElementById("stat-maintenance-bikes").textContent = data.maintenance_bikes || 0;
    document.getElementById("stat-pending-kyc").textContent = data.pending_kyc || 0;
    document.getElementById("stat-today-checkouts").textContent = data.today_checkouts || 0;
    document.getElementById("stat-today-checkins").textContent = data.today_checkins || 0;
    document.getElementById("stat-total-capacity").textContent = data.total_capacity || 0;

    // Show hub filter for System Manager
    var hubFilter = document.getElementById("hub-filter");
    if (data.is_system_manager) {
        hubFilter.style.display = "block";
        if (!hubFilter.dataset.loaded) {
            load_hub_filter(data.hub);
            hubFilter.dataset.loaded = "1";
        }
    }
}

function load_hub_filter(selected_hub) {
    frappe.call({
        method: "frappe.client.get_list",
        args: {
            doctype: "Hub",
            fields: ["name"],
            limit: 100,
        },
        callback: function (r) {
            var select = document.getElementById("hub-filter");
            if (r.message) {
                r.message.forEach(function (hub) {
                    var option = document.createElement("option");
                    option.value = hub.name;
                    option.textContent = hub.name;
                    if (hub.name === selected_hub) {
                        option.selected = true;
                    }
                    select.appendChild(option);
                });
            }
            select.addEventListener("change", function () {
                load_dashboard_data();
            });
        },
    });
}

function update_kyc_section(data) {
    var section = document.getElementById("kyc-section");
    var content = document.getElementById("kyc-content");

    if (data.total_pending === 0) {
        section.style.display = "none";
        return;
    }

    section.style.display = "block";

    var html = `
        <p><strong>${__("Total Pending")}:</strong> ${data.total_pending}
        ${data.high_priority_count > 0
            ? `<span class="text-danger"> (${data.high_priority_count} ${__("waiting >24hr")})</span>`
            : ""}
        </p>
        <a class="btn btn-primary btn-sm" href="/app/kyc-document?status=Pending+Review">
            ${__("Review KYC Documents")}
        </a>
        <hr>
        <table class="table table-sm table-bordered">
            <thead>
                <tr>
                    <th>${__("Customer")}</th>
                    <th>${__("Document Type")}</th>
                    <th>${__("Waiting")}</th>
                    <th>${__("Priority")}</th>
                </tr>
            </thead>
            <tbody>
    `;

    data.items.slice(0, 10).forEach(function (item) {
        var priorityClass = item.high_priority ? "text-danger font-weight-bold" : "";
        var priorityText = item.high_priority ? __("High") : __("Normal");
        html += `
            <tr class="${priorityClass}">
                <td><a href="/app/customer/${item.customer}">${item.customer_name}</a></td>
                <td>${item.document_type}</td>
                <td>${item.waiting_hours} ${__("hrs")}</td>
                <td>${priorityText}</td>
            </tr>
        `;
    });

    if (data.items.length > 10) {
        html += `<tr><td colspan="4">${__("...and {0} more", [data.items.length - 10])}</td></tr>`;
    }

    html += "</tbody></table>";
    content.innerHTML = html;
}

function update_maintenance_section(data) {
    var section = document.getElementById("maintenance-section");
    var content = document.getElementById("maintenance-content");

    if (data.total_prolonged === 0) {
        section.style.display = "none";
        return;
    }

    section.style.display = "block";

    var html = `
        <p><strong>${__("Bikes in prolonged maintenance")}:</strong> ${data.total_prolonged}</p>
        <hr>
        <table class="table table-sm table-bordered">
            <thead>
                <tr>
                    <th>${__("Serial No")}</th>
                    <th>${__("Model")}</th>
                    <th>${__("Hub")}</th>
                    <th>${__("Days in Maintenance")}</th>
                </tr>
            </thead>
            <tbody>
    `;

    data.items.forEach(function (item) {
        html += `
            <tr>
                <td><a href="/app/bike-serial/${item.serial_no}">${item.serial_no}</a></td>
                <td>${item.model}</td>
                <td>${item.hub}</td>
                <td>${item.days_in_maintenance} ${__("days")}</td>
            </tr>
        `;
    });

    html += "</tbody></table>";
    content.innerHTML = html;
}
