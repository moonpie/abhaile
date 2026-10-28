"""Test device line generation without filesystem access."""

from typing import Any

import pytest

from abhaile.renderers.quadlets.volumes import _build_device_lines
from abhaile.utils.errors import RenderError


class TestDeviceLines:
    """Cover optional device entries and renderer-side validation."""

    @pytest.mark.parametrize("container", [{}, {"devices": []}])
    def test_no_devices(self, container: dict[str, Any]) -> None:
        """Emit no passthrough directives when no devices are configured."""
        assert _build_device_lines(container) == []

    @pytest.mark.parametrize("device", ["", None, 42, {}])
    def test_invalid_entry(self, device: Any) -> None:
        """Reject invalid entries even when schema validation was not invoked."""
        with pytest.raises(RenderError, match="Invalid device entry"):
            _build_device_lines({"devices": [device]})
