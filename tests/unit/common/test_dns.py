"""Unit tests for DNS common modules."""

import unittest
from unittest.mock import Mock, patch
from tools.common.dns import DNSProvider, DNSClient, DesecProvider


class TestDNSProvider(unittest.TestCase):
    """Test abstract DNSProvider interface."""

    def test_cannot_instantiate_abstract_class(self):
        """DNSProvider is abstract and cannot be instantiated directly."""
        with self.assertRaises(TypeError):
            DNSProvider()


class TestDesecProvider(unittest.TestCase):
    """Test DesecProvider implementation."""

    def setUp(self):
        self.token = "test_token_123"
        self.provider = DesecProvider(self.token)

    def test_init_default_zone(self):
        """Provider initializes with default zone."""
        self.assertEqual(self.provider.zone, "abhaile.dedyn.io")
        self.assertEqual(self.provider.token, self.token)

    def test_init_custom_zone(self):
        """Provider initializes with custom zone."""
        provider = DesecProvider(self.token, zone="example.com")
        self.assertEqual(provider.zone, "example.com")

    @patch("tools.common.dns.desec_provider.desec_api")
    def test_fetch_current(self, mock_api):
        """fetch_current() calls desec_api.fetch_current()."""
        mock_api.fetch_current.return_value = [
            {"name": "@", "type": "A", "content": ["1.2.3.4"]}
        ]

        result = self.provider.fetch_current()

        mock_api.fetch_current.assert_called_once_with(self.token)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "@")

    def test_plan_changes_create(self):
        """plan_changes() detects new records as creates."""
        desired = [
            {"name": "test", "type": "A", "content": ["1.2.3.4"]},
        ]
        current = []

        plan = self.provider.plan_changes(desired, current)

        self.assertEqual(len(plan["create"]), 1)
        self.assertEqual(plan["create"][0][0], ("test", "A"))
        self.assertEqual(len(plan["update"]), 0)
        self.assertEqual(len(plan["delete"]), 0)

    def test_plan_changes_update(self):
        """plan_changes() detects changed records as updates."""
        desired = [
            {"name": "test", "type": "A", "content": ["1.2.3.5"]},
        ]
        current = [
            {"name": "test", "type": "A", "content": ["1.2.3.4"]},
        ]

        plan = self.provider.plan_changes(desired, current)

        self.assertEqual(len(plan["create"]), 0)
        self.assertEqual(len(plan["update"]), 1)
        self.assertEqual(plan["update"][0][0], ("test", "A"))
        self.assertEqual(plan["update"][0][1], ["1.2.3.5"])
        self.assertEqual(len(plan["delete"]), 0)

    def test_plan_changes_delete(self):
        """plan_changes() detects removed records as deletes."""
        desired = []
        current = [
            {"name": "test", "type": "A", "content": ["1.2.3.4"]},
        ]

        plan = self.provider.plan_changes(desired, current)

        self.assertEqual(len(plan["create"]), 0)
        self.assertEqual(len(plan["update"]), 0)
        self.assertEqual(len(plan["delete"]), 1)
        self.assertEqual(plan["delete"][0], ("test", "A"))

    def test_plan_changes_exclude_records(self):
        """plan_changes() excludes specified records from deletes."""
        provider = DesecProvider(
            self.token, exclude_records={("vpn.abhaile.dedyn.io", "A")}
        )

        desired = []
        current = [
            {"name": "vpn.abhaile.dedyn.io", "type": "A", "content": ["1.2.3.4"]},
        ]

        plan = provider.plan_changes(desired, current)

        # Should not delete excluded record
        self.assertEqual(len(plan["delete"]), 0)

    def test_plan_changes_no_change(self):
        """plan_changes() detects when no changes needed."""
        desired = [
            {"name": "test", "type": "A", "content": ["1.2.3.4"]},
        ]
        current = [
            {"name": "test", "type": "A", "content": ["1.2.3.4"]},
        ]

        plan = self.provider.plan_changes(desired, current)

        self.assertEqual(len(plan["create"]), 0)
        self.assertEqual(len(plan["update"]), 0)
        self.assertEqual(len(plan["delete"]), 0)

    @patch("tools.common.dns.desec_provider.desec_api")
    def test_apply_plan_creates(self, mock_api):
        """apply_plan() creates new records."""
        plan = {
            "create": [(("test", "A"), ["1.2.3.4"])],
            "update": [],
            "delete": [],
        }

        self.provider.apply_plan(plan)

        mock_api.update_record.assert_called_once_with(
            self.token, "test", "A", ["1.2.3.4"]
        )

    @patch("tools.common.dns.desec_provider.desec_api")
    def test_apply_plan_updates(self, mock_api):
        """apply_plan() updates existing records."""
        plan = {
            "create": [],
            "update": [(("test", "A"), ["1.2.3.5"])],
            "delete": [],
        }

        self.provider.apply_plan(plan)

        mock_api.update_record.assert_called_once_with(
            self.token, "test", "A", ["1.2.3.5"]
        )

    @patch("tools.common.dns.desec_provider.desec_api")
    def test_apply_plan_deletes(self, mock_api):
        """apply_plan() deletes removed records."""
        plan = {
            "create": [],
            "update": [],
            "delete": [("test", "A")],
        }

        self.provider.apply_plan(plan)

        mock_api.delete_record.assert_called_once_with(self.token, "test", "A")


class TestDNSClient(unittest.TestCase):
    """Test DNSClient high-level interface."""

    def setUp(self):
        self.mock_provider = Mock(spec=DNSProvider)
        self.client = DNSClient(self.mock_provider)

    def test_init(self):
        """Client initializes with provider."""
        self.assertEqual(self.client.provider, self.mock_provider)

    def test_sync_dry_run(self):
        """sync() in dry-run mode plans but doesn't apply."""
        desired = [{"name": "test", "type": "A", "content": ["1.2.3.4"]}]
        current = []

        self.mock_provider.fetch_current.return_value = current
        self.mock_provider.plan_changes.return_value = {
            "create": [(("test", "A"), ["1.2.3.4"])],
            "update": [],
            "delete": [],
        }

        plan = self.client.sync(desired, dry_run=True)

        self.mock_provider.fetch_current.assert_called_once()
        self.mock_provider.plan_changes.assert_called_once_with(desired, current)
        self.mock_provider.apply_plan.assert_not_called()
        self.assertEqual(plan["summary"]["total"], 1)

    def test_sync_apply(self):
        """sync() in apply mode plans and applies changes."""
        desired = [{"name": "test", "type": "A", "content": ["1.2.3.4"]}]
        current = []

        self.mock_provider.fetch_current.return_value = current
        self.mock_provider.plan_changes.return_value = {
            "create": [(("test", "A"), ["1.2.3.4"])],
            "update": [],
            "delete": [],
        }

        plan = self.client.sync(desired, dry_run=False)

        self.mock_provider.fetch_current.assert_called_once()
        self.mock_provider.plan_changes.assert_called_once()
        self.mock_provider.apply_plan.assert_called_once()
        self.assertEqual(plan["summary"]["total"], 1)

    def test_sync_no_changes(self):
        """sync() handles no-op case correctly."""
        desired = [{"name": "test", "type": "A", "content": ["1.2.3.4"]}]
        current = [{"name": "test", "type": "A", "content": ["1.2.3.4"]}]

        self.mock_provider.fetch_current.return_value = current
        self.mock_provider.plan_changes.return_value = {
            "create": [],
            "update": [],
            "delete": [],
        }

        plan = self.client.sync(desired, dry_run=False)

        # Should not call apply_plan when no changes
        self.mock_provider.apply_plan.assert_not_called()
        self.assertEqual(plan["summary"]["total"], 0)

    def test_fetch_current(self):
        """fetch_current() delegates to provider."""
        expected = [{"name": "@", "type": "A", "content": ["1.2.3.4"]}]
        self.mock_provider.fetch_current.return_value = expected

        result = self.client.fetch_current()

        self.mock_provider.fetch_current.assert_called_once()
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
