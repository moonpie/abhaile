"""Canonical placeholder resolution helpers.

Handles strings containing %%path.to.value%% markers with optional filters.
Reuses the same behavior across service rendering and DNS builders to avoid
silent fallbacks.
"""

from __future__ import annotations

from typing import Any

from .errors import RenderError
from .context_utils import strip_cidr

SUPPORTED_FILTERS = {"strip_cidr"}


def _resolve_path(path_expr: str, ctx: dict[str, Any]) -> Any:
    """Resolve a dotted path like ``services.coredns.address`` from ctx.

    Args:
        path_expr: Dot-delimited path string (no surrounding %% markers).
        ctx: Context dictionary to traverse.

    Returns:
        Resolved value from the context.

    Raises:
        RenderError: If any segment is missing or traversal fails.
    """

    obj: Any = ctx
    parts = [p for p in path_expr.split(".") if p]
    idx = 0
    while idx < len(parts):
        part = parts[idx]
        # Support keys that themselves contain dots (e.g., "enp0s31f6.100") by
        # combining the current and next token when present in the context.
        key = part
        if isinstance(obj, dict) and idx + 1 < len(parts):
            combined = f"{part}.{parts[idx + 1]}"
            if combined in obj:
                key = combined
                idx += 1  # consume an extra token

        if not isinstance(obj, dict):
            raise RenderError(
                f"Failed to resolve placeholder '{path_expr}': '{key}' not in context"
            )
        if key not in obj:
            raise RenderError(
                f"Failed to resolve placeholder '{path_expr}': missing key '{key}'"
            )
        obj = obj[key]
        idx += 1
    return obj


def _apply_filters(value: Any, filters: list[str], path_expr: str) -> Any:
    """Apply supported filters to a resolved value."""

    for filt in filters:
        if not filt:
            continue
        if filt not in SUPPORTED_FILTERS:
            raise RenderError(
                f"Failed to resolve placeholder '{path_expr}': unsupported filter '{filt}'"
            )
        if filt == "strip_cidr":
            if value is not None and not isinstance(value, str):
                raise RenderError(
                    f"Failed to resolve placeholder '{path_expr}': strip_cidr requires string values"
                )
            try:
                value = strip_cidr(value)
            except Exception as exc:  # pragma: no cover - defensive
                raise RenderError(
                    f"Failed to resolve placeholder '{path_expr}': strip_cidr error: {exc}"
                ) from exc
    return value


def resolve_placeholders(value: str, ctx: dict[str, Any], *, max_depth: int = 8) -> str:
    """Replace all %%...%% placeholders in a string using ctx.

    Supports multiple placeholders per string and nested placeholder outputs.
    Fails fast on missing keys, unsupported filters, or circular references.

    Args:
        value: Input string that may contain %%...%% markers.
        ctx: Context dictionary used for lookup.
        max_depth: Maximum resolution passes to guard against circular refs.

    Returns:
        String with all placeholders replaced.

    Raises:
        RenderError: On unresolved paths, bad filters, or circular references.
    """

    if not isinstance(value, str) or "%%" not in value:
        return value

    rendered = value
    depth = 0
    while "%%" in rendered:
        if depth >= max_depth:
            raise RenderError(
                f"Failed to resolve placeholder in '{value}': possible circular reference"
            )

        start = rendered.find("%%")
        end = rendered.find("%%", start + 2)
        if end == -1:
            # Unmatched marker; leave string as-is
            return rendered

        inner = rendered[start + 2 : end].strip()
        path, *filters = [p.strip() for p in inner.split("|")]

        resolved = _resolve_path(path, ctx)
        resolved = _apply_filters(resolved, filters, path)

        rendered = f"{rendered[:start]}{resolved}{rendered[end + 2:]}"
        depth += 1

    return rendered
