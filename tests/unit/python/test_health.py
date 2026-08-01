"""Unit tests for post-apply health audit helpers."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from abhaile import health


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    """Build a subprocess result for health helper tests."""
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )


class TestHealthHelpers:
    """Tests for health helper behavior."""

    def test_coredns_soa_must_match_across_endpoints(self, monkeypatch: Any) -> None:
        answers = {
            ("172.20.20.235", "abhaile.home.arpa.", "SOA"): "ns1 hostmaster 100",
            ("172.20.20.236", "abhaile.home.arpa.", "SOA"): "ns1 hostmaster 101",
            ("172.20.20.235", "abhaile.home.arpa.", "NS"): "ns1\nns2",
            ("172.20.20.236", "abhaile.home.arpa.", "NS"): "ns1\nns2",
            ("172.20.20.235", "example.com.", "A"): "93.184.216.34",
            ("172.20.20.236", "example.com.", "A"): "93.184.216.34",
        }

        def fake_dig(server: str, qname: str, qtype: str, *, timeout_seconds: int) -> str:
            return answers.get((server, qname, qtype), "")

        monkeypatch.setattr(health, "_dig", fake_dig)
        network = {
            "services": {
                "coredns-a": {"address": "172.20.20.235/32"},
                "coredns-b": {"address": "172.20.20.236/32"},
            },
            "dns": {
                "zones": [
                    {
                        "name": "abhaile.home.arpa.",
                        "provider": {"type": "internal"},
                    }
                ]
            },
        }

        results = health._check_coredns(network, timeout_seconds=1)

        consistency = [
            result for result in results if result.name == "dns-soa-consistent:abhaile.home.arpa."
        ]
        assert consistency
        assert consistency[0].success is False

    def test_rootless_failed_units_excludes_only_podman_service(self, monkeypatch: Any) -> None:
        def fake_command(
            argv: list[str],
            *,
            timeout_seconds: int,
            check: bool = False,
        ) -> subprocess.CompletedProcess[str]:
            if "--user" in argv:
                return _completed("podman.service failed\nvault-agent.service failed\n")
            return _completed("")

        monkeypatch.setattr(health, "_command", fake_command)

        results = health._check_failed_units(timeout_seconds=1)

        rootless = [result for result in results if result.name == "rootless-failed-units"][0]
        assert rootless.success is False
        assert "vault-agent.service" in rootless.detail
        assert "podman.service" not in rootless.detail

    def test_required_service_32_address_checked(self, tmp_path: Path, monkeypatch: Any) -> None:
        config_root = tmp_path / "config"
        service_dir = config_root / "services" / "coredns-a"
        service_dir.mkdir(parents=True)
        (service_dir / "service.yaml").write_text(
            "name: coredns-a\nsystemd:\n  network: service-32\n",
            encoding="utf-8",
        )
        seen: list[list[str]] = []

        def fake_command(
            argv: list[str],
            *,
            timeout_seconds: int,
            check: bool = False,
        ) -> subprocess.CompletedProcess[str]:
            seen.append(argv)
            return _completed("172.20.20.235")

        monkeypatch.setattr(health, "_command", fake_command)
        network = {
            "hosts": {
                "phobos": {
                    "interfaces": {
                        "ipvlan-l2": {"address": "172.20.20.20/32"},
                    }
                }
            },
            "services": {
                "coredns-a": {"address": "172.20.20.235/32"},
            },
        }

        results = health._check_required_addresses(
            "phobos",
            ["coredns-a"],
            config_root,
            network,
        )

        assert len(results) == 2
        assert ["ip", "addr", "show", "to", "172.20.20.235"] in seen

    def test_system_unit_command_failure_is_reported(self, monkeypatch: Any) -> None:
        def fake_command(
            argv: list[str],
            *,
            timeout_seconds: int,
            check: bool = False,
        ) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError("systemctl missing")

        monkeypatch.setattr(health, "_command", fake_command)
        manifest = {
            "entries": [
                {
                    "kind": "systemd.unit",
                    "owner_ref": "unit:coredns.service",
                }
            ]
        }

        results = health._check_system_units(manifest, timeout_seconds=1)

        assert results == [
            health.HealthResult("unit-active:coredns.service", False, "systemctl missing")
        ]

    def test_rootless_vault_agent_skips_when_unmapped(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            health,
            "_command",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected command")),
        )

        assert health._check_rootless_vault_agent(["coredns-a"], timeout_seconds=1) == []

    def test_rootless_vault_agent_failure_is_reported(self, monkeypatch: Any) -> None:
        def fake_command(
            argv: list[str],
            *,
            timeout_seconds: int,
            check: bool = False,
        ) -> subprocess.CompletedProcess[str]:
            return _completed("inactive", returncode=3)

        monkeypatch.setattr(health, "_command", fake_command)

        results = health._check_rootless_vault_agent(["vault-agent"], timeout_seconds=1)

        assert results == [
            health.HealthResult("rootless-unit-active:vault-agent.service", False, "inactive")
        ]

    def test_failed_units_command_errors_are_reported(self, monkeypatch: Any) -> None:
        calls = 0

        def fake_command(
            argv: list[str],
            *,
            timeout_seconds: int,
            check: bool = False,
        ) -> subprocess.CompletedProcess[str]:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise FileNotFoundError("systemctl missing")
            raise FileNotFoundError("machinectl unavailable")

        monkeypatch.setattr(health, "_command", fake_command)

        results = health._check_failed_units(timeout_seconds=1)

        assert results == [
            health.HealthResult("system-failed-units", False, "systemctl missing"),
            health.HealthResult("rootless-failed-units", False, "machinectl unavailable"),
        ]

    def test_secrets_ready_sentinel_missing_empty_current_and_stale(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        sentinel = tmp_path / ".ready"
        uptime = tmp_path / "uptime"
        monkeypatch.setattr(health, "_SECRETS_READY_SENTINEL", sentinel)
        monkeypatch.setattr(health, "_PROC_UPTIME", uptime)

        assert health._check_secrets_ready(["vault-agent"]) == [
            health.HealthResult("secrets-ready-sentinel", False, "missing")
        ]

        sentinel.write_text("", encoding="utf-8")
        assert health._check_secrets_ready(["vault-agent"]) == [
            health.HealthResult("secrets-ready-sentinel", False, "empty")
        ]

        sentinel.write_text("ready\n", encoding="utf-8")
        now = time.time()
        uptime.write_text("10.0 0.0\n", encoding="utf-8")
        monkeypatch.setattr(health.time, "time", lambda: now)
        stale_mtime = now - 20
        current_mtime = now - 5

        sentinel.touch()
        sentinel.chmod(0o600)
        os.utime(sentinel, (stale_mtime, stale_mtime))
        stale = health._check_secrets_ready(["vault-agent"])
        assert stale[0].success is False

        os.utime(sentinel, (current_mtime, current_mtime))
        current = health._check_secrets_ready(["vault-agent"])
        assert current[0].success is True

    def test_run_health_audit_reads_config_and_combines_checks(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        repo_root = tmp_path / "repo"
        output_root = tmp_path / "out"
        config_root = repo_root / "config"
        service_dir = config_root / "services" / "coredns-a"
        service_dir.mkdir(parents=True)
        (config_root / "mapping.yaml").write_text(
            "abhaile:\n  - phobos:\n      - coredns-a\n", encoding="utf-8"
        )
        (config_root / "network.yaml").write_text(
            "hosts:\n"
            "  phobos:\n"
            "    interfaces:\n"
            "      shim:\n"
            "        address: 172.20.20.20/32\n"
            "services:\n"
            "  coredns-a:\n"
            "    address: 172.20.20.235/32\n",
            encoding="utf-8",
        )
        (service_dir / "service.yaml").write_text(
            "name: coredns-a\nsystemd:\n  network: service-32\n", encoding="utf-8"
        )
        (output_root / "rendered").mkdir(parents=True)
        (output_root / "rendered" / "manifest.json").write_text(
            '{"entries": []}\n', encoding="utf-8"
        )

        monkeypatch.setattr(
            health,
            "_command",
            lambda *_args, **_kwargs: _completed("172.20.20.235\n172.20.20.20\n"),
        )
        monkeypatch.setattr(health, "_check_coredns", lambda *_args, **_kwargs: [])
        monkeypatch.setattr(health, "_check_podman_health", lambda **_kwargs: [])

        results = health.run_health_audit(
            host="phobos", output_root=output_root, repo_root=repo_root
        )

        assert {result.name for result in results} >= {
            "address:172.20.20.20/32",
            "address:172.20.20.235/32",
            "system-failed-units",
            "rootless-failed-units",
        }
