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

## 3. Create the resource-family role

Create `ansible/roles/nftables_config/`:

- Select only the closed kind family passed by manifest orchestration.
- Validate every source and target before publication.
- Use built-in modules and fixed installed validators.
- Define synchronous activation, readiness, and safe-removal behavior.

## 4. Wire manifest orchestration

In `ansible/roles/manifest_orchestration/tasks/main.yml`:

- Add the kind to exactly one resource-family selection.
- Include the role at the correct dependency position.
- Reject unsupported or ambiguous removal before mutation.

## 5. Add service config

In `config/services/<service>/service.yaml`, add composition entries that produce the new kind.

## 6. Write tests

- `tests/unit/python/renderers/test_nftables.py` — renderer unit tests
- focused Ansible integration tests for check, live, idempotence, drift, and failure behavior
- Update integration tests if the kind should appear in phobos render

## Files touched

| File | Change |
|------|--------|
| `src/abhaile/models/kinds.py` | Add kind to family |
| `src/abhaile/renderers/<new>.py` | New renderer |
| `src/abhaile/cli/render.py` | Wire renderer call |
| `ansible/roles/<family>/` | Direct convergence role |
| `ansible/roles/manifest_orchestration/` | Closed kind selection and ordering |
| `config/services/<svc>/service.yaml` | Add composition entries |
| `tests/` | New test files |
