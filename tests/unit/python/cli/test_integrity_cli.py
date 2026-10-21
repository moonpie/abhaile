"""Tests for the abhaile-integrity CLI entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abhaile.cli import integrity as integrity_cli
from abhaile.integrity import IntegrityResult


def test_integrity_cli_returns_boolean_audit_result(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    """Return zero only for a clean selected scope."""
    seen: list[tuple[Path, str]] = []

    def fake_audit(path: Path, scope: str, *, expected_host: str) -> IntegrityResult:
        seen.append((path, scope))
        assert expected_host == "test-host"
        return IntegrityResult("ordinary", 4, 0, 0, ())

    monkeypatch.setattr(integrity_cli, "audit_manifest", fake_audit)

    assert (
        integrity_cli.main(
            ["--output", str(tmp_path), "--scope", "ordinary", "--host", "test-host"]
        )
        == 0
    )
    assert seen == [(tmp_path / "rendered" / "manifest.json", "ordinary")]
    assert "entries=4" in capsys.readouterr().out


def test_integrity_cli_maps_uncertainty_to_nonzero(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    """Keep parse and execution uncertainty out of clean admission."""
    monkeypatch.setattr(
        integrity_cli,
        "audit_manifest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad manifest")),
    )

    assert integrity_cli.main(["--output", str(tmp_path), "--scope", "ordinary"]) == 1
    assert "integrity uncertainty" in capsys.readouterr().err
