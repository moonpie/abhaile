# ADR 0011: Guarded systemd-networkd Convergence

## Status

2026-10-05: Superseded by ADR 0012.

2026-10-02: Accepted

## Context

Publishing or activating host network configuration can remove the path used by the reconciliation
controller itself. Ordinary Ansible failure handling is insufficient: the controller, Python
runtime, Ansible process, or host may stop before it can restore the previous configuration.
Abhaile therefore needs recovery authority installed before a transition, independent of the
initiating process, and able to survive reboot.

This decision is limited to renderer-owned `systemd-networkd` `.netdev`, `.network`, and
`.network.d/*.conf` artifacts. Resolver configuration and alternative network backends remain
outside this controller.

## Decision

Abhaile will execute networkd changes as a closed, transaction-bound transition rather than as
ordinary file publications or inferred Ansible handlers.

The sealed manifest is the sole desired-state authority. The protected compiler produces one
exact-cover convergence product: every manifest-v2 step is assigned once, in source order, to
either ordinary Ansible or guarded network execution. Missing, duplicate, reordered, or
cross-lane steps fail closed. Before mutation, the privileged network compiler must produce one
complete network plan containing the host, transaction, capsule and manifest
identities; complete candidate file set; exact current files to snapshot; enumerated removal set;
affected links; typed reachability probes; bounded recovery deadline; and expected recovery-helper
installation-manifest identity and protocol version. The report form is immutable and carries no
callbacks, roots, tokens, boot values, or effect ports. Unknown network kinds, paths, links, probe
fields, commands, or executor assignments fail closed.

The construction boundary has two products. Dry-run and review receive a pure immutable proposal
containing the complete exact-cover Ansible/network plan and no execution capability. Mutation may
receive only an opaque private capability issued after the capsule is reverified and fixed runtime,
boot, recovery-installation, prior-state, removal-approval, and confirmation prerequisites pass.
Transaction identifiers and revert tokens come from protected randomness. Removal approval and
confirmation are fixed-root records bound to the exact transaction and evidence, never booleans or
callbacks supplied with a request. Existing CLI and launcher surfaces cannot request this capability
while quarantine remains in force.

Network removal uses a dedicated approval valid only for the exact enumerated removal set sealed
into the plan. Generic destructive or prune approval does not authorize it.

### Transition protocol

The privileged executor is a private capability; public coordinator and CLI surfaces cannot
construct it. Its production factory derives fixed roots and unit identities, reads boot identity
from `/proc/sys/kernel/random/boot_id`, and creates recovery authority from protected randomness.
Injected readers and effect ports exist only as private repository-test seams. The executor
performs these stages under the protected transaction lock once the later adoption gate enables it:

1. Validate the complete plan, fixed installed helper and units, current path identities, links,
   probe coverage, deadline, and deletion approval without mutation.
1. Persist and fsync a descriptor-safe snapshot of every touched current path plus the complete
   candidate and transaction journal.
1. Arm and verify the independent recovery service and timer for that exact transaction.
1. Publish the complete candidate and perform only the approved enumerated removals.
1. Invoke fixed `/usr/bin/networkctl reload`, followed by fixed
   `/usr/bin/networkctl reconfigure <link>` once for each sorted affected link. The controller
   never restarts `systemd-networkd`.
1. Run every typed probe within its bound and persist the exact results.
1. Require explicit confirmation bound to the transaction, candidate digest, and successful probe
   evidence; persist `CONFIRM_AUTHORIZED` before requesting watchdog disarm.
1. Verify the exact watchdog is disarmed and persist `REVERT_DISARMED`, then `CONFIRMED`.
1. Only after `CONFIRMED`, commit ordinary apply state. Persist `APPLY_COMMITTED` bound to that
   durable commit evidence before terminal network-journal cleanup.

Retry dispatch is stage-aware. `SNAPSHOTTED` may arm only while exact prior state remains;
`REVERT_ARMED` may publish only from exact prior state, or record an already exact candidate;
ambiguous activation at `CANDIDATE_APPLIED` reverts; `REACHABLE` reruns all read-only probes;
`CONFIRM_AUTHORIZED` revalidates candidate, recovery installation, boot and confirmation before
disarm. A changed boot before durable disarm remains rollback-authoritative. After durable disarm,
`REVERT_DISARMED` and `CONFIRMED` never revert merely because the boot changed: they finish forward
only after independently revalidating the exact candidate, affected links, probes, confirmation
authority, recovery installation, and durable apply state as applicable. The journal retains bounded
original probe and confirmation evidence so the original authorization can be revalidated exactly;
fresh probes establish current reachability but their nonce-bearing bytes need not equal the original
results. Post-disarm installation revalidation does not require a cancelled timer to remain scheduled
or an old deadline to remain unexpired;
`APPLY_COMMITTED` is idempotent; and `REVERTED` permits exact terminal cleanup followed by a fresh,
distinct transaction. A reused transaction ID with changed revision, capsule, manifest, candidate,
sealed journal boot identity, or deadline fails closed. A legitimate current-boot change follows
the stage-specific rollback/finish-forward policy above. No retry takes a new snapshot or blindly repeats an
ambiguous activation effect.

### Independent recovery

Recovery uses a preinstalled, root-owned, non-writable helper and fixed systemd service/timer. The
units accept no caller-supplied executable, path, or shell fragment. A versioned closed installation
manifest binds the helper, isolated interpreter, watchdog module/dependency artifacts, service,
timer, networkd drop-in, digests, ownership, modes, link counts, and protected ancestry. Parsed unit
contracts bind the helper invocation, interpreter/module, timer cadence and target service, boot
ordering, and enablement. Manager evidence must show the exact loaded timer is enabled, active,
attached to the expected service, and scheduled before the transaction deadline. This identity is
checked after arming and again before disarm. A boot recovery unit runs
before normal networkd activation; a fixed watchdog cadence also evaluates active journals during
normal operation. The journal contains a bounded wall-clock deadline together with a canonical
protected boot identity. The identity is re-read before timer activation, candidate publication,
and disarm; absence, malformed content, links, unreadability, or change fails closed. Expired,
malformed, pre-confirmation, changed-boot, or otherwise
ambiguous active state restores the complete snapshot, reloads networkd, reconfigures the sealed
links, verifies restoration, and records `REVERTED`. Restoration failure remains active and fails
closed for operator recovery. Confirmed state is never reverted merely because apply-state commit
or journal cleanup was interrupted.

The recovery deadline is renderer-owned, from 60 through 900 seconds inclusive; the initial
default is 300 seconds. The watchdog checks at a fixed 15-second cadence. The production executor
must verify the installed helper and unit identities before admitting a transition.

### Typed reachability

Probe intent is declared beside the owning interface at
`hosts.<host>.interfaces.<interface>.convergence_probes` in `config/network.yaml`. The renderer
normalizes that intent and seals the host, `iface:` owner, interface, candidate source address,
VLAN, literal target, transport, direction, and deterministic probe identity into manifest v2.
The privileged compiler copies that authority unchanged and never reopens configuration or derives
intent from live routes.

There is no implicit probe merely because an interface names a VLAN. An explicit `gateway` probe
may be deterministically expanded through that interface's VLAN to the declared literal gateway.
This is especially important for `/32` ipvlan children, where VLAN membership does not imply that
the logical interface owns a route to the gateway. Host-global probes, runtime-derived probes, and
unconditional VLAN gateway defaults are rejected because they lose affected-interface coverage or
allow observations to create intent.

Each affected network must be covered by closed probe records. Supported normalized probe types are:

- `link-state`: exact link must be administratively and operationally up.
- `address`: exact link must hold the sealed address and prefix.
- `route`: exact destination and optional gateway must resolve through the sealed link.
- `gateway`: the sealed gateway must be reachable from the sealed source address and link.
- `endpoint`: a bounded TCP connection to the sealed IP address and port must originate from the
  sealed source address and link.
- `external-peer`: a peer outside the target host's namespace must prove both host-to-peer and
  peer-to-candidate-host reachability using a transaction nonce and the sealed candidate address.

Probe timeouts are one through 30 seconds. DNS-name probes are excluded while resolver convergence
remains outside this controller. A result is authority only when it matches the complete sealed
record and current transaction. Gateway success alone never permits recovery disarm: every
affected network requires an external-peer observation, with separate source/interface binding
when interfaces share a VLAN. Missing production declarations leave network execution fail closed.

Dry-run compiles and reports the complete plan but creates no snapshot, journal, timer, files,
networkd reload, interface reconfiguration, or probe traffic.

## Alternatives Considered

### Rely on Ansible failure handling

Rejected because loss of controller reachability prevents the initiating process from executing
its rescue path.

### Restart systemd-networkd after publication

Rejected because a manager restart broadens disruption and is unnecessary. Reload plus explicit
reconfiguration of the sealed affected links is the bounded activation contract.

### Accept an opaque health command

Rejected because caller-selected commands and untyped success values cannot prove which affected
network was checked or bind the observation to the sealed candidate.

## Consequences

- Network transitions have an independently executing, reboot-capable rollback path.
- Network deletion and confirmation are explicit authorities, separate from ordinary convergence.
- The disposable Debian 13 proof uses console-backed Hyper-V isolation and a separate network
  namespace peer; real reboot evidence, rather than an in-process simulation, proves changed-boot
  recovery ordering.
- The fixed helper and units become protected runtime prerequisites for host adoption.
- Live `deimos` or `phobos` network mutation remains a separately approved Phase 6/7 activity.

## Implementation Status

The repository now enforces the construction and recovery mechanics while keeping execution
quarantined. A revision-only production constructor loads the fixed protected trust policy,
re-verifies the canonical sealed capsule, compiles and retains the complete Ansible/network exact
cover in one issuer-created request, derives prior-state removals, creates the transaction and token
internally, and issues only private plan-bound ordinary and fixed-effect network capabilities. The
coordinator accepts no callback alongside that request and drives confirmation, apply-state commit,
network apply-commit, and authority-first terminal cleanup through private execution methods
unavailable to the CLI and launcher.

Independent recovery installation is separate from networkd/resolved adoption. Its exact canonical
identity must match a separately provisioned root-owned policy digest under `/etc/abhaile`; the
installation role cannot self-approve that digest. The identity covers helper, units, drop-in,
copied interpreter, first-party module closure, fixed Debian shell/Python/runtime package set and
versions. Package files are checked with `dpkg --verify` before publication, after timer arm, and
before disarm. Effective systemd observations bind the monotonic timer schedule, service command
and hardening, drop-ins, networkd ordering, and reload state.

Disposable Debian proof completed on 2026-10-03 for real systemd/networkd/reboot/peer behavior.
A proof-only veth and separate network namespace exercised deadline revert, the nonce-bearing
bidirectional peer, explicit confirmation, distinct same-state transactions, exact approved
deletion, inert dry-run, controller interruption, and a real changed-boot restore before networkd
startup. The owner approved the bounded reboot rule on 2026-10-03: pre-disarm changed boot restores the snapshot;
post-disarm recovery finishes forward only after the exact independent revalidation above and
otherwise fails closed. A broader review before Phase 6 will consider simplifying all reconciliation
around the protected locally retained last-successful capsule and one durable apply commit point.

## References

- [ADR 0012: Trusted-Revision Ansible Reconciliation](0012-trusted-revision-ansible-reconciliation.md)
- [Spec 0028: Target Host Reconciliation Model](../specs/accepted/0028-target-host-reconciliation-model.md)
- [ADR 0010: Ansible Reconciliation Model](0010-ansible-reconciliation-model.md)
