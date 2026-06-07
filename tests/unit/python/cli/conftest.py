"""Shared fixtures for CLI tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def write_manifest():
    """Write a test manifest file with normalized entries."""

    def _write(
        path: Path,
        host: str,
        entries: list[dict[str, object]],
        *,
        owners: dict[str, dict[str, object]] | None = None,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized: list[dict[str, object]] = []
        for entry in entries:
            n = dict(entry)
            n.setdefault("kind", "service.config")
            n.setdefault("owner_ref", "service:test")
            normalized.append(n)
        payload: dict[str, object] = {
            "version": "1",
            "host": host,
            "entries": normalized,
        }
        if owners:
            payload["owners"] = owners
        path.write_text(json.dumps(payload, indent=2) + "\n")

    return _write
