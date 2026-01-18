"""CLI helpers for consistent argument parsing and help formatting.

Provides a unified ``HelpFormatter`` that combines default value display
with raw description handling, plus a convenience factory for parsers.

Style: Google-style docstrings.
"""

from __future__ import annotations

import argparse
from typing import Optional


class HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter
):
    """Argument parser help formatter.

    Combines:
    - ArgumentDefaultsHelpFormatter: shows default values for options
    - RawDescriptionHelpFormatter: preserves newlines/formatting in descriptions
    """


def create_parser(
    description: str, *, epilog: Optional[str] = None
) -> argparse.ArgumentParser:
    """Create a standardized argument parser.

    Args:
        description: Parser description shown in ``--help``.
        epilog: Optional epilog text shown after arguments.

    Returns:
        argparse.ArgumentParser: Configured parser with standard formatter.
    """

    return argparse.ArgumentParser(
        description=description,
        epilog=epilog,
        formatter_class=HelpFormatter,
    )


def add_verbose_flag(parser: argparse.ArgumentParser) -> None:
    """Add a standard ``-v/--verbose`` flag to a parser.

    Args:
        parser: The parser to extend.
    """

    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output"
    )
