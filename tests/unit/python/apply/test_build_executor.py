"""Unit tests for generic managed build transactions."""

from __future__ import annotations

from typing import Any

import pytest

from abhaile.apply.actions import ExecutionResult
from abhaile.apply.build import ManagedBuildExecutor
from abhaile.apply.quadlet import QuadletExecutor
from abhaile.utils.errors import ApplyError


def _build_action() -> dict[str, object]:
    """Return a representative CoreDNS managed build action."""
    return {
        "service": "coredns-omada",
        "scope": "rootful",
        "output_image": "localhost/coredns-omada:latest",
        "build_unit": "coredns-omada-build.service",
        "post_build": {
            "install_unit": "coredns-omada-install.service",
            "verify_binary": "/usr/local/bin/coredns",
        },
        "consumers": ["coredns.service"],
    }


class TestManagedBuildExecutor:
    """Tests for managed build transaction ordering."""

    def test_successful_build_verifies_output_before_post_build_and_consumer_restart(
        self, mocker: Any
    ) -> None:
        """Consumers should restart only after build output and post-build success."""
        calls: list[str] = []

        def fake_reload(**_kwargs: object) -> ExecutionResult:
            calls.append("reload")
            return ExecutionResult("reload", "systemctl", True, 0)

        def fake_verify_unit(unit: str, **_kwargs: object) -> ExecutionResult:
            calls.append(f"verify-unit:{unit}")
            return ExecutionResult("verify", "validation", True, 0, stdout="loaded\n")

        def fake_image_exists(image: str, **_kwargs: object) -> bool:
            calls.append(f"verify-image:{image}")
            return True

        mocker.patch.object(
            QuadletExecutor,
            "daemon_reload",
            side_effect=fake_reload,
        )
        mocker.patch.object(
            QuadletExecutor,
            "verify_generated_unit",
            side_effect=fake_verify_unit,
        )
        mocker.patch.object(
            QuadletExecutor,
            "image_exists",
            side_effect=fake_image_exists,
        )
        mocker.patch.object(
            QuadletExecutor,
            "inspect_image",
            return_value={"image": "localhost/coredns-omada:latest", "image_id": "sha256:abc"},
        )
        mocker.patch.object(
            ManagedBuildExecutor,
            "verify_file_executable",
            side_effect=lambda path: calls.append(f"verify-binary:{path}"),
        )

        def fake_systemctl(action: str, unit: str, **_kwargs: object) -> ExecutionResult:
            calls.append(f"{action}:{unit}")
            return ExecutionResult(f"{action}:{unit}", "systemctl", True, 0)

        mocker.patch("abhaile.apply.build.run_systemctl_command", side_effect=fake_systemctl)

        summary = ManagedBuildExecutor.run_transaction(_build_action())

        assert calls == [
            "reload",
            "verify-unit:coredns-omada-build.service",
            "start:coredns-omada-build.service",
            "verify-image:localhost/coredns-omada:latest",
            "start:coredns-omada-install.service",
            "verify-binary:/usr/local/bin/coredns",
            "restart:coredns.service",
        ]
        assert summary["result"] == "built"
        assert summary["actions"][3]["action"] == "verify-output-image"

    def test_build_failure_prevents_post_build_and_consumer_restart(self, mocker: Any) -> None:
        """A failed build unit should stop before post-build actions."""
        mocker.patch.object(
            QuadletExecutor,
            "daemon_reload",
            return_value=ExecutionResult("reload", "systemctl", True, 0),
        )
        mocker.patch.object(
            QuadletExecutor,
            "verify_generated_unit",
            return_value=ExecutionResult("verify", "validation", True, 0, stdout="loaded\n"),
        )
        mocker.patch(
            "abhaile.apply.build.run_systemctl_command",
            side_effect=ApplyError("build failed"),
        )
        mock_verify_image = mocker.patch.object(QuadletExecutor, "image_exists")
        mock_post = mocker.patch.object(ManagedBuildExecutor, "verify_file_executable")

        with pytest.raises(ApplyError, match="build failed"):
            ManagedBuildExecutor.run_transaction(_build_action())

        mock_verify_image.assert_not_called()
        mock_post.assert_not_called()

    def test_missing_output_image_prevents_post_build_and_consumer_restart(
        self, mocker: Any
    ) -> None:
        """Output image verification failure should stop before install and restarts."""
        calls: list[str] = []
        mocker.patch.object(
            QuadletExecutor,
            "daemon_reload",
            return_value=ExecutionResult("reload", "systemctl", True, 0),
        )
        mocker.patch.object(
            QuadletExecutor,
            "verify_generated_unit",
            return_value=ExecutionResult("verify", "validation", True, 0, stdout="loaded\n"),
        )

        def fake_systemctl(action: str, unit: str, **_kwargs: object) -> ExecutionResult:
            calls.append(f"{action}:{unit}")
            return ExecutionResult(f"{action}:{unit}", "systemctl", True, 0)

        mocker.patch("abhaile.apply.build.run_systemctl_command", side_effect=fake_systemctl)
        mocker.patch.object(QuadletExecutor, "image_exists", return_value=False)
        mock_post = mocker.patch.object(ManagedBuildExecutor, "verify_file_executable")

        with pytest.raises(ApplyError, match="output image"):
            ManagedBuildExecutor.run_transaction(_build_action())

        assert calls == ["start:coredns-omada-build.service"]
        mock_post.assert_not_called()

    def test_post_build_failure_prevents_consumer_restart(self, mocker: Any) -> None:
        """Failed post-build install should prevent consumer restarts."""
        calls: list[str] = []
        mocker.patch.object(
            QuadletExecutor,
            "daemon_reload",
            return_value=ExecutionResult("reload", "systemctl", True, 0),
        )
        mocker.patch.object(
            QuadletExecutor,
            "verify_generated_unit",
            return_value=ExecutionResult("verify", "validation", True, 0, stdout="loaded\n"),
        )
        mocker.patch.object(QuadletExecutor, "image_exists", return_value=True)
        mocker.patch.object(
            QuadletExecutor,
            "inspect_image",
            return_value={"image": "localhost/coredns-omada:latest", "image_id": "sha256:abc"},
        )

        def fake_systemctl(action: str, unit: str, **_kwargs: object) -> ExecutionResult:
            calls.append(f"{action}:{unit}")
            if unit == "coredns-omada-install.service":
                raise ApplyError("install failed")
            return ExecutionResult(f"{action}:{unit}", "systemctl", True, 0)

        mocker.patch("abhaile.apply.build.run_systemctl_command", side_effect=fake_systemctl)

        with pytest.raises(ApplyError, match="install failed"):
            ManagedBuildExecutor.run_transaction(_build_action())

        assert calls == [
            "start:coredns-omada-build.service",
            "start:coredns-omada-install.service",
        ]
