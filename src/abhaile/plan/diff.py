"""Diff planning for desired, applied, and live host state."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from abhaile.utils.hashing import sha256_file
from abhaile.utils.errors import DiffError

LOG = logging.getLogger(__name__)


class SyncPlan(TypedDict):
    """Classified file operations from manifest comparison."""

    writes: list[dict[str, Any]]
    removals_safe: list[dict[str, Any]]
    removals_drifted: list[dict[str, Any]]
    removals_missing: list[dict[str, Any]]


class DiffSummary(TypedDict):
    """High-level diff counts."""

    added: int
    changed: int
    removed: int
    writes: int
    removals_safe: int
    removals_drifted: int
    removals_missing: int
    owner_plan_changed_owners: int
    owner_plan_expanded_owners: int


class PlanResult(TypedDict):
    """Return type for plan_manifest_drift."""

    host: str
    desired_manifest_path: str
    applied_manifest_path: str
    applied_manifest_exists: bool
    desired_manifest: dict[str, Any]
    diff: dict[str, list[dict[str, Any]]]
    sync: SyncPlan
    owner_plan: dict[str, Any]
    networkd_netdev_delete_order: list[str]
    quadlet_convergence_plans: dict[str, list[dict[str, str]]]
    summary: DiffSummary


NON_REGULAR_LIVE_FILE = "__NON_REGULAR__"


@dataclass(frozen=True)
class LoadedManifest:
    """Validated manifest payload plus source path metadata."""

    host: str
    entries: list[dict[str, Any]]
    owners: dict[str, dict[str, Any]]
    raw: dict[str, Any]


def _load_manifest(path: Path, *, allow_missing: bool, default_host: str = "") -> LoadedManifest:
    """Load and minimally validate a manifest file."""
    if not path.exists():
        if allow_missing:
            return LoadedManifest(
                host=default_host,
                entries=[],
                owners={},
                raw={"version": "1", "host": default_host, "entries": []},
            )
        raise DiffError(f"Missing manifest: {path}")

    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        raise DiffError(f"Failed to read manifest: {path} ({exc})") from exc

    if not isinstance(payload, dict):
        raise DiffError(f"Manifest must be a JSON object: {path}")

    host = payload.get("host")
    entries = payload.get("entries")
    version = payload.get("version")
    owners = payload.get("owners", {})
    if version != "1":
        raise DiffError(f"Manifest has unsupported or missing version: {path}")
    if not isinstance(host, str) or not host:
        raise DiffError(f"Manifest missing required 'host' string: {path}")
    if not isinstance(entries, list):
        raise DiffError(f"Manifest missing required 'entries' list: {path}")
    if not isinstance(owners, dict):
        raise DiffError(f"Manifest 'owners' must be an object when present: {path}")

    validated_entries: list[dict[str, Any]] = []
    for item in entries:
        if not isinstance(item, dict):
            raise DiffError(f"Manifest entry must be an object: {path}")

        target_path = item.get("target_path")
        sha256 = item.get("sha256")
        render_path = item.get("render_path")
        kind = item.get("kind")
        owner_ref = item.get("owner_ref")
        size = item.get("size")
        contributor_ref = item.get("contributor_ref")
        apply_hints = item.get("apply_hints")
        is_directory = item.get("is_directory")
        if not isinstance(target_path, str) or not target_path:
            raise DiffError(f"Manifest entry missing target_path: {path}")
        if not isinstance(sha256, str) or len(sha256) != 64:
            raise DiffError(f"Manifest entry has invalid sha256: {path} target={target_path}")
        if not isinstance(render_path, str) or not render_path:
            raise DiffError(f"Manifest entry missing render_path: {path} target={target_path}")
        if not isinstance(kind, str) or not kind:
            raise DiffError(f"Manifest entry missing kind: {path} target={target_path}")
        if not isinstance(owner_ref, str) or not owner_ref:
            raise DiffError(f"Manifest entry missing owner_ref: {path} target={target_path}")
        if not isinstance(size, int) or size < 0:
            raise DiffError(f"Manifest entry has invalid size: {path} target={target_path}")
        if contributor_ref is not None and (
            not isinstance(contributor_ref, str) or not contributor_ref
        ):
            raise DiffError(
                f"Manifest entry has invalid contributor_ref: {path} target={target_path}"
            )
        if apply_hints is not None and not isinstance(apply_hints, dict):
            raise DiffError(f"Manifest entry has invalid apply_hints: {path} target={target_path}")
        if is_directory is not None and not isinstance(is_directory, bool):
            raise DiffError(f"Manifest entry has invalid is_directory: {path} target={target_path}")
        if not Path(target_path).is_absolute():
            raise DiffError(f"Manifest target_path must be absolute: {path} target={target_path}")

        validated_entries.append(item)

    validated_owners: dict[str, dict[str, Any]] = {}
    for owner_name, owner_payload in owners.items():
        if not isinstance(owner_name, str) or not owner_name:
            raise DiffError(f"Manifest owner key must be a non-empty string: {path}")
        if not isinstance(owner_payload, dict):
            raise DiffError(f"Manifest owner '{owner_name}' must be an object: {path}")

        name = owner_payload.get("name")
        description = owner_payload.get("description")
        requires = owner_payload.get("requires")
        owner_apply_hints = owner_payload.get("apply_hints")

        if name != owner_name:
            raise DiffError(f"Manifest owner '{owner_name}' has mismatched or missing name: {path}")
        if description is not None and not isinstance(description, str):
            raise DiffError(f"Manifest owner '{owner_name}' has invalid description: {path}")
        if requires is not None and not (
            isinstance(requires, list) and all(isinstance(item, str) and item for item in requires)
        ):
            raise DiffError(f"Manifest owner '{owner_name}' has invalid requires: {path}")
        if owner_apply_hints is not None and not isinstance(owner_apply_hints, dict):
            raise DiffError(f"Manifest owner '{owner_name}' has invalid apply_hints: {path}")

        validated_owners[owner_name] = owner_payload

    return LoadedManifest(
        host=host, entries=validated_entries, owners=validated_owners, raw=payload
    )


def _live_file_sha256(target_path: str) -> str | None:
    """Return live file sha256 for a regular file; None for missing paths."""
    path = Path(target_path)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        return NON_REGULAR_LIVE_FILE
    try:
        return sha256_file(path)
    except OSError as exc:
        raise DiffError(f"Failed to hash live file: {target_path} ({exc})") from exc


def _index_entries(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index manifest entries by target_path and enforce uniqueness."""
    by_target: dict[str, dict[str, Any]] = {}
    for entry in entries:
        target_path = entry["target_path"]
        if target_path in by_target:
            raise DiffError(f"Duplicate target_path in manifest: {target_path}")
        by_target[target_path] = entry
    return by_target


def _owner_requires_map(owners: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Build normalized owner dependency map."""
    requires_by_owner: dict[str, list[str]] = {}
    for owner_ref, payload in owners.items():
        requires = payload.get("requires", [])
        if isinstance(requires, list):
            normalized = sorted({item for item in requires if isinstance(item, str) and item})
        else:
            normalized = []
        requires_by_owner[owner_ref] = normalized
    return requires_by_owner


def _owner_dependents_map(owners: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Build reverse owner dependency map keyed by prerequisite owner."""
    dependents_by_owner: dict[str, set[str]] = {}
    requires_by_owner = _owner_requires_map(owners)
    for owner_ref, requires in requires_by_owner.items():
        dependents_by_owner.setdefault(owner_ref, set())
        for dep in requires:
            dependents_by_owner.setdefault(dep, set()).add(owner_ref)
    return {owner_ref: sorted(dependents) for owner_ref, dependents in dependents_by_owner.items()}


def _expand_dependent_closure(
    initial: set[str],
    dependents_by_owner: dict[str, list[str]],
) -> set[str]:
    """Expand transitive reverse-dependency closure from changed owners."""
    expanded = set(initial)
    stack = list(initial)
    while stack:
        owner_ref = stack.pop()
        for dependent in dependents_by_owner.get(owner_ref, []):
            if dependent in expanded:
                continue
            expanded.add(dependent)
            stack.append(dependent)
    return expanded


def _owner_kind_map(entries: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Build mapping of owner_ref to sorted artifact kinds across manifests."""
    kinds_by_owner: dict[str, set[str]] = {}
    for entry in entries:
        owner_ref = entry.get("owner_ref")
        kind = entry.get("kind")
        if not isinstance(owner_ref, str) or not owner_ref:
            continue
        if not isinstance(kind, str) or not kind:
            continue
        kinds_by_owner.setdefault(owner_ref, set()).add(kind)
    return {owner_ref: sorted(kinds) for owner_ref, kinds in kinds_by_owner.items()}


def _expand_owner_closure(
    initial: set[str],
    requires_by_owner: dict[str, list[str]],
) -> set[str]:
    """Expand affected owners through transitive requires edges."""
    expanded = set(initial)
    stack = list(initial)
    while stack:
        owner_ref = stack.pop()
        for dep in requires_by_owner.get(owner_ref, []):
            if dep in expanded:
                continue
            expanded.add(dep)
            stack.append(dep)
    return expanded


def _toposort_owners(
    owners: set[str],
    requires_by_owner: dict[str, list[str]],
) -> list[str]:
    """Topologically sort owners so dependencies are ordered first."""
    ordered: list[str] = []
    permanent: set[str] = set()
    visiting: set[str] = set()

    def visit(owner_ref: str) -> None:
        if owner_ref in permanent:
            return
        if owner_ref in visiting:
            raise DiffError(f"Owner dependency cycle detected at: {owner_ref}")

        visiting.add(owner_ref)
        for dep in sorted(requires_by_owner.get(owner_ref, [])):
            if dep in owners:
                visit(dep)
        visiting.remove(owner_ref)
        permanent.add(owner_ref)
        ordered.append(owner_ref)

    for owner_ref in sorted(owners):
        visit(owner_ref)

    return ordered


def _build_owner_plan(
    *,
    writes: list[dict[str, Any]],
    removals_safe: list[dict[str, Any]],
    removals_drifted: list[dict[str, Any]],
    removals_missing: list[dict[str, Any]],
    desired_by_target: dict[str, dict[str, Any]],
    applied_by_target: dict[str, dict[str, Any]],
    owners: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Group changed entries by owner and order by owner dependencies."""
    owner_changes: dict[str, dict[str, list[dict[str, Any]]]] = {}

    def ensure_owner(owner_ref: str) -> None:
        owner_changes.setdefault(
            owner_ref,
            {
                "writes": [],
                "removals_safe": [],
                "removals_drifted": [],
                "removals_missing": [],
            },
        )

    for action in writes:
        target_path = action["target_path"]
        desired_entry = desired_by_target[target_path]
        owner_ref = desired_entry["owner_ref"]
        ensure_owner(owner_ref)
        owner_changes[owner_ref]["writes"].append(action)

    for category, removals in (
        ("removals_safe", removals_safe),
        ("removals_drifted", removals_drifted),
        ("removals_missing", removals_missing),
    ):
        for removal in removals:
            target_path = removal["target_path"]
            applied_entry = applied_by_target[target_path]
            owner_ref = applied_entry["owner_ref"]
            ensure_owner(owner_ref)
            owner_changes[owner_ref][category].append(removal)

    direct_owners = set(owner_changes.keys())
    requires_by_owner = _owner_requires_map(owners)
    expanded_owners = _expand_owner_closure(direct_owners, requires_by_owner)
    for owner_ref in expanded_owners:
        requires_by_owner.setdefault(owner_ref, [])

    ordered_owners = _toposort_owners(expanded_owners, requires_by_owner)

    owner_bundles: list[dict[str, Any]] = []
    for owner_ref in ordered_owners:
        changes = owner_changes.get(
            owner_ref,
            {
                "writes": [],
                "removals_safe": [],
                "removals_drifted": [],
                "removals_missing": [],
            },
        )
        known_owner = owner_ref in owners
        escalations: list[str] = []
        if changes["removals_drifted"]:
            escalations.append("prune-drifted")
        if not known_owner:
            escalations.append("missing-owner-metadata")

        owner_bundles.append(
            {
                "owner_ref": owner_ref,
                "requires": requires_by_owner.get(owner_ref, []),
                "changed": bool(
                    changes["writes"]
                    or changes["removals_safe"]
                    or changes["removals_drifted"]
                    or changes["removals_missing"]
                ),
                "writes": sorted(changes["writes"], key=lambda item: item["target_path"]),
                "removals_safe": sorted(
                    changes["removals_safe"],
                    key=lambda item: item["target_path"],
                ),
                "removals_drifted": sorted(
                    changes["removals_drifted"],
                    key=lambda item: item["target_path"],
                ),
                "removals_missing": sorted(
                    changes["removals_missing"],
                    key=lambda item: item["target_path"],
                ),
                "validation_actions": [],
                "runtime_actions": [],
                "escalations": escalations,
            }
        )

    return {
        "owners": owner_bundles,
        "summary": {
            "direct_owners": len(direct_owners),
            "expanded_owners": len(expanded_owners),
            "changed_owners": sum(1 for bundle in owner_bundles if bundle["changed"]),
        },
    }


def _build_networkd_netdev_delete_order(
    *,
    removals_safe: list[dict[str, Any]],
    removals_drifted: list[dict[str, Any]],
    owners: dict[str, dict[str, Any]],
) -> list[str]:
    """Build child-first owner order for removed networkd.netdev interfaces."""
    netdev_owner_refs: set[str] = set()
    for removal in [*removals_safe, *removals_drifted]:
        kind = removal.get("kind")
        owner_ref = removal.get("owner_ref")
        if kind != "networkd.netdev":
            continue
        if isinstance(owner_ref, str) and owner_ref:
            netdev_owner_refs.add(owner_ref)

    if not netdev_owner_refs:
        return []

    requires_by_owner = _owner_requires_map(owners)
    for owner_ref in netdev_owner_refs:
        requires_by_owner.setdefault(owner_ref, [])

    parent_first = _toposort_owners(netdev_owner_refs, requires_by_owner)
    return list(reversed(parent_first))


def _build_quadlet_convergence_plans(
    *,
    writes: list[dict[str, Any]],
    removals_safe: list[dict[str, Any]],
    removals_drifted: list[dict[str, Any]],
    owners: dict[str, dict[str, Any]],
    owner_kinds: dict[str, list[str]],
) -> dict[str, list[dict[str, str]]]:
    """Build per-owner stop/start plans for changed quadlet network/volume owners."""
    primary_owner_refs: set[str] = set()
    for action in [*writes, *removals_safe, *removals_drifted]:
        kind = action.get("kind")
        owner_ref = action.get("owner_ref")
        if kind not in {"quadlet.network", "quadlet.volume"}:
            continue
        if isinstance(owner_ref, str) and owner_ref:
            primary_owner_refs.add(owner_ref)

    if not primary_owner_refs:
        return {}

    dependents_by_owner = _owner_dependents_map(owners)
    raw_runtime_dependents: dict[str, list[str]] = {}

    for owner_ref in sorted(primary_owner_refs):
        dependents = _expand_dependent_closure({owner_ref}, dependents_by_owner)
        dependents.discard(owner_ref)
        runtime_dependents = sorted(
            dependent
            for dependent in dependents
            if "quadlet.container" in owner_kinds.get(dependent, [])
        )
        raw_runtime_dependents[owner_ref] = runtime_dependents

    plans: dict[str, list[dict[str, str]]] = {
        owner_ref: [] for owner_ref in sorted(primary_owner_refs)
    }
    primary_owners_by_dependent: dict[str, list[str]] = {}
    for owner_ref, runtime_dependents in raw_runtime_dependents.items():
        for dependent in runtime_dependents:
            primary_owners_by_dependent.setdefault(dependent, []).append(owner_ref)

    for dependent, primary_owners in sorted(primary_owners_by_dependent.items()):
        ordered_primary_owners = sorted(set(primary_owners))
        first_owner = ordered_primary_owners[0]
        last_owner = ordered_primary_owners[-1]
        plans[first_owner].append({"owner_ref": dependent, "action": "stop"})
        plans[last_owner].append({"owner_ref": dependent, "action": "start"})

    for owner_ref in list(plans.keys()):
        if not plans[owner_ref]:
            plans.pop(owner_ref)
            continue
        plans[owner_ref] = sorted(
            plans[owner_ref],
            key=lambda item: (item["action"] != "stop", item["owner_ref"]),
        )

    return plans


def plan_manifest_drift(rendered_manifest_path: Path, applied_manifest_path: Path) -> PlanResult:
    """Compare desired and applied manifests and classify live drift."""
    desired = _load_manifest(rendered_manifest_path, allow_missing=False)
    applied = _load_manifest(
        applied_manifest_path,
        allow_missing=True,
        default_host=desired.host,
    )

    LOG.debug(
        "plan.loaded desired_entries=%d applied_entries=%d",
        len(desired.entries),
        len(applied.entries),
    )

    if applied_manifest_path.exists() and applied.host != desired.host:
        raise DiffError(
            "State host mismatch: " f"desired host={desired.host} applied host={applied.host}"
        )

    desired_by_target = _index_entries(desired.entries)
    applied_by_target = _index_entries(applied.entries)

    merged_owners = dict(applied.owners)
    merged_owners.update(desired.owners)
    owner_kinds = _owner_kind_map([*applied.entries, *desired.entries])

    desired_targets = set(desired_by_target.keys())
    applied_targets = set(applied_by_target.keys())

    added_targets = sorted(desired_targets - applied_targets)
    removed_targets = sorted(applied_targets - desired_targets)
    common_targets = sorted(desired_targets & applied_targets)

    changed_targets = [
        target
        for target in common_targets
        if desired_by_target[target]["sha256"] != applied_by_target[target]["sha256"]
    ]

    added = [desired_by_target[target] for target in added_targets]
    changed = [
        {
            "target_path": target,
            "render_path": desired_by_target[target]["render_path"],
            "desired_sha256": desired_by_target[target]["sha256"],
            "applied_sha256": applied_by_target[target]["sha256"],
        }
        for target in changed_targets
    ]
    removed: list[dict[str, Any]] = []
    removals_safe: list[dict[str, Any]] = []
    removals_drifted: list[dict[str, Any]] = []
    removals_missing: list[dict[str, Any]] = []

    for target in removed_targets:
        applied_entry = applied_by_target[target]
        live_sha = _live_file_sha256(target)
        prune_safe = live_sha == applied_entry["sha256"]
        live_missing = live_sha is None
        removal = {
            "target_path": target,
            "render_path": applied_entry["render_path"],
            "kind": applied_entry["kind"],
            "owner_ref": applied_entry["owner_ref"],
            "apply_hints": applied_entry.get("apply_hints"),
            "applied_sha256": applied_entry["sha256"],
            "live_sha256": live_sha,
            "prune_safe": prune_safe,
            "live_missing": live_missing,
        }
        removed.append(removal)
        if live_missing:
            removals_missing.append(removal)
        elif prune_safe:
            removals_safe.append(removal)
        else:
            removals_drifted.append(removal)

    writes: list[dict[str, Any]] = []
    for target in sorted(desired_targets):
        desired_entry = desired_by_target[target]
        live_sha = _live_file_sha256(target)
        if live_sha == desired_entry["sha256"]:
            continue

        if live_sha is None:
            reason = "missing"
        elif target not in applied_by_target:
            reason = "add"
        elif applied_by_target[target]["sha256"] != desired_entry["sha256"]:
            reason = "change"
        else:
            reason = "drift"

        writes.append(
            {
                "target_path": target,
                "render_path": desired_entry["render_path"],
                "kind": desired_entry["kind"],
                "owner_ref": desired_entry["owner_ref"],
                "apply_hints": desired_entry.get("apply_hints"),
                "is_directory": desired_entry.get("is_directory", False),
                "desired_sha256": desired_entry["sha256"],
                "live_sha256": live_sha,
                "reason": reason,
            }
        )

    owner_plan = _build_owner_plan(
        writes=writes,
        removals_safe=removals_safe,
        removals_drifted=removals_drifted,
        removals_missing=removals_missing,
        desired_by_target=desired_by_target,
        applied_by_target=applied_by_target,
        owners=merged_owners,
    )
    networkd_netdev_delete_order = _build_networkd_netdev_delete_order(
        removals_safe=removals_safe,
        removals_drifted=removals_drifted,
        owners=merged_owners,
    )
    quadlet_convergence_plans = _build_quadlet_convergence_plans(
        writes=writes,
        removals_safe=removals_safe,
        removals_drifted=removals_drifted,
        owners=merged_owners,
        owner_kinds=owner_kinds,
    )

    return {
        "host": desired.host,
        "desired_manifest_path": rendered_manifest_path.as_posix(),
        "applied_manifest_path": applied_manifest_path.as_posix(),
        "applied_manifest_exists": applied_manifest_path.exists(),
        "desired_manifest": desired.raw,
        "diff": {
            "added": added,
            "changed": changed,
            "removed": removed,
        },
        "sync": {
            "writes": writes,
            "removals_safe": removals_safe,
            "removals_drifted": removals_drifted,
            "removals_missing": removals_missing,
        },
        "owner_plan": owner_plan,
        "networkd_netdev_delete_order": networkd_netdev_delete_order,
        "quadlet_convergence_plans": quadlet_convergence_plans,
        "summary": {
            "added": len(added),
            "changed": len(changed),
            "removed": len(removed),
            "writes": len(writes),
            "removals_safe": len(removals_safe),
            "removals_drifted": len(removals_drifted),
            "removals_missing": len(removals_missing),
            "owner_plan_changed_owners": owner_plan["summary"]["changed_owners"],
            "owner_plan_expanded_owners": owner_plan["summary"]["expanded_owners"],
        },
    }
