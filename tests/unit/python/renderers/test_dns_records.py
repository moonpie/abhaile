"""Unit tests for DNS record collection."""

from typing import Any, Dict

import pytest

from abhaile.dns.records import collect_zone_records as _collect_zone_records
from abhaile.utils.errors import RenderError


class TestCollectZoneRecords:
    """Tests for _collect_zone_records."""

    def test_collect_host_records_only(self):
        """Test collecting records from hosts only."""
        network: Dict[str, Any] = {
            "hosts": {
                "host1": {
                    "dns": [
                        {
                            "zone": "example.com.",
                            "records": [
                                {
                                    "name": "host1",
                                    "type": "a",
                                    "rdata": "192.0.2.1",
                                    "ttl": 3600,
                                },
                            ],
                        }
                    ]
                }
            },
            "services": {},
        }
        zone: Dict[str, Any] = {"name": "example.com."}
        records = _collect_zone_records(zone, network, [])

        assert len(records) == 1
        assert records[0]["name"] == "host1"

    def test_collect_service_records_only(self):
        """Test collecting records from services only."""
        network: Dict[str, Any] = {
            "hosts": {},
            "services": {
                "service1": {
                    "dns": [
                        {
                            "zone": "svc.example.com.",
                            "records": [
                                {
                                    "name": "service1",
                                    "type": "a",
                                    "rdata": "172.20.20.1",
                                    "ttl": 3600,
                                },
                            ],
                        }
                    ]
                }
            },
        }
        zone: Dict[str, Any] = {"name": "svc.example.com."}
        records = _collect_zone_records(zone, network, ["service1"])

        assert len(records) == 1
        assert records[0]["name"] == "service1"

    def test_collect_host_and_service_records(self):
        """Test collecting records from both hosts and services."""
        network: Dict[str, Any] = {
            "hosts": {
                "host1": {
                    "dns": [
                        {
                            "zone": "svc.example.com.",
                            "records": [
                                {
                                    "name": "host1",
                                    "type": "a",
                                    "rdata": "172.20.20.10",
                                    "ttl": 3600,
                                },
                            ],
                        }
                    ]
                }
            },
            "services": {
                "service1": {
                    "dns": [
                        {
                            "zone": "svc.example.com.",
                            "records": [
                                {
                                    "name": "service1",
                                    "type": "a",
                                    "rdata": "172.20.20.1",
                                    "ttl": 3600,
                                },
                            ],
                        }
                    ]
                }
            },
        }
        zone: Dict[str, Any] = {"name": "svc.example.com."}
        records = _collect_zone_records(zone, network, ["service1"])

        assert len(records) == 2
        # Host records come first
        assert records[0]["name"] == "host1"
        assert records[1]["name"] == "service1"

    def test_collect_multiple_records_per_entity(self):
        """Test collecting multiple records from same host."""
        network: Dict[str, Any] = {
            "hosts": {
                "host1": {
                    "dns": [
                        {
                            "zone": "example.com.",
                            "records": [
                                {
                                    "name": "www",
                                    "type": "a",
                                    "rdata": "192.0.2.1",
                                    "ttl": 3600,
                                },
                                {
                                    "name": "mail",
                                    "type": "a",
                                    "rdata": "192.0.2.2",
                                    "ttl": 3600,
                                },
                            ],
                        }
                    ]
                }
            },
            "services": {},
        }
        zone: Dict[str, Any] = {"name": "example.com."}
        records = _collect_zone_records(zone, network, [])

        assert len(records) == 2
        assert records[0]["name"] == "www"
        assert records[1]["name"] == "mail"

    def test_collect_records_multiple_zones(self):
        """Test that only matching zone records are collected."""
        network: Dict[str, Any] = {
            "hosts": {
                "host1": {
                    "dns": [
                        {
                            "zone": "zone1.com.",
                            "records": [
                                {
                                    "name": "host1",
                                    "type": "a",
                                    "rdata": "192.0.2.1",
                                    "ttl": 3600,
                                },
                            ],
                        },
                        {
                            "zone": "zone2.com.",
                            "records": [
                                {
                                    "name": "host1",
                                    "type": "a",
                                    "rdata": "192.0.2.2",
                                    "ttl": 3600,
                                },
                            ],
                        },
                    ]
                }
            },
            "services": {},
        }
        zone: Dict[str, Any] = {"name": "zone1.com."}
        records = _collect_zone_records(zone, network, [])

        assert len(records) == 1
        assert records[0]["rdata"] == "192.0.2.1"

    def test_collect_ipv6_reverse_zone_rejected(self):
        """Test that IPv6 reverse zone PTR generation is rejected."""
        network: Dict[str, Any] = {
            "hosts": {
                "host1": {
                    "dns": [
                        {
                            "zone": "example.com.",
                            "records": [
                                {
                                    "name": "host1",
                                    "type": "aaaa",
                                    "rdata": "2001:db8::1",
                                    "ttl": 3600,
                                    "ptr": True,
                                },
                            ],
                        }
                    ]
                }
            },
            "services": {},
        }
        zone: Dict[str, Any] = {
            "name": "0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa."
        }

        with pytest.raises(RenderError) as exc_info:
            _collect_zone_records(zone, network, [])

        assert "IPv6 PTR generation is not supported" in str(exc_info.value)
