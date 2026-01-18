"""Common errors for tools/common.

Shared exceptions to be raised by library code and handled by CLI wrappers.
"""


class ValidationError(Exception):
    """Raised when validation of config/network fails."""


class RenderError(Exception):
    """Raised for fatal rendering errors.

    These exceptions should be raised by library code and handled by CLI
    wrappers.
    """
