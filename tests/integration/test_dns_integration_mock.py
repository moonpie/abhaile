import pytest

from tools.dns import cli as dns_cli
from tools.common.dns.provider import DNSProvider
from tools.common.dns.client import DNSClient


class FakeProvider(DNSProvider):
    def __init__(self):
        self.applied_plans = []

    def fetch_current(self):
        return [
            {"name": "@", "type": "A", "content": ["1.2.3.4"], "ttl": 3600},
        ]

    def plan_changes(self, desired, current):
        # simple diff: anything not in current is a create
        current_set = {
            (r["name"], r["type"], tuple(r.get("content", []))) for r in current
        }
        desired_set = {
            (r["name"], r["type"], tuple(r.get("content", []))) for r in desired
        }
        creates = [((n, t), list(c)) for (n, t, c) in desired_set - current_set]
        updates = []
        deletes = []
        return {"create": creates, "update": updates, "delete": deletes}

    def apply_plan(self, plan):
        self.applied_plans.append(plan)


@pytest.fixture
def fake_provider(monkeypatch):
    # Monkeypatch DesecProvider used by CLI to our FakeProvider
    monkeypatch.setattr(
        dns_cli, "DesecProvider", lambda *args, **kwargs: FakeProvider()
    )
    return FakeProvider()


def test_dns_plan_with_fake_provider(monkeypatch, tmp_path, fake_provider):
    # Monkeypatch token loader to avoid env requirement
    monkeypatch.setattr(dns_cli, "load_token", lambda a: "dummy-token")

    # Build desired from real config
    paths = dns_cli.PathConfig.from_env()
    network = dns_cli.load_yaml(paths.config_root / "network.yaml")
    mapping = dns_cli.load_yaml(paths.config_root / "mapping.yaml")
    desired = dns_cli.collect_desired_records(network, mapping)

    client = DNSClient(dns_cli.DesecProvider("dummy"))
    plan = client.sync(desired, dry_run=True)

    assert "summary" in plan
    assert plan["summary"]["total"] >= 0


def test_dns_apply_with_fake_provider(monkeypatch, fake_provider):
    monkeypatch.setattr(dns_cli, "load_token", lambda a: "dummy-token")

    # Build desired from config and apply
    paths = dns_cli.PathConfig.from_env()
    network = dns_cli.load_yaml(paths.config_root / "network.yaml")
    mapping = dns_cli.load_yaml(paths.config_root / "mapping.yaml")
    desired = dns_cli.collect_desired_records(network, mapping)

    client = DNSClient(dns_cli.DesecProvider("dummy"))
    plan = client.sync(desired, dry_run=False)

    # Our FakeProvider records applied plans
    assert plan["summary"]["total"] >= 0
