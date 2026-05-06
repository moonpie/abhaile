"""CLI entrypoint for abhaile-diff."""

from __future__ import annotations

import argparse
import json
import sys

from abhaile.plan.diff import plan_manifest_drift
from abhaile.cli.common import print_diff_summary, resolve_cli_paths
from abhaile.utils.errors import PipelineError


def parse_diff_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse arguments for abhaile-diff."""
    parser = argparse.ArgumentParser(description="Diff desired and applied manifests")
    parser.add_argument(
        "desired_manifest_positional", nargs="?", help="Desired rendered manifest path"
    )
    parser.add_argument(
        "applied_manifest_positional", nargs="?", help="Applied state manifest path"
    )
    parser.add_argument("--output", help="Output root override")
    parser.add_argument("--desired-manifest", help="Path to desired rendered manifest")
    parser.add_argument("--applied-manifest", help="Path to last applied manifest")
    parser.add_argument("--json", action="store_true", help="Print JSON diff output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run abhaile-diff."""
    args = parse_diff_args(argv)
    _, _, desired_path, applied_path = resolve_cli_paths(
        args.output,
        args.desired_manifest,
        args.applied_manifest,
        args.desired_manifest_positional,
        args.applied_manifest_positional,
    )
    plan = plan_manifest_drift(desired_path, applied_path)

    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))
    else:
        print_diff_summary(plan)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PipelineError as exc:
        print(f"diff: {exc}", file=sys.stderr)
        sys.exit(1)
