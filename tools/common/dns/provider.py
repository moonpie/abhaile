"""Abstract DNS provider interface."""

from abc import ABC, abstractmethod
from typing import Any


class DNSProvider(ABC):
    """Abstract base class for DNS providers.

    Defines the interface for fetching current DNS state, planning changes,
    and applying updates. Implementations handle provider-specific API calls.
    """

    @abstractmethod
    def fetch_current(self) -> list[dict[str, Any]]:
        """Fetch current DNS records from provider.

        Returns:
            List of current DNS records in normalized format:
            [{"name": str, "type": str, "content": list[str], "ttl": int}, ...]

        Raises:
            Exception: Provider-specific errors
        """
        pass

    @abstractmethod
    def plan_changes(
        self,
        desired: list[dict[str, Any]],
        current: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate change plan comparing desired vs current state.

        Args:
            desired: List of desired DNS records
            current: List of current DNS records (from fetch_current)

        Returns:
            Plan dict with keys: create, update, delete
            {
                "create": [((name, type), [content])],
                "update": [((name, type), [content])],
                "delete": [(name, type)]
            }
        """
        pass

    @abstractmethod
    def apply_plan(self, plan: dict[str, Any]) -> None:
        """Apply a change plan to the DNS provider.

        Args:
            plan: Change plan from plan_changes()

        Raises:
            Exception: Provider-specific errors
        """
        pass
