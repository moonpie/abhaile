"""deSEC plan builder (pure, no file I/O).

Returns a plan dict to be written by the orchestrator.
"""

from __future__ import annotations

from typing import Any

import requests

from tools.common.core import RenderError
from tools.common.dns import DNSClient, DesecProvider


def build_desec_plan(
    desired_records: list[dict[str, Any]],
    token: str | None,
    strict: bool = False,
    skip: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Build deSEC plan (dry-run) without performing file I/O.

    Args:
        desired_records: desired DNS records for deSEC
        token: DESEC_TOKEN (required unless skip is True)
        strict: if True, raise on drift-check errors
        skip: if True, skip remote check and return skipped plan

    Returns:
        (plan_dict, skipped)
        plan_dict may contain keys: create, update, delete, desired_records, error, skipped

    Raises:
        RenderError: when token missing (and not skip) or strict mode errors occur
    """
    if skip:
        return {"desired_records": desired_records, "skipped": True}, True

    if not token:
        raise RenderError(
            "DESEC_TOKEN not set; set env var or use --skip-desec to bypass external DNS"
        )

    try:
        provider = DesecProvider(token)
        client = DNSClient(provider)
        plan = client.sync(desired_records, dry_run=True)
        return plan, False
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status in (401, 403):
            raise RenderError(
                f"deSEC auth failed (status {status}); refresh DESEC_TOKEN"
            ) from e
        if strict:
            raise RenderError(f"deSEC drift check failed (strict): {e}") from e
        return {"desired_records": desired_records, "error": str(e)}, False
    except Exception as e:  # pragma: no cover - fallback path
        if strict:
            raise RenderError(f"deSEC drift check failed (strict): {e}") from e
        return {"desired_records": desired_records, "error": str(e)}, False


def summarize_desec_drift(plan: dict[str, Any]) -> tuple[int, int, int]:
    """Return counts of create, update, delete from plan (0 if missing)."""
    creates = len(plan.get("create", []) or []) if isinstance(plan, dict) else 0
    updates = len(plan.get("update", []) or []) if isinstance(plan, dict) else 0
    deletes = len(plan.get("delete", []) or []) if isinstance(plan, dict) else 0
    return creates, updates, deletes
