"""Register deterministic parents for managed files after explicit directory intent."""

from pathlib import Path, PurePosixPath

from abhaile.renderers.collector import ArtifactCollector
from abhaile.utils.errors import RenderError


def register_file_parents(collector: ArtifactCollector, rendered_root: Path) -> None:
    """Supply missing file parents while preserving explicit directory metadata."""
    artifacts = collector.get_all_artifacts()
    targets = {entry.target_path: entry for entry in artifacts}
    for entry in artifacts:
        if entry.is_directory:
            continue
        hints = entry.apply_hints or {}
        user = str(hints.get("podman_user", "root")) if hints.get("rootless") else "root"
        boundary = PurePosixPath(f"/home/{user}" if user != "root" else "/")
        parent = PurePosixPath(entry.target_path).parent
        immediate_parent = parent
        group = user
        mode = "0700" if user != "root" else "0755"
        if entry.kind == "host.authorized_keys":
            user = str(hints["owner_user"])
            group = str(hints["owner_group"])
            mode = "0700"
            boundary = parent.parent
        # Distribution-owned roots and account homes are prerequisites, not service metadata.
        stops = {PurePosixPath(p) for p in ("/", "/etc", "/srv", "/usr", "/var", "/run", "/home")}
        while parent not in stops and parent != boundary:
            target = str(parent)
            expected = {"owner": user, "group": group, "mode": mode}
            if parent != immediate_parent and not parent.is_relative_to(boundary):
                expected = {"owner": "root", "group": "root", "mode": "0755"}
            existing = targets.get(target)
            if existing is not None:
                if not existing.is_directory:
                    raise RenderError(f"Managed file occupies required directory: {target}")
                if (
                    existing.owner_ref == "host-directories:parents"
                    and existing.apply_hints != expected
                ):
                    raise RenderError(
                        f"Conflicting implicit directory metadata; declare shared intent: {target}"
                    )
                break
            render_path = "system/parents/" + target.lstrip("/")
            path = rendered_root / render_path
            path.mkdir(parents=True, exist_ok=True)
            artifact = collector.register_artifact(
                render_path=render_path,
                target_path=target,
                kind="service.directory",
                owner_ref="host-directories:parents",
                content="",
                is_directory=True,
                apply_hints=expected,
            )
            if "host-directories:parents" not in collector.get_all_owners():
                collector.register_owner(
                    "host-directories:parents", "Managed file parent directories"
                )
            targets[target] = artifact
            parent = parent.parent
