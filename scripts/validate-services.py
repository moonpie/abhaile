"""Run service validation from a source checkout, including isolated hook environments."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from abhaile.cli.validate_services import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
