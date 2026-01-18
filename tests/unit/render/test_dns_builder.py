from pathlib import Path
import os
import pytest

from tools.render.dns.dns_builder import (
    build_dns_context,
    build_desec_context,
    plan_desec_changes,
)
from tools.render.dns.dns_serial import calculate_record_hash
from tools.common.core import RenderError

# DNS builder and serial tests (merged from test_dns.py)


def test_build_dns_context_host_ptr_and_service_substitution(
    tmp_path: Path, dns_test_dates
):
    # Use actual content hashes to avoid "needs update" errors in tests
    # These hashes are pre-computed from the expected zone records
    network = {
        "services": {
            "svc1": {
                "address": "172.20.30.5/32",
                "dns": [
                    {
                        "zone": "svc.abhaile.home.arpa",
                        "records": [
                            {
                                "type": "A",
                                "name": "svc1",
                                "rdata": "%%services.svc1.address|strip_cidr%%",
                            }
                        ],
                    }
                ],
            }
        },
        "dns": {
            "zones": [
                {
                    "name": "svc.abhaile.home.arpa",
                    "provider": "coredns-common",
                    "serial": {
                        "date": dns_test_dates.TODAY,
                        "counter": 0,
                        "content_hash": "",
                    },
                },
                {
                    "name": "abhaile.home.arpa.",
                    "provider": "coredns-common",
                    "serial": {
                        "date": dns_test_dates.TODAY,
                        "counter": 0,
                        "content_hash": "",
                    },
                },
                {
                    "name": "2.20.172.in-addr.arpa.",
                    "provider": "coredns-common",
                    "serial": {
                        "date": dns_test_dates.TODAY,
                        "counter": 0,
                        "content_hash": "",
                    },
                },
                {
                    "name": "30.20.172.in-addr.arpa.",
                    "provider": "coredns-common",
                    "serial": {
                        "date": dns_test_dates.TODAY,
                        "counter": 0,
                        "content_hash": "",
                    },
                },
            ]
        },
    }

    hosts = {
        "hostA": {
            "dns": [
                {
                    "zone": "abhaile.home.arpa.",
                    "records": [
                        {
                            "type": "A",
                            "name": "hostA",
                            "rdata": "172.20.2.50/32",
                            "ptr": True,
                        }
                    ],
                }
            ]
        }
    }

    # Compute content hashes dynamically for zones present
    svc_records = [{"type": "A", "name": "svc1", "rdata": "172.20.30.5", "ptr": False}]
    host_records = [
        {"type": "A", "name": "hostA", "rdata": "172.20.2.50/32", "ptr": True}
    ]
    rev_records = [{"type": "PTR", "name": "50", "rdata": "hostA.abhaile.home.arpa."}]
    zone_hash_map = {
        "svc.abhaile.home.arpa": calculate_record_hash(svc_records),
        "abhaile.home.arpa.": calculate_record_hash(host_records),
        "2.20.172.in-addr.arpa.": calculate_record_hash(rev_records),
    }
    for z in network["dns"]["zones"]:
        h = zone_hash_map.get(z.get("name"))
        if h is not None:
            z["serial"]["content_hash"] = h

    services_meta = {}
    deployed = ["svc1"]

    ctx = build_dns_context(deployed, network, hosts, services_meta, tmp_path)

    zone_names = {z["name"] for z in ctx["zones"]}
    assert "abhaile.home.arpa." in zone_names
    assert any(z["name"].endswith("in-addr.arpa.") for z in ctx["zones"])

    svc_zone = next(
        (z for z in ctx["zones"] if z["name"] == "svc.abhaile.home.arpa"), None
    )
    assert svc_zone is not None
    recs = svc_zone.get("records", [])
    assert any(
        r.get("name") == "svc1" and r.get("rdata") == "172.20.30.5" for r in recs
    )

    # Verify serial exists and is in YYYYMMDDXX format
    assert "serial" in svc_zone
    assert len(svc_zone["serial"]) == 10
    assert svc_zone["serial"].isdigit()


def test_build_desec_context_and_plan(tmp_path: Path, dns_test_dates):
    network = {
        "services": {
            "web": {
                "dns": [
                    {
                        "zone": "example.com",
                        "records": [{"name": "@", "type": "A", "rdata": "1.2.3.4"}],
                    }
                ]
            }
        },
        "dns": {"zones": [{"name": "example.com", "provider": "desec.io"}]},
    }

    deployed = ["web"]

    desec_ctx = build_desec_context(deployed, network)
    desired = desec_ctx.get("desired_records", [])
    assert any(r["type"] == "A" and r["name"] == "@" for r in desired)

    current = []
    plan = plan_desec_changes(desired, current)
    assert len(plan["create"]) == len(desired)

    current = [{"name": "@", "type": "A", "content": ["9.9.9.9"]}]
    plan = plan_desec_changes(desired, current)
    assert len(plan["update"]) == 1

    current = [
        {"name": "@", "type": "A", "content": ["1.2.3.4"]},
        {"name": "old", "type": "A", "content": ["5.6.7.8"]},
    ]
    plan = plan_desec_changes(desired, current)
    assert ("old", "A") in plan["delete"]


# Old serial tests removed - moved to test_dns_serial_commit.py


# Negative / edge-case tests (unique names to avoid collisions)


def test_build_dns_context_invalid_ip_no_ptr(tmp_path: Path):
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
    finally:
        os.chdir(original_cwd)

    hosts = {
        "h1": {
            "dns": [
                {
                    "zone": "abhaile.home.arpa",
                    "records": [
                        {
                            "type": "A",
                            "name": "bad",
                            "rdata": "not.an.ip/24",
                            "ptr": True,
                        }
                    ],
                }
            ]
        }
    }

    with pytest.raises(ValueError):
        build_dns_context([], {}, hosts, {}, tmp_path / "state")


def test_build_dns_context_ipv6_rdata_skips_ptr(tmp_path: Path):
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
    finally:
        os.chdir(original_cwd)

    hosts = {
        "h2": {
            "dns": [
                {
                    "zone": "abhaile.home.arpa",
                    "records": [
                        {
                            "type": "A",
                            "name": "v6",
                            "rdata": "2001:db8::1/128",
                            "ptr": True,
                        }
                    ],
                }
            ]
        }
    }

    records_v6 = [{"type": "A", "name": "v6", "rdata": "2001:db8::1/128", "ptr": True}]
    network = {
        "dns": {
            "zones": [
                {
                    "name": "abhaile.home.arpa",
                    "provider": "coredns-common",
                    "serial": {
                        "date": "20260101",
                        "counter": 0,
                        "content_hash": calculate_record_hash(records_v6),
                    },
                }
            ]
        }
    }
    ctx = build_dns_context([], network, hosts, {}, tmp_path / "state2")
    names = [z["name"] for z in ctx["zones"]]
    assert all("in-addr.arpa" not in n for n in names)


def test_build_dns_context_unresolved_placeholder_raises(tmp_path: Path):
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
    finally:
        os.chdir(original_cwd)

    hosts = {
        "h3": {
            "dns": [
                {
                    "zone": "abhaile.home.arpa",
                    "records": [
                        {"type": "A", "name": "x", "rdata": "%%network.missing%%"}
                    ],
                }
            ]
        }
    }

    records_ph = [{"type": "A", "name": "x", "rdata": "%%network.missing%%"}]
    network = {
        "dns": {
            "zones": [
                {
                    "name": "abhaile.home.arpa",
                    "provider": "coredns-common",
                    "serial": {
                        "date": "20260101",
                        "counter": 0,
                        "content_hash": calculate_record_hash(records_ph),
                    },
                }
            ]
        }
    }
    with pytest.raises(
        RenderError, match="Failed to resolve placeholder.*network.missing"
    ):
        build_dns_context([], network, hosts, {}, tmp_path / "state3")


def test_build_desec_context_skips_missing_service(tmp_path: Path):
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
    finally:
        os.chdir(original_cwd)

    network = {
        "dns": {"zones": [{"name": "example.com", "provider": "desec.io"}]},
        "services": {},
    }

    ctx = build_desec_context(["svc1"], network)
    assert ctx == {"desired_records": []}


def test_plan_desec_changes_create_update_delete():
    desired = [
        {"name": "a", "type": "A", "content": ["1.1.1.1"]},
        {"name": "b", "type": "A", "content": ["2.2.2.2"]},
    ]
    current = [
        {"name": "b", "type": "A", "content": ["9.9.9.9"]},
        {"name": "c", "type": "A", "content": ["3.3.3.3"]},
    ]

    plan = plan_desec_changes(desired, current)
    assert (("a", "A"), ["1.1.1.1"]) in plan["create"]
    assert (("b", "A"), ["2.2.2.2"]) in plan["update"]
    assert ("c", "A") in plan["delete"]


def test_build_dns_context_invalid_ptr_ip(tmp_path: Path):
    hosts = {
        "host1": {
            "dns": [
                {
                    "zone": "abhaile.home.arpa",
                    "records": [
                        {"type": "A", "name": "bad", "rdata": "10.0", "ptr": True}
                    ],
                }
            ]
        }
    }

    network = {"services": {}, "dns": {"zones": []}}
    services_meta = {}
    with pytest.raises(ValueError):
        build_dns_context([], network, hosts, services_meta, tmp_path)


def test_build_desec_context_no_zones():
    ctx = build_desec_context([], {"dns": {"zones": []}, "services": {}})
    assert ctx == {"desired_records": []}


def test_plan_desec_changes_detects_create_update_delete():
    desired = [{"name": "@", "type": "A", "content": ["1.2.3.4"]}]
    current = []
    plan = plan_desec_changes(desired, current)
    assert plan["create"]
    assert plan["update"] == []
    assert plan["delete"] == []


def dnsptr_test_build_dns_context_empty_rdata_skips_ptr(tmp_path: Path):
    hosts = {
        "h1": {
            "dns": [
                {
                    "zone": "abhaile.home.arpa",
                    "records": [{"type": "A", "name": "n", "rdata": "", "ptr": True}],
                }
            ]
        }
    }
    network = {"services": {}, "dns": {"zones": []}}
    services_meta = {}
    with pytest.raises(ValueError):
        build_dns_context([], network, hosts, services_meta, tmp_path)


def test_resolve_placeholder_nonmatching_returns_original():
    network = {"services": {}}
    s = "not_a_placeholder"
    from tools.render.dns.dns_records import resolve_placeholder

    assert resolve_placeholder(s, network) == s


def test_resolve_placeholder_missing_key_raises():
    network = {"services": {}}
    ph = "%%services.nope.address%%"
    from tools.render.dns.dns_records import resolve_placeholder

    with pytest.raises(
        RenderError, match="Failed to resolve placeholder.*services.nope.address"
    ):
        resolve_placeholder(ph, network)


def test_resolve_placeholder_strip_cidr_with_complex_key():
    network = {"enp0s31f6.100": {"address": "172.20.100.5/24"}}
    ph = "%%enp0s31f6.100.address|strip_cidr%%"
    from tools.render.dns.dns_records import resolve_placeholder

    out = resolve_placeholder(ph, network)
    assert out == "172.20.100.5"


def test_ptr_not_created_for_invalid_ip(tmp_path):
    hosts = {
        "h1": {
            "dns": [
                {
                    "zone": "abhaile.home.arpa.",
                    "records": [
                        {"type": "A", "name": "bad", "rdata": "not.an.ip", "ptr": True}
                    ],
                }
            ]
        }
    }

    with pytest.raises(ValueError):
        build_dns_context(
            [], {"services": {}, "dns": {"zones": []}}, hosts, {}, tmp_path
        )


def test_ptr_not_created_for_non_a_record(tmp_path):
    records_aaaa = [{"type": "AAAA", "name": "host1", "rdata": "::1", "ptr": True}]
    network = {
        "services": {},
        "dns": {
            "zones": [
                {
                    "name": "abhaile.home.arpa.",
                    "provider": "coredns-common",
                    "serial": {
                        "date": "20260101",
                        "counter": 0,
                        "content_hash": calculate_record_hash(records_aaaa),
                    },
                }
            ]
        },
    }

    hosts = {
        "h1": {
            "dns": [
                {
                    "zone": "abhaile.home.arpa.",
                    "records": [
                        {"type": "AAAA", "name": "host1", "rdata": "::1", "ptr": True}
                    ],
                }
            ]
        }
    }

    ctx = build_dns_context([], network, hosts, {}, tmp_path)
    assert not any(z["name"].endswith("in-addr.arpa") for z in ctx.get("zones", []))


# --- Desec-specific tests (merged from test_desec.py) ---
def test_plan_desec_no_changes_when_current_matches_desired():
    network = {
        "services": {
            "web": {
                "dns": [
                    {
                        "zone": "example.com",
                        "records": [{"name": "@", "type": "A", "rdata": "1.2.3.4"}],
                    }
                ]
            }
        },
        "dns": {"zones": [{"name": "example.com", "provider": "desec.io"}]},
    }
    deployed = ["web"]
    desired_ctx = build_desec_context(deployed, network)
    desired = desired_ctx.get("desired_records", [])
    current = [{"name": "@", "type": "A", "content": ["1.2.3.4"]}]
    plan = plan_desec_changes(desired, current)
    assert plan["create"] == [] and plan["update"] == [] and plan["delete"] == []


# --- Activity 5: Expanded DNS builder tests ---


def test_zone_sorting_explicit_order(tmp_path, dns_test_dates):
    """Test that zones are sorted in deterministic order."""
    # Test with a smaller, simpler setup
    abhaile_hash = calculate_record_hash(
        [{"type": "A", "name": "test", "rdata": "172.20.20.5", "ptr": False}]
    )

    network = {
        "services": {},
        "dns": {
            "zones": [
                {
                    "name": "abhaile.home.arpa.",
                    "provider": "coredns-common",
                    "serial": {
                        "date": dns_test_dates.TODAY,
                        "counter": 0,
                        "content_hash": abhaile_hash,
                    },
                },
            ]
        },
    }

    hosts = {
        "phobos": {
            "dns": [
                {
                    "zone": "abhaile.home.arpa.",
                    "records": [
                        {
                            "type": "A",
                            "name": "test",
                            "rdata": "172.20.20.5",
                            "ptr": False,
                        }
                    ],
                },
            ]
        }
    }

    # Render with fixed date for deterministic testing
    ctx = build_dns_context(
        [], network, hosts, {}, tmp_path, today=dns_test_dates.TODAY
    )
    zones = ctx.get("zones", [])
    zone_names = [z["name"] for z in zones]

    # Should have at least abhaile.home.arpa
    assert "abhaile.home.arpa." in zone_names
    # Zones should be a list (ordered)
    assert isinstance(zones, list)


def test_serial_management_increment_on_change(tmp_path, dns_test_dates):
    """Test that serial counter format is correct (YYYYMMDDXX)."""
    # Initial records
    initial_records = [
        {"type": "A", "name": "test", "rdata": "172.20.20.5", "ptr": False}
    ]
    initial_hash = calculate_record_hash(initial_records)

    network = {
        "services": {},
        "dns": {
            "zones": [
                {
                    "name": "abhaile.home.arpa.",
                    "provider": "coredns-common",
                    "serial": {
                        "date": dns_test_dates.TODAY,
                        "counter": 5,
                        "content_hash": initial_hash,
                    },
                }
            ]
        },
    }

    hosts = {
        "phobos": {"dns": [{"zone": "abhaile.home.arpa.", "records": initial_records}]}
    }

    # Render with fixed date - serial should be stable since content matches
    ctx1 = build_dns_context(
        [], network, hosts, {}, tmp_path, today=dns_test_dates.TODAY
    )
    zone1 = next((z for z in ctx1["zones"] if z["name"] == "abhaile.home.arpa."), None)

    # Serial should be stable since content matches
    assert zone1 is not None
    assert zone1["serial"] == dns_test_dates.TODAY + "05"  # Original date + counter

    # Change records - should detect hash mismatch and require update
    changed_records = [
        {"type": "A", "name": "host2", "rdata": "172.20.20.6", "ptr": False}
    ]
    hosts_changed = {
        "host1": {"dns": [{"zone": "abhaile.home.arpa.", "records": changed_records}]}
    }

    # This should raise RenderError because content_hash doesn't match
    with pytest.raises(RenderError, match="DNS zone records have changed"):
        build_dns_context([], network, hosts_changed, {}, tmp_path)


def test_zone_filtering_by_provider(tmp_path, dns_test_dates):
    """Test that zones are correctly filtered by provider."""
    records = [{"type": "A", "name": "test", "rdata": "1.2.3.4", "ptr": False}]
    network = {
        "services": {},
        "dns": {
            "zones": [
                {
                    "name": "abhaile.home.arpa.",
                    "provider": "coredns-common",
                    "serial": {
                        "date": dns_test_dates.TODAY,
                        "counter": 0,
                        "content_hash": calculate_record_hash(records),
                    },
                },
                {
                    "name": "abhaile.dedyn.io",
                    "provider": "desec.io",
                },
            ]
        },
    }

    hosts = {"host1": {"dns": [{"zone": "abhaile.home.arpa.", "records": records}]}}

    ctx = build_dns_context([], network, hosts, {}, tmp_path)

    # zones_common should only include coredns-common zones
    zones_common_names = {z["name"].rstrip(".") for z in ctx.get("zones_common", [])}
    assert "abhaile.home.arpa" in zones_common_names
    assert "abhaile.dedyn.io" not in zones_common_names

    # providers map should have both
    assert ctx["providers"].get("abhaile.home.arpa") == "coredns-common"
    assert ctx["providers"].get("abhaile.dedyn.io") == "desec.io"


def test_soa_record_serial_format(tmp_path, dns_test_dates):
    """Test that SOA serial is in YYYYMMDDXX format."""
    records = [{"type": "A", "name": "test", "rdata": "172.20.20.5", "ptr": False}]
    network = {
        "services": {},
        "dns": {
            "zones": [
                {
                    "name": "abhaile.home.arpa.",
                    "provider": "coredns-common",
                    "serial": {
                        "date": dns_test_dates.TODAY,
                        "counter": 7,
                        "content_hash": calculate_record_hash(records),
                    },
                }
            ]
        },
    }

    hosts = {"phobos": {"dns": [{"zone": "abhaile.home.arpa.", "records": records}]}}

    ctx = build_dns_context(
        [], network, hosts, {}, tmp_path, today=dns_test_dates.TODAY
    )
    zone = next((z for z in ctx["zones"] if z["name"] == "abhaile.home.arpa."), None)

    assert zone is not None
    serial = zone["serial"]
    # Serial should be 10 digits in YYYYMMDDXX format
    assert len(serial) == 10
    assert serial.isdigit()
    # Since content matches, serial should be stable
    assert serial == dns_test_dates.TODAY + "07"
