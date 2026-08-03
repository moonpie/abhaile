"""Post-apply host health audit helpers."""

from __future__ import annotations

import json
import socket
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

_SECRETS_READY_SENTINEL = Path("/srv/vault/agent/out/.ready")
_PROC_UPTIME = Path("/proc/uptime")


@dataclass(frozen=True)
class HealthResult:
    """Single health check outcome."""

    name: str
    success: bool
    detail: str = ""


def run_health_audit(
    *,
    host: str | None,
    output_root: Path,
    repo_root: Path,
    timeout_seconds: int = 5,
    cluster: bool = False,
) -> list[HealthResult]:
    """Run bounded post-apply health checks for the local host."""
    actual_host = host or socket.gethostname().split(".", 1)[0]
    config_root = repo_root / "config"
    mapping = _read_yaml(config_root / "mapping.yaml")
    network = _read_yaml(config_root / "network.yaml")
    manifest = _read_json(output_root / "rendered" / "manifest.json")
    services = _mapped_services(mapping, actual_host)
    rootless_users = _rootless_users_for_services(config_root, services)

    results: list[HealthResult] = []
    results.extend(_check_required_addresses(actual_host, services, config_root, network))
    results.extend(
        _check_coredns(
            network,
            timeout_seconds=timeout_seconds,
            include_cluster_consistency=cluster,
        )
    )
    results.extend(_check_system_units(manifest, timeout_seconds=timeout_seconds))
    results.extend(
        _check_rootless_vault_agent(
            services,
            config_root=config_root,
            timeout_seconds=timeout_seconds,
        )
    )
    results.extend(
        _check_failed_units(
            timeout_seconds=timeout_seconds,
            rootless_users=rootless_users,
        )
    )
    results.extend(_check_secrets_ready(services))
    results.extend(_check_podman_health(timeout_seconds=timeout_seconds))
    return results


def results_to_json(results: list[HealthResult]) -> str:
    """Serialize health results as deterministic JSON."""
    return json.dumps([asdict(result) for result in results], indent=2, sort_keys=True)


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML mapping from disk, returning an empty mapping for non-maps."""
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return payload if isinstance(payload, dict) else {}


def _read_json(path: Path) -> dict[str, Any]:
    """Read a JSON mapping from disk, returning an empty mapping for missing non-maps."""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _mapped_services(mapping: dict[str, Any], host: str) -> list[str]:
    """Return services assigned to a host in mapping order."""
    services: list[str] = []
    for item in mapping.get("abhaile", []) or []:
        if not isinstance(item, dict):
            continue
        host_services = item.get(host)
        if isinstance(host_services, list):
            services.extend(service for service in host_services if isinstance(service, str))
    return services


def _command(
    argv: list[str],
    *,
    timeout_seconds: int,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a bounded command and capture its output for health diagnostics."""
    return subprocess.run(
        argv,
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def _service_yaml(config_root: Path, service: str) -> dict[str, Any]:
    """Read a service definition if it exists."""
    path = config_root / "services" / service / "service.yaml"
    if not path.exists():
        return {}
    return _read_yaml(path)


def _service_rootless_user(config_root: Path, service: str) -> str | None:
    """Return the podman user when a service is configured for rootless execution."""
    service_data = _service_yaml(config_root, service)
    podman = service_data.get("podman")
    if not isinstance(podman, dict):
        return None

    user = podman.get("user")
    if not isinstance(user, str) or not user:
        return None

    rootless_value = podman.get("rootless")
    if isinstance(rootless_value, bool):
        return user if rootless_value else None

    return user if user != "root" else None


def _rootless_users_for_services(config_root: Path, services: list[str]) -> list[str]:
    """Return unique rootless runtime users for mapped services."""
    users = {
        user
        for service in services
        if (user := _service_rootless_user(config_root, service)) is not None
    }
    return sorted(users)


def _strip_cidr(address: str) -> str:
    """Remove a CIDR suffix from an address string."""
    return address.split("/", 1)[0]


def _check_required_addresses(
    host: str,
    services: list[str],
    config_root: Path,
    network: dict[str, Any],
) -> list[HealthResult]:
    """Check that configured host and service addresses exist locally."""
    results: list[HealthResult] = []
    expected: list[str] = []
    hosts = network.get("hosts", {})
    if isinstance(hosts, dict):
        host_payload = hosts.get(host, {})
        interfaces = host_payload.get("interfaces", {}) if isinstance(host_payload, dict) else {}
        if isinstance(interfaces, dict):
            for payload in interfaces.values():
                if isinstance(payload, dict) and isinstance(payload.get("address"), str):
                    expected.append(payload["address"])

    network_services = network.get("services", {})
    if isinstance(network_services, dict):
        for service in services:
            service_data = _service_yaml(config_root, service)
            systemd = service_data.get("systemd")
            if not (isinstance(systemd, dict) and systemd.get("network") == "service-32"):
                continue
            payload = network_services.get(service)
            if isinstance(payload, dict) and isinstance(payload.get("address"), str):
                expected.append(payload["address"])

    for address in sorted(set(expected)):
        ip = _strip_cidr(address)
        try:
            result = _command(["ip", "addr", "show", "to", ip], timeout_seconds=3)
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append(HealthResult(f"address:{address}", False, str(exc)))
            continue
        results.append(
            HealthResult(
                f"address:{address}",
                result.returncode == 0 and ip in result.stdout,
                result.stderr.strip() or result.stdout.strip(),
            )
        )
    return results


def _coredns_endpoints(network: dict[str, Any]) -> list[str]:
    """Return CoreDNS service endpoint IPs from network configuration."""
    services = network.get("services", {})
    if not isinstance(services, dict):
        return []
    endpoints: list[str] = []
    for name, payload in services.items():
        if not isinstance(name, str) or not name.startswith("coredns-"):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("address"), str):
            endpoints.append(_strip_cidr(payload["address"]))
    return sorted(endpoints)


def _internal_zones(network: dict[str, Any]) -> list[str]:
    """Return internally hosted DNS zones from network configuration."""
    dns = network.get("dns", {})
    zones = dns.get("zones", []) if isinstance(dns, dict) else []
    internal: list[str] = []
    for zone in zones:
        provider = zone.get("provider") if isinstance(zone, dict) else None
        if isinstance(provider, dict) and provider.get("type") == "internal":
            name = zone.get("name")
            if isinstance(name, str) and name:
                internal.append(name)
    return sorted(internal)


def _dig(server: str, qname: str, qtype: str, *, timeout_seconds: int) -> str:
    """Query a DNS server and return compact answer text."""
    try:
        result = _command(
            ["dig", f"@{server}", qname, qtype, "+short", "+time=2", "+tries=1"],
            timeout_seconds=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return "\n".join(line.strip() for line in result.stdout.splitlines() if line.strip())


def _check_coredns(
    network: dict[str, Any],
    *,
    timeout_seconds: int,
    include_cluster_consistency: bool,
) -> list[HealthResult]:
    """Check CoreDNS public resolution and authoritative zone answers."""
    results: list[HealthResult] = []
    endpoints = _coredns_endpoints(network)
    zones = _internal_zones(network)
    for endpoint in endpoints:
        public_answer = _dig(endpoint, "example.com.", "A", timeout_seconds=timeout_seconds)
        results.append(
            HealthResult(
                f"dns-public:{endpoint}",
                bool(public_answer),
                public_answer or "no public DNS answer",
            )
        )
        for zone in zones:
            soa = _dig(endpoint, zone, "SOA", timeout_seconds=timeout_seconds)
            ns = _dig(endpoint, zone, "NS", timeout_seconds=timeout_seconds)
            results.append(HealthResult(f"dns-soa:{endpoint}:{zone}", bool(soa), soa))
            results.append(HealthResult(f"dns-ns:{endpoint}:{zone}", bool(ns), ns))

    if not include_cluster_consistency:
        return results

    for zone in zones:
        soa_by_endpoint = {
            endpoint: _dig(endpoint, zone, "SOA", timeout_seconds=timeout_seconds)
            for endpoint in endpoints
        }
        non_empty_answers = [answer for answer in soa_by_endpoint.values() if answer]
        all_endpoints_answered = len(non_empty_answers) == len(endpoints)
        consistent_answers = len(set(non_empty_answers)) == 1 if non_empty_answers else False
        results.append(
            HealthResult(
                f"dns-soa-consistent:{zone}",
                all_endpoints_answered and consistent_answers,
                json.dumps(soa_by_endpoint, sort_keys=True),
            )
        )
    return results


def _check_system_units(
    manifest: dict[str, Any],
    *,
    timeout_seconds: int,
) -> list[HealthResult]:
    """Check required root-owned units discovered from the rendered manifest."""
    units: set[str] = set()
    entries = manifest.get("entries", [])
    if not isinstance(entries, list):
        return []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        owner_ref = entry.get("owner_ref")
        hints = entry.get("apply_hints")
        rootless = isinstance(hints, dict) and bool(hints.get("rootless"))
        if rootless or not isinstance(owner_ref, str) or not owner_ref.startswith("unit:"):
            continue
        unit = owner_ref.split(":", 1)[1]
        if kind in {"quadlet.container", "quadlet.pod"} and unit.endswith(".service"):
            units.add(unit)
        if kind == "systemd.unit" and unit in {"coredns.service", "vault.service"}:
            units.add(unit)

    results: list[HealthResult] = []
    for unit in sorted(units):
        try:
            result = _command(
                ["systemctl", "is-active", "--quiet", unit],
                timeout_seconds=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append(HealthResult(f"unit-active:{unit}", False, str(exc)))
            continue
        results.append(
            HealthResult(
                f"unit-active:{unit}",
                result.returncode == 0,
                result.stderr.strip() or result.stdout.strip(),
            )
        )
    return results


def _check_rootless_vault_agent(
    services: list[str],
    *,
    config_root: Path,
    timeout_seconds: int,
) -> list[HealthResult]:
    """Check the rootless Vault Agent user unit when mapped to the host."""
    if "vault-agent" not in services:
        return []

    run_as_user = _service_rootless_user(config_root, "vault-agent")
    if run_as_user is None:
        return []

    try:
        result = _command(
            [
                "systemctl",
                "--user",
                "-M",
                f"{run_as_user}@",
                "is-active",
                "--quiet",
                "vault-agent.service",
            ],
            timeout_seconds=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [HealthResult("rootless-unit-active:vault-agent.service", False, str(exc))]
    return [
        HealthResult(
            "rootless-unit-active:vault-agent.service",
            result.returncode == 0,
            result.stderr.strip() or result.stdout.strip(),
        )
    ]


def _check_failed_units(*, timeout_seconds: int, rootless_users: list[str]) -> list[HealthResult]:
    """Check system and rootless failed units without hiding unrelated failures."""
    results: list[HealthResult] = []
    try:
        system_failed = _command(
            ["systemctl", "--failed", "--plain", "--no-legend"],
            timeout_seconds=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        results.append(HealthResult("system-failed-units", False, str(exc)))
    else:
        results.append(
            HealthResult(
                "system-failed-units",
                system_failed.returncode == 0 and not system_failed.stdout.strip(),
                system_failed.stdout.strip() or system_failed.stderr.strip(),
            )
        )
    for rootless_user in sorted(set(rootless_users)):
        result_name = f"rootless-failed-units:{rootless_user}"
        try:
            user_failed = _command(
                [
                    "systemctl",
                    "--user",
                    "-M",
                    f"{rootless_user}@",
                    "--failed",
                    "--plain",
                    "--no-legend",
                ],
                timeout_seconds=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append(HealthResult(result_name, False, str(exc)))
            continue

        failed_lines = [
            line
            for line in user_failed.stdout.splitlines()
            if line.strip() and not line.split(None, 1)[0] == "podman.service"
        ]
        results.append(
            HealthResult(
                result_name,
                user_failed.returncode == 0 and not failed_lines,
                "\n".join(failed_lines) or user_failed.stderr.strip(),
            )
        )
    return results


def _check_secrets_ready(services: list[str]) -> list[HealthResult]:
    """Check that the Vault Agent readiness sentinel exists and readiness gate is active."""
    if "vault-agent" not in services:
        return []
    sentinel = _SECRETS_READY_SENTINEL
    try:
        if not sentinel.exists():
            return [HealthResult("secrets-ready-sentinel", False, "missing")]
        stat = sentinel.stat()
        if stat.st_size == 0:
            return [HealthResult("secrets-ready-sentinel", False, "empty")]
    except OSError as exc:
        return [HealthResult("secrets-ready-sentinel", False, str(exc))]

    try:
        result = _command(
            ["systemctl", "is-active", "--quiet", "abhaile-secrets-ready.service"],
            timeout_seconds=3,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [HealthResult("secrets-ready-sentinel", False, str(exc))]

    return [
        HealthResult(
            "secrets-ready-sentinel",
            result.returncode == 0,
            result.stderr.strip() or result.stdout.strip(),
        )
    ]


def _check_podman_health(*, timeout_seconds: int) -> list[HealthResult]:
    """Report unhealthy Podman containers when the Podman CLI is available."""
    try:
        result = _command(
            ["podman", "ps", "--filter", "health=unhealthy", "--format", "{{.Names}}"],
            timeout_seconds=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [HealthResult("podman-unhealthy-containers", False, str(exc))]
    unhealthy = result.stdout.strip()
    return [
        HealthResult(
            "podman-unhealthy-containers",
            result.returncode == 0 and not unhealthy,
            unhealthy or result.stderr.strip(),
        )
    ]
