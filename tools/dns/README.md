# DNS Management Tools

Tools for DNS synchronization and validation.

- `cli.py`: Unified DNS management CLI for deSEC synchronization. Fetches current records, plans changes, and applies updates to deSEC for DMZ services. Compares rendered CoreDNS zones with live deSEC state.

Reads:

- `out/rendered/<host>/services/coredns-*/config/zones/*.zone` - rendered DNS zones
- deSEC API (live state)

Produces:

- `out/state/desec_plan.json` - planned DNS changes
- Applies changes to deSEC when `apply` command is used

Usage:

```bash
# Fetch current records from deSEC
python3 tools/dns/cli.py fetch

# Plan changes (dry-run)
python3 tools/dns/cli.py plan

# Apply changes
python3 tools/dns/cli.py apply
```

Called by `apply.sh` during deployment to keep public DNS in sync.
