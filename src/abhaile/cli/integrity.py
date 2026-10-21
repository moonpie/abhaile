"""CLI entrypoint for the read-only manifest-integrity auditor."""

from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path
from typing import cast

from abhaile.integrity import AuditScope, audit_manifest, result_to_json


def parse_integrity_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse arguments for abhaile-integrity."""
    parser = argparse.ArgumentParser(description="Audit rendered identities against live state")
    parser.add_argument("--output", required=True, help="Fresh render output root")
    parser.add_argument("--host", help="Expected manifest host")
    parser.add_argument(
        "--scope",
        required=True,
        choices=("ordinary", "enrollment-foundations"),
    )
    parser.add_argument("--json", action="store_true", help="Output JSON result")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the read-only integrity audit."""
    args = parse_integrity_args(argv)
    try:
        result = audit_manifest(
            Path(args.output).resolve() / "rendered" / "manifest.json",
            cast(AuditScope, args.scope),
            expected_host=args.host or socket.gethostname().split(".", 1)[0],
        )
    except ValueError as exc:
        print(f"integrity uncertainty: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(result_to_json(result))
    else:
        paths = ",".join(result.paths) or "none"
        print(
            f"scope={result.scope} entries={result.entries} drift={result.drift} "
            f"uncertainty={result.uncertainty} paths={paths}"
        )
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
