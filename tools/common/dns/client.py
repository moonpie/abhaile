"""High-level DNS client for sync operations."""

from typing import Any

from tools.common.core import get_logger
from tools.common.dns.provider import DNSProvider

logger = get_logger(__name__)


class DNSClient:
    """High-level DNS synchronization client.

    Wraps a DNSProvider to provide a simple sync() interface for comparing
    desired state against current state and optionally applying changes.
    """

    def __init__(self, provider: DNSProvider):
        """Initialize DNS client with a provider.

        Args:
            provider: DNSProvider implementation (e.g., DesecProvider)
        """
        self.provider = provider

    def sync(
        self,
        desired: list[dict[str, Any]],
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Synchronize DNS records with desired state.

        Fetches current records, plans changes, and optionally applies them.

        Args:
            desired: List of desired DNS records
            dry_run: If True, only plan changes; if False, apply them

        Returns:
            Change plan dict with keys: create, update, delete, and metadata

        Raises:
            Exception: Provider-specific errors
        """
        logger.info("Fetching current DNS state...")
        current = self.provider.fetch_current()

        logger.info("Planning changes...")
        plan = self.provider.plan_changes(desired, current)

        # Add summary metadata
        plan["summary"] = {
            "creates": len(plan.get("create", [])),
            "updates": len(plan.get("update", [])),
            "deletes": len(plan.get("delete", [])),
            "total": (
                len(plan.get("create", []))
                + len(plan.get("update", []))
                + len(plan.get("delete", []))
            ),
        }

        if not dry_run:
            if plan["summary"]["total"] > 0:
                logger.info("Applying changes...")
                self.provider.apply_plan(plan)
                logger.info("DNS sync complete")
            else:
                logger.info("No changes to apply")
        else:
            if plan["summary"]["total"] > 0:
                logger.info("Dry-run: %d changes planned", plan["summary"]["total"])
            else:
                logger.info("No changes needed")

        return plan

    def fetch_current(self) -> list[dict[str, Any]]:
        """Fetch current DNS records from provider.

        Convenience method for direct access to provider's fetch.

        Returns:
            List of current DNS records
        """
        return self.provider.fetch_current()
