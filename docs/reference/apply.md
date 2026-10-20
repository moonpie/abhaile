# Reconciliation Reference

The former Python mutation backend documented at this path was retired after both production hosts
completed the Ansible cutover. Historical accepted specs retain its original contracts as evidence;
they are not current operator guidance.

Current reconciliation uses:

- `scripts/abhaile-runner` for locking, revision selection, recovery, and status;
- `ansible/playbooks/reconcile.yml` for check and live convergence;
- direct roles under `ansible/roles/` for validation, publication, lifecycle, and readiness;
- `src/abhaile/state/reconciliation.py` for durable runner authority; and
- `src/abhaile/state/removals.py` for exact-identity removal classification.

Use [operations](../runbooks/operations.md) for routine commands and
[ADR 0013](../adr/0013-last-successful-ansible-reconciliation.md) for the authority model.
