#!/usr/bin/python
"""Publish one manifest-authorized filesystem object without following ancestry links."""

from __future__ import annotations

from pathlib import Path
import subprocess

from ansible.module_utils.basic import AnsibleModule

from abhaile.trust.errors import TrustError
from abhaile.trust.publication import publish_directory, publish_file
from abhaile.trust.service_validation import (
    validate_caddyfile,
    validate_coredns_corefile,
    validate_resolved_config,
)


def _validate(module: AnsibleModule, source: Path, validation: str, zone: str | None) -> None:
    """Validate sealed input with a closed fixed-argv platform vocabulary."""
    if validation == "caddy":
        validate_caddyfile(source.read_bytes())
        return
    if validation == "coredns":
        validate_coredns_corefile(source.read_bytes())
        return
    if validation == "resolved":
        validate_resolved_config(source.read_bytes())
        return
    if validation == "structural":
        payload = source.read_bytes()
        if not payload or b"\x00" in payload:
            module.fail_json(msg="Structural validation failed")
        return
    commands = {
        "systemd": ["/usr/bin/systemd-analyze", "verify", str(source)],
        "sudoers": ["/usr/sbin/visudo", "-cf", str(source)],
        "sysusers": ["/usr/bin/systemd-sysusers", "--dry-run", str(source)],
        "vault-agent": ["/usr/bin/vault", "agent", f"-config={source}", "-verify-only"],
        "quadlet": ["/usr/libexec/podman/quadlet", "-dryrun"],
        "coredns-zone": ["/usr/bin/named-checkzone", zone, str(source)],
    }
    command = commands.get(validation)
    if command is None:
        module.fail_json(msg="Publication validator is unsupported")
    if validation == "coredns-zone" and zone is None:
        module.fail_json(msg="CoreDNS zone validation authority is incomplete")
    environment = {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    if validation == "quadlet":
        environment["QUADLET_UNIT_DIRS"] = str(source.parent)
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        module.fail_json(msg="Publication validator could not run")
    if completed.returncode != 0:
        module.fail_json(msg="Publication validation failed")


def main() -> None:
    """Execute descriptor-bound file or directory publication."""
    module = AnsibleModule(
        argument_spec={
            "root": {"type": "path", "required": True},
            "target": {"type": "path", "required": True},
            "state": {"type": "str", "choices": ["file", "directory"], "required": True},
            "source": {"type": "path"},
            "content": {"type": "str"},
            "sha256": {"type": "str"},
            "uid": {"type": "int", "required": True},
            "gid": {"type": "int", "required": True},
            "mode": {"type": "str", "required": True},
            "validation": {"type": "str", "default": "structural"},
            "zone": {"type": "str"},
            "validate_only": {"type": "bool", "default": False},
        },
        supports_check_mode=True,
    )
    try:
        mode = int(module.params["mode"], 8)
        if module.params["state"] == "directory":
            if (
                module.params["source"] is not None
                or module.params["content"] is not None
                or module.params["sha256"] is not None
            ):
                module.fail_json(msg="Directory publication received file authority")
            result = publish_directory(
                Path(module.params["root"]),
                module.params["target"],
                uid=module.params["uid"],
                gid=module.params["gid"],
                mode=mode,
                check=module.check_mode,
            )
        else:
            source = module.params["source"]
            content = module.params["content"]
            if (source is None) == (content is None) or module.params["sha256"] is None:
                module.fail_json(msg="File publication authority is incomplete")
            payload = Path(source).read_bytes() if source is not None else content.encode()
            if source is not None:
                _validate(module, Path(source), module.params["validation"], module.params["zone"])
            if module.params["validate_only"]:
                module.exit_json(changed=False, action="validated")
            result = publish_file(
                Path(module.params["root"]),
                module.params["target"],
                payload,
                sha256=module.params["sha256"],
                uid=module.params["uid"],
                gid=module.params["gid"],
                mode=mode,
                check=module.check_mode,
            )
    except (OSError, ValueError, TrustError):
        module.fail_json(msg="Protected publication failed")
    module.exit_json(changed=result.changed, action=result.action)


if __name__ == "__main__":
    main()
