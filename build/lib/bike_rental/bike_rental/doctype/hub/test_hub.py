from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase


class TestHub(FrappeTestCase):
    """Test suite for Hub DocType and per-hub inventory (FR-35, FR-36)."""

    def setUp(self):
        self.hub_a = frappe.get_doc(
            {
                "doctype": "Hub",
                "hub_name": "Test Hub A",
                "location": "123 Test Street",
                "operating_hours_start": "06:00:00",
                "operating_hours_end": "22:00:00",
            }
        ).insert()

        self.hub_b = frappe.get_doc(
            {
                "doctype": "Hub",
                "hub_name": "Test Hub B",
                "location": "456 Test Avenue",
                "operating_hours_start": "08:00:00",
                "operating_hours_end": "20:00:00",
            }
        ).insert()

        self.bike_model = frappe.get_doc(
            {
                "doctype": "Bike Model",
                "model_name": "Test Hub Bike",
                "brand": "HubBrand",
                "category": "City",
                "base_rate_hourly": 10.00,
                "base_rate_daily": 40.00,
            }
        ).insert()

    def tearDown(self):
        for name in frappe.get_all("Bike Serial", pluck="name"):
            frappe.delete_doc("Bike Serial", name, force=True)
        for name in frappe.get_all("Hub", pluck="name"):
            frappe.delete_doc("Hub", name, force=True)
        if frappe.db.exists("Bike Model", self.bike_model.name):
            frappe.delete_doc("Bike Model", self.bike_model.name, force=True)

    def _create_serial(self, registration_no, hub, status="Available"):
        """Helper to create a Bike Serial linked to a hub."""
        return frappe.get_doc(
            {
                "doctype": "Bike Serial",
                "registration_no": registration_no,
                "chassis_no": f"CH-{registration_no}",
                "bike_model": self.bike_model.name,
                "hub": hub,
                "status": status,
            }
        ).insert()

    def test_create_hub_with_all_fields(self):
        """AC #1: Verify all Hub fields are stored correctly."""
        self.assertEqual(self.hub_a.hub_name, "Test Hub A")
        self.assertEqual(self.hub_a.location, "123 Test Street")
        self.assertEqual(self.hub_a.operating_hours_start, "06:00:00")
        self.assertEqual(self.hub_a.operating_hours_end, "22:00:00")
        self.assertEqual(self.hub_a.disabled, 0)

    def test_bike_serial_linked_to_hub(self):
        """AC #2: Bike Serial can be assigned to a specific Hub."""
        serial = self._create_serial("HUB-SER-001", self.hub_a.name)
        self.assertEqual(serial.hub, self.hub_a.name)

    def test_per_hub_available_count(self):
        """AC #3: get_available_count returns correct per-hub counts."""
        from .hub import get_available_count

        # Create 2 serials at Hub A, 1 at Hub B
        self._create_serial("HUB-A-001", self.hub_a.name)
        self._create_serial("HUB-A-002", self.hub_a.name)
        self._create_serial("HUB-B-001", self.hub_b.name)

        count_a = get_available_count(self.bike_model.name, self.hub_a.name)
        self.assertEqual(count_a, 2)

        count_b = get_available_count(self.bike_model.name, self.hub_b.name)
        self.assertEqual(count_b, 1)

    def test_hub_b_does_not_affect_hub_a_availability(self):
        """AC #3: Bike Serials at Hub B do not affect Hub A's count (FR-36)."""
        from .hub import get_available_count

        self._create_serial("HUB-A-001", self.hub_a.name)
        self._create_serial("HUB-B-001", self.hub_b.name)
        self._create_serial("HUB-B-002", self.hub_b.name)

        count_a = get_available_count(self.bike_model.name, self.hub_a.name)
        self.assertEqual(count_a, 1)

    def test_rented_serials_excluded_from_available(self):
        """AC #4: Rented serials are excluded from available count."""
        from .hub import get_available_count

        self._create_serial("HUB-A-001", self.hub_a.name)
        self._create_serial("HUB-A-002", self.hub_a.name, status="Rented")

        count = get_available_count(self.bike_model.name, self.hub_a.name)
        self.assertEqual(count, 1)

    def test_maintenance_serials_excluded_from_available(self):
        """AC #4: Maintenance serials are excluded from available count."""
        from .hub import get_available_count

        self._create_serial("HUB-A-001", self.hub_a.name)
        self._create_serial("HUB-A-002", self.hub_a.name, status="Maintenance")

        count = get_available_count(self.bike_model.name, self.hub_a.name)
        self.assertEqual(count, 1)

    def test_list_view_fields(self):
        """AC #1: List view returns expected columns for Hub."""
        hubs = frappe.get_list(
            "Hub",
            fields=["hub_name", "location"],
            limit=10,
        )
        self.assertGreaterEqual(len(hubs), 2)
        self.assertTrue(any(h.hub_name == "Test Hub A" for h in hubs))

    def test_initiate_transfer_sets_in_transit(self):
        """AC #1: initiate_transfer sets status to In Transit."""
        from .hub import initiate_transfer

        serial = self._create_serial("XFER-001", self.hub_a.name)
        initiate_transfer(serial.name, self.hub_b.name)

        serial.reload()
        self.assertEqual(serial.status, "In Transit")

    def test_initiate_transfer_updates_hub(self):
        """AC #1: initiate_transfer assigns destination hub immediately."""
        from .hub import initiate_transfer

        serial = self._create_serial("XFER-002", self.hub_a.name)
        initiate_transfer(serial.name, self.hub_b.name)

        serial.reload()
        self.assertEqual(serial.hub, self.hub_b.name)

    def test_confirm_arrival_sets_available(self):
        """AC #2: confirm_arrival sets status back to Available."""
        from .hub import initiate_transfer, confirm_arrival

        serial = self._create_serial("XFER-003", self.hub_a.name)
        initiate_transfer(serial.name, self.hub_b.name)

        confirm_arrival(serial.name)
        serial.reload()
        self.assertEqual(serial.status, "Available")
        self.assertEqual(serial.hub, self.hub_b.name)

    def test_transfer_rented_bike_blocked(self):
        """AC #4: Transfer of Rented bike raises ValidationError."""
        from .hub import initiate_transfer

        serial = self._create_serial("XFER-004", self.hub_a.name, status="Rented")

        with self.assertRaises(frappe.ValidationError) as cm:
            initiate_transfer(serial.name, self.hub_b.name)
        self.assertIn("Cannot transfer a rented bike", str(cm.exception))
