"""Error types for render, planning, apply, and state workflows."""


class PipelineError(Exception):
    """Base error for user-facing pipeline failures."""


class RenderError(PipelineError):
    """Raised when render encounters a fatal error."""


class DiffError(PipelineError):
    """Raised when diff/planning encounters a fatal error."""


class ApplyError(PipelineError):
    """Raised when apply or state mutation encounters a fatal error."""
