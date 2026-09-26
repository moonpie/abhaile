"""Define failures at the privileged trust boundary."""


class TrustError(RuntimeError):
    """Report a fail-closed trust-policy violation."""
