from __future__ import unicode_literals

import frappe
from frappe.tests.utils import FrappeTestCase

from bike_rental.api.catalogue import get_catalogue_data, get_hubs_list


class TestCatalogue(FrappeTestCase):
    """Tests for Customer Website catalogue API (Story 6.1)."""

    def test_get_hubs_list_returns_list(self):
        """get_hubs_list returns a list of hubs."""
        hubs = get_hubs_list()
        self.assertIsInstance(hubs, list)

    def test_get_hubs_list_has_name_field(self):
        """Each hub has a name field."""
        hubs = get_hubs_list()
        if hubs:
            self.assertIn("name", hubs[0])

    def test_get_catalogue_data_returns_structure(self):
        """get_catalogue_data returns expected structure."""
        hubs = get_hubs_list()
        if not hubs:
            self.skipTest("No hubs in database")
        data = get_catalogue_data(hubs[0].name)
        self.assertIn("models", data)
        self.assertIn("hub", data)
        self.assertIsInstance(data["models"], list)

    def test_get_catalogue_data_model_fields(self):
        """Each model has the required fields."""
        hubs = get_hubs_list()
        if not hubs:
            self.skipTest("No hubs in database")
        data = get_catalogue_data(hubs[0].name)
        if data["models"]:
            for key in ("name", "category", "base_rate_daily", "available",
                         "total_serials", "rented"):
                self.assertIn(key, data["models"][0])

    def test_get_catalogue_data_availability_non_negative(self):
        """Available count should be >= 0."""
        hubs = get_hubs_list()
        if not hubs:
            self.skipTest("No hubs in database")
        data = get_catalogue_data(hubs[0].name)
        for model in data["models"]:
            self.assertGreaterEqual(model["available"], 0)

    def test_get_catalogue_data_nonexistent_hub(self):
        """get_catalogue_data with nonexistent hub returns empty models."""
        data = get_catalogue_data("Nonexistent Hub")
        self.assertEqual(data["models"], [])
        self.assertEqual(data["hub"], "Nonexistent Hub")

    def test_get_catalogue_data_empty_hub(self):
        """get_catalogue_data with empty hub returns empty."""
        data = get_catalogue_data("")
        self.assertEqual(data["models"], [])
        self.assertIsNone(data["hub"])
