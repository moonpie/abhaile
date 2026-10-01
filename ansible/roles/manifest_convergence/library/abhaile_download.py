#!/usr/bin/python
"""Publish one bounded immutable HTTPS artifact for manifest convergence."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ansible.module_utils.basic import AnsibleModule

from abhaile.trust.download import DownloadPolicy, download_bytes, extract_zip_member
from abhaile.trust.errors import TrustError
from abhaile.trust.publication import file_matches, publish_file


def main() -> None:
    """Run the bounded download module."""
    module = AnsibleModule(
        argument_spec={
            "root": {"type": "path", "required": True},
            "url": {"type": "str", "required": True},
            "sha256": {"type": "str", "required": True},
            "destination": {"type": "path", "required": True},
            "mode": {"type": "str", "required": True},
            "uid": {"type": "int", "required": True},
            "gid": {"type": "int", "required": True},
            "max_bytes": {"type": "int", "required": True},
            "redirect_origins": {"type": "list", "elements": "str", "required": True},
            "max_redirects": {"type": "int", "required": True},
            "archive_member": {"type": "str"},
            "output_sha256": {"type": "str"},
            "max_member_bytes": {"type": "int"},
            "max_compression_ratio": {"type": "int"},
        },
        supports_check_mode=True,
    )
    try:
        policy = DownloadPolicy(
            module.params["url"],
            module.params["sha256"],
            module.params["max_bytes"],
            tuple(module.params["redirect_origins"]),
            module.params["max_redirects"],
        )
        member = module.params["archive_member"]
        output_sha256 = (
            module.params["sha256"] if member is None else module.params["output_sha256"]
        )
        if output_sha256 is None:
            module.fail_json(msg="Archive output digest authority is incomplete")
        root = Path(module.params["root"])
        mode = int(module.params["mode"], 8)
        if file_matches(
            root,
            module.params["destination"],
            sha256=output_sha256,
            uid=module.params["uid"],
            gid=module.params["gid"],
            mode=mode,
        ):
            module.exit_json(changed=False, action="unchanged", acquisition_verified=False)
        if module.check_mode:
            module.exit_json(changed=True, action="would-acquire", acquisition_verified=False)
        acquired = download_bytes(policy)
        if member is None:
            payload = acquired
        else:
            maximum = module.params["max_member_bytes"]
            ratio = module.params["max_compression_ratio"]
            if maximum is None or ratio is None:
                module.fail_json(msg="Archive extraction authority is incomplete")
            payload = extract_zip_member(
                acquired,
                member=member,
                max_member_bytes=maximum,
                max_compression_ratio=ratio,
            )
            if hashlib.sha256(payload).hexdigest() != output_sha256:
                module.fail_json(msg="Archive output digest is mismatched")
        result = publish_file(
            root,
            module.params["destination"],
            payload,
            sha256=output_sha256,
            uid=module.params["uid"],
            gid=module.params["gid"],
            mode=mode,
            check=False,
        )
    except (OSError, ValueError, TrustError):
        module.fail_json(msg="Immutable artifact convergence failed")
    module.exit_json(changed=result.changed, action=result.action, acquisition_verified=True)


if __name__ == "__main__":
    main()
