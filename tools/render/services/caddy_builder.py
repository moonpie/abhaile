"""Caddy Caddyfile rendering for ingress services."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_caddy_configs(
    hostname: str,
    deployed_services: list[str],
    services_meta: dict[str, Any],
    services_dir: Path,
) -> list[tuple[Path, str]]:
    """Build Caddyfile outputs (pure, no writes)."""

    outputs: list[tuple[Path, str]] = []

    caddy_services = [svc for svc in deployed_services if svc.startswith("caddy-")]
    if not caddy_services:
        return outputs

    for caddy_svc in caddy_services:
        ingress_type = caddy_svc.replace("caddy-", "")

        caddy_meta = services_meta.get(caddy_svc, {})
        caddy_ingress_entries = (caddy_meta.get("ingress", {}) or {}).get(
            ingress_type, []
        )

        base_content = ""
        destination = None
        if caddy_ingress_entries:
            for entry in caddy_ingress_entries:
                base_file = entry.get("base")
                dest_file = entry.get("destination")
                if base_file and dest_file:
                    candidates = [
                        services_dir / base_file,
                        services_dir / caddy_svc / base_file,
                    ]
                    base_path = next((p for p in candidates if p.exists()), None)
                    if base_path:
                        base_content = base_path.read_text()
                        destination = dest_file
                        break

        ingress_blocks: list[dict[str, str]] = []
        for svc in deployed_services:
            svc_meta = services_meta.get(svc, {})
            ingress_config = svc_meta.get("ingress", {}) or {}
            type_config = ingress_config.get(ingress_type, []) or []

            for block_entry in type_config:
                block_file = block_entry.get("block")
                if not block_file:
                    continue

                candidates = [
                    services_dir / block_file,
                    services_dir / svc / block_file,
                ]
                block_path = next((p for p in candidates if p.exists()), None)
                if block_path:
                    ingress_blocks.append(
                        {
                            "service": svc,
                            "content": block_path.read_text().rstrip(),
                        }
                    )

        if not base_content and not ingress_blocks:
            continue

        caddyfile_lines: list[str] = []
        if base_content:
            caddyfile_lines.append(base_content.rstrip())

        if ingress_blocks:
            if caddyfile_lines:
                caddyfile_lines.append("")
                caddyfile_lines.append("")
            caddyfile_lines.append("# ---------- Service Ingress Blocks ----------")
            caddyfile_lines.append("")
            for block in ingress_blocks:
                caddyfile_lines.append(block["content"])
                caddyfile_lines.append("")

        joined = "\n".join(caddyfile_lines)
        while joined.endswith("\n\n"):
            joined = joined[:-1]
        final_content = joined + "\n"

        rel_path = (
            Path("services") / caddy_svc / (destination or "Caddyfile").lstrip("/")
        )
        outputs.append((rel_path, final_content))

    return outputs


def render_caddy_configs(
    hostname: str,
    deployed_services: list[str],
    services_meta: dict[str, Any],
    services_dir: Path,
    out_dir: Path,
) -> None:
    """Compatibility wrapper that writes outputs from build_caddy_configs."""

    outputs = build_caddy_configs(
        hostname=hostname,
        deployed_services=deployed_services,
        services_meta=services_meta,
        services_dir=services_dir,
    )
    for rel_path, content in outputs:
        dest = out_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
