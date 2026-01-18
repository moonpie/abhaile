"""deSEC DNS provider implementation."""

from typing import Any

from tools.common.core import get_logger
from tools.common.dns.provider import DNSProvider
from tools.common.dns import desec_api

logger = get_logger(__name__)


class DesecProvider(DNSProvider):
    """deSEC DNS provider implementation.

    Handles deSEC-specific API calls, record normalization, and change planning.
    Wraps the low-level desec_api module with the DNSProvider interface.
    """

    def __init__(
        self,
        token: str,
        zone: str = "abhaile.dedyn.io",
        exclude_records: set[tuple[str, str]] | None = None,
    ):
        """Initialize deSEC provider.

        Args:
            token: deSEC API token
            zone: DNS zone name (default: abhaile.dedyn.io)
            exclude_records: Set of (name, type) tuples to exclude from management
        """
        self.token = token
        self.zone = zone
        # Records managed outside this tool (e.g., ddclient dynamic updates)
        # Note: deSEC returns FQDNs with trailing dots; we strip them for comparison
        self.exclude_records = exclude_records or {
            (f"vpn.{zone}", "A"),
            (zone, "NS"),
        }

    def fetch_current(self) -> list[dict[str, Any]]:
        """Fetch current DNS records from deSEC API.

        Returns:
            List of current DNS records in normalized format

        Raises:
            requests.HTTPError: If API call fails
        """
        return desec_api.fetch_current(self.token)

    def plan_changes(
        self,
        desired: list[dict[str, Any]],
        current: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Plan deSEC DNS changes (create/update/delete).

        Compares desired vs current state and generates a change plan.
        Excludes records in self.exclude_records from delete operations.

        Args:
            desired: List of desired DNS records
            current: List of current DNS records

        Returns:
            Plan dict with keys: create, update, delete
        """
        # Build maps keyed by (name, type)
        desired_map: dict[tuple[str, str], list[str]] = {}
        for rec in desired:
            name = rec.get("name", "@")
            rtype = rec.get("type", "").upper()
            content = rec.get("content", [])

            # Handle both list and single-value content
            if isinstance(content, str):
                content = [content]

            key = (name, rtype)
            if key not in desired_map:
                desired_map[key] = []
            desired_map[key].extend(content)

        current_map: dict[tuple[str, str], list[str]] = {}
        for rec in current:
            name = rec.get("name", "@")
            rtype = rec.get("type", "").upper()
            content = rec.get("content", [])

            if isinstance(content, str):
                content = [content]

            key = (name, rtype)
            current_map[key] = content

        create = []
        update = []
        delete = []

        # Find creates and updates
        for key, contents in desired_map.items():
            cur_contents = current_map.get(key, [])
            # Sort for stable comparison
            if sorted(cur_contents) != sorted(contents):
                if cur_contents:
                    update.append((key, contents))
                else:
                    create.append((key, contents))

        # Find deletes (excluding managed records)
        for key in current_map:
            if key not in desired_map:
                # Check if key should be excluded (match with or without zone suffix)
                name, rtype = key
                # Normalize: strip zone suffix for comparison
                name_normalized = name.replace(f".{self.zone}", "").rstrip(".")

                exclude_key_plain = (name_normalized, rtype)
                exclude_key_fqdn = (f"{name_normalized}.{self.zone}", rtype)
                exclude_key_zone = (self.zone, rtype)

                if (
                    exclude_key_plain not in self.exclude_records
                    and exclude_key_fqdn not in self.exclude_records
                    and exclude_key_zone not in self.exclude_records
                ):
                    delete.append(key)

        return {
            "create": create,
            "update": update,
            "delete": delete,
        }

    def apply_plan(self, plan: dict[str, Any]) -> None:
        """Apply a change plan to deSEC.

        Args:
            plan: Change plan from plan_changes()

        Raises:
            requests.HTTPError: If API call fails
        """
        applied = 0

        # Apply creates
        for (name, rtype), contents in plan.get("create", []):
            desec_api.update_record(
                self.token,
                name if name != "@" else "",
                rtype,
                contents,
            )
            logger.info("CREATE: %s %s -> %s", name, rtype, contents)
            applied += 1

        # Apply updates
        for (name, rtype), contents in plan.get("update", []):
            desec_api.update_record(
                self.token,
                name if name != "@" else "",
                rtype,
                contents,
            )
            logger.info("UPDATE: %s %s -> %s", name, rtype, contents)
            applied += 1

        # Apply deletes
        for name, rtype in plan.get("delete", []):
            desec_api.delete_record(
                self.token,
                name if name != "@" else "",
                rtype,
            )
            logger.info("DELETE: %s %s", name, rtype)
            applied += 1

        logger.info("Applied %d deSEC changes", applied)
