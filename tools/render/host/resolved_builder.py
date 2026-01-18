"""systemd-resolved configuration builder."""

from pathlib import Path
import shutil

from tools.common.core import get_logger

logger = get_logger(__name__)


def build_resolved_configs(
    hostname: str,
    hosts_path: Path,
    output_path: Path,
) -> None:
    """Build systemd-resolved configuration for the host.

    Copies resolved config from config/hosts/{hostname}/systemd-resolved/ to output.

    Args:
        hostname: Target hostname
        hosts_path: Path to config/hosts directory
        output_path: Output root path
    """
    resolved_config_dir = hosts_path / hostname / "systemd-resolved"

    if not resolved_config_dir.exists() or not any(
        p.is_file() for p in resolved_config_dir.rglob("*")
    ):
        # Try common directory when host dir is missing or empty
        resolved_config_dir = hosts_path / "common" / "systemd-resolved"
        if not resolved_config_dir.exists():
            return

    output_dir = output_path / hostname / "systemd-resolved" / "etc" / "systemd"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Copy all resolved configuration files
    for item in resolved_config_dir.rglob("*"):
        if item.is_file():
            rel_path = item.relative_to(resolved_config_dir)
            dest = output_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
            logger.info("Copied resolved config: %s", dest)
