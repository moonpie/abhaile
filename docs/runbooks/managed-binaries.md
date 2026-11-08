# Managed host binaries

Standard packages use APT. Pinned standalone executable downloads use the
`host.binary` manifest family and native Ansible role. Container images and
existing Quadlet builds retain their established handling. Command-oriented
software declarations remain render-only.

Declare a binary in `config/hosts/<host>/software/downloads/<id>.yaml` and
reference its ID through host `composition.software.downloads`. For example,
the following is the planned SOPS adoption declaration; it is not yet enrolled:

```yaml
id: sops
name: Install SOPS binary
binary:
  url: https://github.com/getsops/sops/releases/download/v3.13.1/sops-v3.13.1.linux.amd64
  sha256: 620a9d7e3352ababeca6908cea24a6e8b14ce89a448ddbd3f94f1ef3398f470a
  destination: /usr/local/bin/sops
  owner_user: root
  owner_group: root
  mode: "0755"
```

Only direct children of `/usr/local/bin` are supported, with root ownership
and modes `0700`, `0750` or `0755`. Symlink targets, redirected parents and
conflicting manifest targets are rejected. Archives and arbitrary install
commands are unsupported. Keep bootstrap's SOPS pin/checksum aligned with
the declaration when enrolling or upgrading SOPS.

A matching binary requires no download. Metadata-only repair is local.
Changed content is downloaded into a private temporary directory beside the
target, checksum-verified and published atomically. Download or verification
failure preserves the old executable. Temporary files are removed on normal
completion and handled failures; power loss can leave staging directories.
Check mode reports changes without downloading or testing upstream availability.

Recovery uses the last-successful declaration. Restoring a different version
requires its release to remain downloadable: offline rollback is not guaranteed.
A failed restore preserves the installed executable and recovery marker; restore
upstream availability and let normal recovery retry. Do not edit runner records.
First-adoption recovery retains the executable when the previous manifest did
not manage it. Ordinary removal and destination changes are rejected.

## Delivery sequence

1. Deploy support without enrolling SOPS. Confirm that revision is last-successful
   on both hosts.
1. Confirm both installed SOPS checksums, then enroll 3.13.1. Confirm both hosts
   have accepted that managed baseline without replacing matching executables.
1. Upgrade the declaration and bootstrap pin to 3.13.3 in a separate change.
   Validate version/checksum and decrypt an existing age-encrypted artifact with
   plaintext discarded.

Spec [0035](../specs/active/0035-managed-binary-downloads.md) tracks delivery and
operator evidence. A payload checksum is distinct from the manifest checksum of
the rendered declaration; integrity audits the payload and its metadata.
