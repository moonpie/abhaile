# Abhaile Documentation

Authoritative documentation for the Abhaile GitOps homelab. Start with [QUICKSTART.md](QUICKSTART.md) for new users or [ARCHITECTURE.md](ARCHITECTURE.md) for system design.

## Core Documentation

| File | Description |
| --- | --- |
| [QUICKSTART.md](QUICKSTART.md) | Get started in 3 steps: install, render, apply |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, ADR index, technical decisions |
| [OPERATIONS.md](OPERATIONS.md) | Deployment workflows, drift, service migration |
| [MAINTENANCE.md](MAINTENANCE.md) | Routine maintenance, backups, security, troubleshooting |
| [OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md) | Quick reference for on-call operations |
| [CREDENTIALS.md](CREDENTIALS.md) | SOPS vs Vault, secret catalog, rotation |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Rendering logic, testing, path resolution |

## Architecture Decision Records

Key ADRs (see [ARCHITECTURE.md](ARCHITECTURE.md) for complete index):

- [ADR 0001](ADR/0001-host-level-gitops.md) – Host-Level GitOps as Source of Truth
- [ADR 0002](ADR/0002-service-addressing-ipvlan.md) – `/32` Service Addressing via ipvlan-l2
- [ADR 0003](ADR/0003-dns-split-horizon.md) – Split-Horizon DNS with Dual CoreDNS
- [ADR 0004](ADR/0004-secrets-sops-vault.md) – Secrets via SOPS + Vault
- [ADR 0007](ADR/0007-atomic-host-apply.md) – Atomic Deployments via apply.sh
- [ADR 0009](ADR/0009-secrets-decryption-boundary.md) – Secrets Decryption Boundary
- [ADR 0010](ADR/0010-gitops-privilege-boundary.md) – GitOps Privilege Boundary

## Quick Navigation

**New to Abhaile?**

1. Read [QUICKSTART.md](QUICKSTART.md)
1. Review [ARCHITECTURE.md](ARCHITECTURE.md) for system design
1. Check [NETWORK.md](NETWORK.md) for network layout

**Day-to-day operations:**

- [OPERATIONS.md](OPERATIONS.md) for deployment workflows and automatic rollback
- [MAINTENANCE.md](MAINTENANCE.md) for backups, security, troubleshooting
- [OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md) for quick command reference

**Development:**

- [DEVELOPMENT.md](DEVELOPMENT.md) for rendering internals
- [tests/README.md](../tests/README.md) for test structure
- [CONTRIBUTING.md](../CONTRIBUTING.md) for contribution guidelines
