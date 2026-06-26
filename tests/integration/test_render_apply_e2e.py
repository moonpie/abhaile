"""Integration tests for real-config render output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from abhaile.cli.render import load_and_validate, render_host
from abhaile.models.kinds import ALL_KINDS
from abhaile.plan.diff import plan_manifest_drift
from abhaile.utils.config import clear_config_cache
from abhaile.utils.paths import load_paths

pytestmark = [pytest.mark.integration, pytest.mark.slow]


class TestRenderApplyE2E:
    """Render phobos with real config, then plan drift against empty state."""

    def test_render_phobos_plan_drift(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Render phobos, feed manifest to plan_manifest_drift, validate kinds."""
        repo_root = Path(__file__).resolve().parents[2]
        if not (repo_root / "config" / "mapping.yaml").exists():
            pytest.skip("Real config not available")

        monkeypatch.setattr("abhaile.cli.render.validate_dns_serials", lambda *a, **kw: None)
        clear_config_cache()

        paths = load_paths(repo_root)
        validated = load_and_validate(repo_root, paths)

        manifest_path = render_host(
            "phobos",
            output_override=tmp_path,
            paths=paths,
            all_mode=False,
            repo_root=repo_root,
            mapping=validated.mapping,
            network=validated.network,
            host_services=validated.host_services,
        )

        assert manifest_path.exists()

        # Plan drift against empty applied state (all entries become writes)
        applied_path = tmp_path / "state" / "manifest.json"
        plan = plan_manifest_drift(manifest_path, applied_path)

        assert plan["summary"]["added"] > 0
        assert plan["summary"]["writes"] > 0

        manifest = json.loads(manifest_path.read_text())
        entries = manifest["entries"]
        assert len(entries) > 0

        invalid_kinds = {e["kind"] for e in entries} - ALL_KINDS
        assert invalid_kinds == set(), f"Unknown kinds: {invalid_kinds}"

    def test_render_migrated_host_systemd_units_for_phobos_and_deimos(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Render migrated host-owned units for phobos and deimos."""
        repo_root = Path(__file__).resolve().parents[2]
        if not (repo_root / "config" / "mapping.yaml").exists():
            pytest.skip("Real config not available")

        monkeypatch.setattr("abhaile.cli.render.validate_dns_serials", lambda *a, **kw: None)
        clear_config_cache()

        paths = load_paths(repo_root)
        validated = load_and_validate(repo_root, paths)

        manifests = {}
        for host in ("phobos", "deimos"):
            manifests[host] = render_host(
                host,
                output_override=tmp_path / host,
                paths=paths,
                all_mode=False,
                repo_root=repo_root,
                mapping=validated.mapping,
                network=validated.network,
                host_services=validated.host_services,
            )

        phobos_root = manifests["phobos"].parent
        deimos_root = manifests["deimos"].parent

        phobos_unseal = (
            phobos_root / "system/etc/systemd/system/abhaile-vault-unseal.service"
        ).read_text(encoding="utf-8")
        deimos_unseal = deimos_root / "system/etc/systemd/system/abhaile-vault-unseal.service"

        assert "After=vault.service network-online.target" in phobos_unseal
        assert "Wants=vault.service network-online.target" in phobos_unseal
        assert "ConditionPathExists=" not in phobos_unseal
        assert (
            "Environment=SOPS_AGE_KEY_FILE=/root/.config/sops/age/vault-unseal.keys.txt"
            in phobos_unseal
        )
        assert "Environment=UNSEAL_FILE=/opt/abhaile/secrets/phobos/vault-unseal.sops.yaml" in (
            phobos_unseal
        )
        assert "vault-bootstrap.sops.yaml" not in phobos_unseal
        assert "config/bootstrap/sealed" not in phobos_unseal
        assert not deimos_unseal.exists()
        assert not (deimos_root / "system/usr/local/lib/abhaile/tools/vault-unseal.sh").exists()

        phobos_networkd = phobos_root / "system/etc/systemd/network"
        deimos_networkd = deimos_root / "system/etc/systemd/network"
        for networkd_root in (phobos_networkd, deimos_networkd):
            networkd_content = "\n".join(
                path.read_text(encoding="utf-8")
                for path in sorted(networkd_root.rglob("*"))
                if path.is_file()
            )
            assert "DNS=172.20.20.235/32" not in networkd_content
            assert "DNS=172.20.20.236/32" not in networkd_content
            assert "PreferredSource=172.20.20.20/32" not in networkd_content
            assert "PreferredSource=172.20.100.20/32" not in networkd_content
            assert "DNS=172.20.20.235 172.20.20.236" in networkd_content

        phobos_chrony = (phobos_root / "services/chrony-a/etc/chrony/chrony.conf").read_text(
            encoding="utf-8"
        )
        deimos_chrony = (deimos_root / "services/chrony-b/etc/chrony/chrony.conf").read_text(
            encoding="utf-8"
        )
        assert "bindaddress 172.20.20.237/32" not in phobos_chrony
        assert "peer 172.20.20.238/32" not in phobos_chrony
        assert "bindaddress 172.20.20.238/32" not in deimos_chrony
        assert "peer 172.20.20.237/32" not in deimos_chrony
        assert "bindaddress 172.20.20.237" in phobos_chrony
        assert "peer 172.20.20.238 iburst" in phobos_chrony
        assert "bindaddress 172.20.20.238" in deimos_chrony
        assert "peer 172.20.20.237 iburst" in deimos_chrony

        caddy_dmz_quadlet = (
            phobos_root / "services/caddy-dmz/etc/containers/systemd/caddy-dmz.container"
        ).read_text(encoding="utf-8")
        assert "EnvironmentFile=/srv/vault/agent/out/caddy-dns-desec.env" in caddy_dmz_quadlet
        assert "EnvironmentFile=/etc/caddy/dns.env" not in caddy_dmz_quadlet

        for rendered_root, service_name in (
            (phobos_root, "coredns-filtered"),
            (deimos_root, "coredns-clean"),
        ):
            corefile = (rendered_root / f"services/{service_name}/etc/coredns/Corefile").read_text(
                encoding="utf-8"
            )
            assert "controller_url ${OMADA_URL}" in corefile
            assert "site ${OMADA_SITE}" in corefile
            assert "controller_url https://172.20.20.220:8043" not in corefile

        authelia_quadlet = (
            phobos_root / "services/authelia/etc/containers/systemd/authelia-app-authelia.container"
        ).read_text(encoding="utf-8")
        redis_quadlet = (
            phobos_root / "services/authelia/etc/containers/systemd/authelia-app-redis.container"
        ).read_text(encoding="utf-8")
        authelia_copy_unit = (
            phobos_root / "services/authelia/etc/systemd/system/authelia-config.service"
        ).read_text(encoding="utf-8")
        redis_copy_unit = (
            phobos_root / "services/authelia/etc/systemd/system/authelia-redis-conf.service"
        ).read_text(encoding="utf-8")

        assert "Requires=abhaile-secrets-ready.service authelia-redis-conf.service" in (
            redis_quadlet
        )
        assert (
            "Requires=abhaile-secrets-ready.service authelia-config.service "
            "authelia-app-redis.service"
        ) in authelia_quadlet
        assert (
            "ExecStartPost=/usr/bin/systemctl try-restart authelia-app-authelia.service"
            in authelia_copy_unit
        )
        assert "ExecStartPre=/usr/bin/install -d -m 0750 -o root -g root" in authelia_copy_unit
        assert (
            "ExecStartPost=/usr/bin/systemctl try-restart authelia-app-redis.service"
            in redis_copy_unit
        )
        assert "ExecStartPre=/usr/bin/install -d -m 0750 -o root -g root" in redis_copy_unit
        assert "Notify=healthy" in redis_quadlet
        assert "StopSignal=SIGTERM" in redis_quadlet
        assert "StopTimeout=60" in redis_quadlet

        omada_rebuild = (
            phobos_root
            / "services/omada-controller/usr/local/lib/abhaile/tools/rebuild-omada-cert.sh"
        )
        assert omada_rebuild.exists()
        omada_rebuild_content = omada_rebuild.read_text(encoding="utf-8")
        assert 'OMADA_ENV="${OMADA_ENV:-/etc/omada-controller/omada-controller.env}"' in (
            omada_rebuild_content
        )
        assert (
            'OUT_DIR="${OUT_DIR:-/srv/omada-controller/omada-controller/cert}"'
            in omada_rebuild_content
        )
        assert "systemctl try-restart omada-controller-app-omada-controller.service" in (
            omada_rebuild_content
        )

        omada_service_root = phobos_root / "services/omada-controller/etc/containers/systemd"
        assert (omada_service_root / "omada-controller-app.pod").exists()
        omada_controller_container = (
            omada_service_root / "omada-controller-app-omada-controller.container"
        )
        omada_mongodb_container = omada_service_root / "omada-controller-app-mongodb.container"
        assert omada_controller_container.exists()
        assert (omada_service_root / "omada-controller-app-omada-controller.image").exists()
        assert omada_mongodb_container.exists()
        assert (omada_service_root / "omada-controller-app-mongodb.image").exists()
        omada_controller_content = omada_controller_container.read_text(encoding="utf-8")
        omada_mongodb_content = omada_mongodb_container.read_text(encoding="utf-8")
        assert "EnvironmentFile=/etc/omada-controller/omada-controller.env" in (
            omada_controller_content
        )
        assert "omada-controller-env.service" in omada_controller_content
        assert "omada-controller-app-mongodb.service" in omada_controller_content
        assert "EnvironmentFile=/etc/omada-controller/omada-mongodb.env" in (omada_mongodb_content)
        assert "omada-mongodb-env.service" in omada_mongodb_content
        assert "HealthCmd=" in omada_mongodb_content
        assert "Notify=healthy" in omada_mongodb_content
        assert "StopSignal=SIGTERM" in omada_mongodb_content
        assert "StopTimeout=60" in omada_mongodb_content
        assert "/docker-entrypoint-initdb.d/omada.js:ro" in omada_mongodb_content
        assert "Image=" in (
            omada_service_root / "omada-controller-app-omada-controller.image"
        ).read_text(encoding="utf-8")
        assert "Image=" in (omada_service_root / "omada-controller-app-mongodb.image").read_text(
            encoding="utf-8"
        )

        omada_init = (
            phobos_root / "services/omada-controller/srv/omada-controller/mongodb/initdb/omada.js"
        )
        assert omada_init.exists()
        omada_init_content = omada_init.read_text(encoding="utf-8")
        assert "process.env.OMADA_MONGODB_USERNAME" in omada_init_content
        assert "process.env.OMADA_MONGODB_PASSWORD" in omada_init_content

        omada_env_path = phobos_root / "services/omada-controller/etc/systemd/system"
        assert not (omada_env_path / "omada-mongodb-ready.service").exists()
        assert (omada_env_path / "omada-controller-env.path").exists()
        assert (omada_env_path / "omada-controller-env.service").exists()
        assert (omada_env_path / "omada-mongodb-env.path").exists()
        assert (omada_env_path / "omada-mongodb-env.service").exists()

        for rendered_root in (phobos_root, deimos_root):
            zone_root = (
                rendered_root / "services/coredns-clean/etc/coredns/zones"
                if rendered_root == deimos_root
                else rendered_root / "services/coredns-filtered/etc/coredns/zones"
            )
            zones_content = "\n".join(
                path.read_text(encoding="utf-8")
                for path in sorted(zone_root.glob("*.zone"))
                if path.is_file()
            )
            assert "ns1    IN CNAME" not in zones_content
            assert "ns2    IN CNAME" not in zones_content
            ns1_a = "ns1                      IN    A      172.20.20.235"
            ns2_a = "ns2                      IN    A      172.20.20.236"
            first_cname = "phobos                   IN    CNAME  phobos.svc.abhaile.home.arpa."
            assert ns1_a in zones_content
            assert ns2_a in zones_content
            assert zones_content.index(ns1_a) < zones_content.index(first_cname)
            assert zones_content.index(ns2_a) < zones_content.index(first_cname)
            assert "\n    10    IN PTR" not in zones_content
            assert "\n10                       IN    PTR    " in zones_content

        for rendered_root in (phobos_root, deimos_root):
            packages = (
                (rendered_root / "software/packages.txt").read_text(encoding="utf-8").splitlines()
            )
            assert "bind9-utils" in packages
            runner_unit = rendered_root / "system/etc/systemd/system/abhaile-runner.service"
            assert runner_unit.exists()
            assert "Environment=PATH=/opt/abhaile/.venv/bin:" in runner_unit.read_text(
                encoding="utf-8"
            )
            assert (rendered_root / "system/etc/systemd/system/abhaile-runner.timer").exists()
            vault_agent_unit = (
                rendered_root
                / "services/vault-agent/home/abhaile/.config/containers/systemd"
                / "vault-agent.container"
            )
            vault_agent_content = vault_agent_unit.read_text(encoding="utf-8")
            assert "After=network-online.target" in vault_agent_content
            assert "Wants=network-online.target" in vault_agent_content
            assert "abhaile-vault-unseal.service" not in vault_agent_content
            assert (
                "Volume=/home/abhaile/.config/vault-agent/role-id:/agent/role-id:ro"
                in vault_agent_content
            )
            assert (
                "Volume=/home/abhaile/.config/vault-agent/secret-id:/agent/secret-id:ro"
                in vault_agent_content
            )
            assert "/home/abhaile/.config/vault-agent/token:/agent/token" not in (
                vault_agent_content
            )

        phobos_entries = _entries_by_target(json.loads(manifests["phobos"].read_text()))
        deimos_entries = _entries_by_target(json.loads(manifests["deimos"].read_text()))

        for entries in (phobos_entries, deimos_entries):
            assert entries["/etc/systemd/system/abhaile-runner.service"]["kind"] == "systemd.unit"
            assert entries["/etc/systemd/system/abhaile-runner.timer"]["apply_hints"] == {
                "activation_mode": "start",
                "enable_mode": "enable",
            }

        assert phobos_entries["/etc/systemd/system/abhaile-vault-unseal.service"][
            "apply_hints"
        ] == {
            "activation_mode": "start",
            "enable_mode": "enable",
        }
        assert phobos_entries["/usr/local/lib/abhaile/tools/vault-unseal.sh"][
            "owner_ref"
        ].startswith("host:")
        assert "/etc/systemd/system/abhaile-vault-unseal.service" not in deimos_entries
        assert "/usr/local/lib/abhaile/tools/vault-unseal.sh" not in deimos_entries


def _entries_by_target(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index manifest entries by target path."""
    return {entry["target_path"]: entry for entry in manifest["entries"]}
