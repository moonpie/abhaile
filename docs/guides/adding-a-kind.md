# Adding a New Artifact Kind

Checklist for adding a new artifact kind (e.g., `nftables.config`) end-to-end.

## 1. Register the kind

Add the kind string to the appropriate family in `src/abhaile/models/kinds.py`:

```python
KIND_FAMILIES = {
    ...
    "nftables": frozenset({"nftables.config"}),
}
```

Run `make test` — the manifest assertion catches any typo immediately.

## 2. Create the renderer

Create `src/abhaile/renderers/nftables.py`:

- Accept `host`, `services`, `network`, `config_root`, `output_dir`, `collector`, `rendered_root`
- Write output files to `output_dir`
- Call `collector.register_artifact(kind="nftables.config", ...)`

Wire it in `src/abhaile/cli/render.py` → `_render_host_system()` or `_render_host_services()`.

## 3. Create the executor

Create `src/abhaile/apply/nftables.py`:

- Implement `apply_owner_change(owner_ref, ...)` returning an actions summary dict
- Use `run_command` or `run_systemctl_command` from `apply/actions.py`

## 4. Wire the dispatch

In `src/abhaile/cli/apply.py`:

- Add `_NFTABLES_KINDS = KIND_FAMILIES["nftables"]` to the constants block
- Add a `_run_nftables_owner_actions(writes, removals_to_apply)` function
- Call it from `main()` in the appropriate phase position
- Add dry-run validation in `_run_dry_run_validations` if applicable

## 5. Add service config

In `config/services/<service>/service.yaml`, add composition entries that produce the new kind.

## 6. Write tests

- `tests/unit/python/renderers/test_nftables.py` — renderer unit tests
- `tests/unit/python/apply/test_nftables_executor.py` — executor unit tests
- Update integration tests if the kind should appear in phobos render

## Files touched

| File | Change |
|------|--------|
| `src/abhaile/models/kinds.py` | Add kind to family |
| `src/abhaile/renderers/<new>.py` | New renderer |
| `src/abhaile/cli/render.py` | Wire renderer call |
| `src/abhaile/apply/<new>.py` | New executor |
| `src/abhaile/cli/apply.py` | Wire dispatch + constant |
| `config/services/<svc>/service.yaml` | Add composition entries |
| `tests/` | New test files |
