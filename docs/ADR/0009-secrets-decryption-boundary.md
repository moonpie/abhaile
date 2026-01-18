# ADR 0009: Secrets Decryption Boundary

- **Status:** Accepted
- **Date:** 2025-12-19
- **Related Docs:** `docs/CREDENTIALS.md`, `docs/QUICKSTART.md`

## Context

SOPS-encrypted secrets must only be decrypted in controlled environments to avoid plaintext exposure in CI or developer workstations. Additionally, decryption should be performed by a dedicated unprivileged user to minimize blast radius.

## Decision

- SOPS decryption occurs only on target hosts via the GitOps render phase (unprivileged `abhaile` user).
- Age private key required for decryption lives at `/home/abhaile/.config/sops/age/keys.txt` (mode 600).
- CI may validate schemas but must not decrypt secrets.
- Plaintext outputs are written to `/etc/abhaile/<service>/` with strict permissions (mode 600), applied by privileged phase.

## Consequences

- ✅ Reduces exposure of plaintext secrets.
- ✅ Clear operational boundary for decryption (unprivileged render phase).
- ✅ Unprivileged user cannot write to protected paths; privileged apply handles that.
- ⚠️ Host access required for troubleshooting decrypted outputs.
- ⚠️ Age key is high-impact; rotation must be coordinated across all hosts.

## Alternatives Considered

- **CI-based decryption**: rejected due to increased secret exposure risk.
- **Root-user decryption**: rejected; prefer unprivileged user to limit blast radius.
