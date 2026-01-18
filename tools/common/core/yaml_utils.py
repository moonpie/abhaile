"""YAML loading utilities (shared copy).

This is a lightweight copy of the same helper used by the renderer, moved
into `tools.common` so other tools can import it without reaching into
`tools.render.lib`.
"""

from pathlib import Path
from typing import Any
import yaml


def load_yaml(path: Path | str) -> dict[str, Any]:
    path = Path(path) if isinstance(path, str) else path
    if not path.exists():
        raise FileNotFoundError(f"YAML file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        content = yaml.safe_load(f)
        return content if content is not None else {}
