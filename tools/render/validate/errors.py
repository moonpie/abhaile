"""Validation error types for render validation."""

from tools.common.core import ValidationError as CoreValidationError


class ValidationError(CoreValidationError):
    """Raised when pre-render validation fails."""

    pass
