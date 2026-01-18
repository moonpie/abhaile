"""Software package configuration builder."""

from pathlib import Path
import yaml

from tools.common.core import load_yaml, get_logger

logger = get_logger(__name__)


def _merge_lists(base: list[str], extra: list[str]) -> list[str]:
    merged: list[str] = []
    for item in base + extra:
        if item not in merged:
            merged.append(item)
    return merged


def _load_action_defs(names: list[str], base_dir: Path, kind: str) -> dict[str, dict]:
    defs: dict[str, dict] = {}
    for name in names:
        path = base_dir / "software" / kind / f"{name}.yaml"
        if path.exists():
            defs[name] = load_yaml(path) or {}
    return defs


def _write_packages_script(packages: list[str], dest: Path) -> None:
    lines = [
        "#!/bin/bash",
        "# Generated package installation script for Debian/Ubuntu",
        "# This file is managed by the orchestrator - do not edit manually",
        "set -euo pipefail",
        "",
        "# Update package lists",
        "apt-get update",
        "",
        "# Install packages",
        "apt-get install -y \\",
    ]

    for idx, pkg in enumerate(packages):
        suffix = " \\" if idx < len(packages) - 1 else ""
        lines.append(f"  {pkg}{suffix}")

    lines.extend(
        [
            "",
            "# Clean up apt cache",
            "apt-get clean",
            "apt-get autoclean",
            "",
        ]
    )

    dest.write_text("\n".join(lines))
    dest.chmod(0o755)
    logger.info("Wrote package installer: %s", dest)


def _write_action_script(
    actions: list[str], action_defs: dict[str, dict], dest: Path, header: str
) -> None:
    if not actions:
        return

    lines = [
        "#!/bin/bash",
        header,
        "# This file is managed by the orchestrator - do not edit manually",
        "set -euo pipefail",
        "",
    ]

    for name in actions:
        meta = action_defs.get(name, {})
        title = meta.get("name", name)
        lines.append(f"echo '=== {title} ({name}) ==='")
        for cmd in meta.get("commands", []):
            lines.append(cmd)
        lines.append("")

    dest.write_text("\n".join(lines).rstrip() + "\n")
    dest.chmod(0o755)
    logger.info("Wrote action script: %s", dest)


def _write_software_md(
    output_dir: Path, merged: dict, action_defs: dict[str, dict], kind: str, title: str
) -> list[str]:
    lines: list[str] = [f"## {title}", ""]
    for name in merged.get(kind, []):
        meta = action_defs.get(name, {})
        friendly = meta.get("name", name)
        desc = meta.get("description")
        if desc:
            lines.append(f"- **{friendly}** (`{name}`) - {desc}")
        else:
            lines.append(f"- {friendly}")
    lines.append("")
    return lines


def build_software_configs(
    hostname: str,
    hosts_path: Path,
    output_path: Path,
) -> None:
    """Build software/package configuration for the host.

    Merges common + host software.yaml, writes combined manifest and helper
    scripts (packages, downloads, builds, commands) plus a short README.
    """
    common_file = hosts_path / "common" / "software.yaml"
    host_file = hosts_path / hostname / "software.yaml"

    if not common_file.exists() and not host_file.exists():
        return

    common = load_yaml(common_file) if common_file.exists() else {}
    host = load_yaml(host_file) if host_file.exists() else {}

    merged = {
        "packages": _merge_lists(common.get("packages", []), host.get("packages", [])),
        "downloads": _merge_lists(
            common.get("downloads", []), host.get("downloads", [])
        ),
        "builds": _merge_lists(common.get("builds", []), host.get("builds", [])),
        "commands": _merge_lists(common.get("commands", []), host.get("commands", [])),
    }

    output_dir = output_path / hostname / "software"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Combined software.yaml
    software_manifest = output_dir / "software.yaml"
    software_manifest.write_text(yaml.safe_dump(merged, sort_keys=False))
    logger.info("Wrote software manifest: %s", software_manifest)

    # Definitions for actions
    action_base = hosts_path
    download_defs = _load_action_defs(merged["downloads"], action_base, "downloads")
    build_defs = _load_action_defs(merged["builds"], action_base, "builds")
    command_defs = _load_action_defs(merged["commands"], action_base, "commands")

    # Scripts
    if merged["packages"]:
        _write_packages_script(merged["packages"], output_dir / "install-packages.sh")
    if merged["downloads"]:
        _write_action_script(
            merged["downloads"],
            download_defs,
            output_dir / "downloads.sh",
            "# Generated downloads execution script",
        )
    if merged["builds"]:
        _write_action_script(
            merged["builds"],
            build_defs,
            output_dir / "builds.sh",
            "# Generated builds execution script",
        )
    if merged["commands"]:
        _write_action_script(
            merged["commands"],
            command_defs,
            output_dir / "commands.sh",
            "# Generated commands execution script",
        )

    # SOFTWARE.md summary
    md_lines = [
        "# Software Plan (Generated)",
        "",
        "> This file is managed by the orchestrator - do not edit manually.",
        "",
    ]

    md_lines.append("## Packages (apt)")
    md_lines.append("")
    for pkg in merged["packages"]:
        md_lines.append(f"- {pkg}")
    md_lines.append("")

    if merged["downloads"]:
        md_lines.extend(
            _write_software_md(
                output_dir, merged, download_defs, "downloads", "Downloads"
            )
        )
    if merged["builds"]:
        md_lines.extend(
            _write_software_md(output_dir, merged, build_defs, "builds", "Builds")
        )
    if merged["commands"]:
        md_lines.extend(
            _write_software_md(output_dir, merged, command_defs, "commands", "Commands")
        )

    (output_dir / "SOFTWARE.md").write_text("\n".join(md_lines).rstrip() + "\n")
    logger.info("Wrote software summary: %s", output_dir / "SOFTWARE.md")
