"""CLI entrypoint for abhaile-health."""

from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

from abhaile.cli.common import configure_logging
from abhaile.health import results_to_json, run_health_audit
from abhaile.utils.paths import get_repo_root, load_paths


def parse_health_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse arguments for abhaile-health."""
    parser = argparse.ArgumentParser(description="Audit local host health after apply")
    parser.add_argument("--output", help="Output root override")
    parser.add_argument("--host", help="Expected host name override")
    parser.add_argument("--timeout", type=int, default=5, help="Per-check timeout in seconds")
    parser.add_argument(
        "--cluster",
        action="store_true",
        help="Include cluster-consistency checks (cross-node DNS SOA consistency)",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON results")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run abhaile-health."""
    args = parse_health_args(argv)
    configure_logging(args.verbose)
    repo_root = get_repo_root(Path(__file__))
    paths = load_paths(repo_root)
    output_root = Path(args.output).resolve() if args.output else Path(paths["output_root_default"])
    host = args.host or socket.gethostname().split(".", 1)[0]

    results = run_health_audit(
        host=host,
        output_root=output_root,
        repo_root=repo_root,
        timeout_seconds=args.timeout,
        cluster=args.cluster,
    )
    failed = [result for result in results if not result.success]
    if args.json:
        print(results_to_json(results))
    else:
        for result in results:
            status = "ok" if result.success else "fail"
            suffix = f" detail={result.detail}" if result.detail else ""
            print(f"{status} {result.name}{suffix}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
