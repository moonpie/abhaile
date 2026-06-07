"""CLI entrypoint for abhaile-diff."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from abhaile.plan.diff import PlanResult, plan_manifest_drift
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


def _has_content_differences(plan: PlanResult | dict[str, Any]) -> bool:
    """Return True if the plan contains added, changed, or removed entries."""
    summary = plan.get("summary")
    if not isinstance(summary, dict):
        return False
    added = summary.get("added", 0)
    changed = summary.get("changed", 0)
    removed = summary.get("removed", 0)
    return bool(added or changed or removed)


def _detect_metadata_changes(
    plan: PlanResult | dict[str, Any], applied_path: Path
) -> list[dict[str, object]]:
    """Detect entries where sha256 matches but kind/owner_ref/apply_hints differ."""
    desired_manifest = plan.get("desired_manifest")
    if not isinstance(desired_manifest, dict):
        return []
    desired_entries = desired_manifest.get("entries")
    if not isinstance(desired_entries, list):
        return []

    if not applied_path.exists():
        return []

    try:
        with applied_path.open("r", encoding="utf-8") as fh:
            applied_data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []

    applied_entries = applied_data.get("entries")
    if not isinstance(applied_entries, list):
        return []

    applied_by_target: dict[str, dict[str, object]] = {}
    for entry in applied_entries:
        if isinstance(entry, dict) and isinstance(entry.get("target_path"), str):
            applied_by_target[entry["target_path"]] = entry

    metadata_changes: list[dict[str, object]] = []
    for entry in desired_entries:
        if not isinstance(entry, dict):
            continue
        target_path = entry.get("target_path")
        if not isinstance(target_path, str):
            continue
        applied_entry = applied_by_target.get(target_path)
        if applied_entry is None:
            continue
        if entry.get("sha256") != applied_entry.get("sha256"):
            continue
        diffs: dict[str, object] = {}
        for field in ("kind", "owner_ref", "apply_hints"):
            desired_val = entry.get(field)
            applied_val = applied_entry.get(field)
            if desired_val != applied_val:
                diffs[field] = {"desired": desired_val, "applied": applied_val}
        if diffs:
            metadata_changes.append({"target_path": target_path, "changes": diffs})

    return metadata_changes


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
    metadata_changes = _detect_metadata_changes(plan, applied_path)

    if args.json:
        output = dict(plan)
        output["metadata_changes"] = metadata_changes
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        print_diff_summary(plan)
        if metadata_changes:
            print(f"metadata_changes={len(metadata_changes)}")

    if _has_content_differences(plan):
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PipelineError as exc:
        print(f"diff: {exc}", file=sys.stderr)
        sys.exit(2)
