"""Tests for abhaile-health CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from abhaile.cli import health as health_cli
from abhaile.health import HealthResult


class TestHealthCli:
    """Tests for health CLI argument handling and output."""

    def test_json_output_and_success_exit(
        self, tmp_path: Path, monkeypatch: Any, capsys: Any
    ) -> None:
        calls: list[dict[str, object]] = []

        def fake_audit(**kwargs: object) -> list[HealthResult]:
            calls.append(kwargs)
            return [HealthResult("dns-public:172.20.20.235", True, "93.184.216.34")]

        monkeypatch.setattr(health_cli, "get_repo_root", lambda _path: tmp_path)
        monkeypatch.setattr(
            health_cli,
            "load_paths",
            lambda _repo_root: {"output_root_default": (tmp_path / "state").as_posix()},
        )
        monkeypatch.setattr(health_cli, "run_health_audit", fake_audit)

        rc = health_cli.main(
            [
                "--host",
                "phobos",
                "--output",
                (tmp_path / "out").as_posix(),
                "--timeout",
                "9",
                "--json",
            ]
        )

        assert rc == 0
        assert calls == [
            {
                "host": "phobos",
                "output_root": tmp_path / "out",
                "repo_root": tmp_path,
                "timeout_seconds": 9,
            }
        ]
        assert json.loads(capsys.readouterr().out) == [
            {
                "detail": "93.184.216.34",
                "name": "dns-public:172.20.20.235",
                "success": True,
            }
        ]

    def test_text_output_and_failure_exit(
        self, tmp_path: Path, monkeypatch: Any, capsys: Any
    ) -> None:
        monkeypatch.setattr(health_cli, "get_repo_root", lambda _path: tmp_path)
        monkeypatch.setattr(
            health_cli,
            "load_paths",
            lambda _repo_root: {"output_root_default": (tmp_path / "state").as_posix()},
        )
        monkeypatch.setattr(
            health_cli,
            "run_health_audit",
            lambda **_kwargs: [
                HealthResult("unit-active:coredns.service", True),
                HealthResult("dns-soa-consistent:abhaile.home.arpa.", False, "mismatch"),
            ],
        )

        rc = health_cli.main(["--host", "deimos"])

        assert rc == 1
        assert capsys.readouterr().out.splitlines() == [
            "ok unit-active:coredns.service",
            "fail dns-soa-consistent:abhaile.home.arpa. detail=mismatch",
        ]
