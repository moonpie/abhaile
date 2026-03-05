# ADR 008: Public Helper APIs and YAML Mapping Validation

## Status

Accepted

## Context

The Abhaile codebase had several helper functions prefixed with underscores (`_`) that were quasi-public:

- Used in production code across modules
- Imported and tested directly in test suites
- Stable, well-tested, and essential to public rendering workflows

Additionally, YAML-to-dict validation was inconsistent:

- `_require_mapping` was a private CLI helper duplicating validation logic
- Many call sites used `read_yaml(...) or {}` without enforcing mapping structure
- No centralized helper for "load YAML and require mapping" patterns

This created:

- Confusing API boundaries (underscored but imported in tests)
- Inconsistent validation (some paths validated mappings, others didn't)
- Code duplication and unclear stability guarantees

## Decision

### 1. Promote selected DNS/validation helpers to public names

The following helpers are now public (non-underscored):

**abhaile.dns.records:**

- `collect_zone_records()` — collect DNS records for a zone from hosts and deployed services

**abhaile.dns.serial_validator:**

- `validate_zone_serial()` — validate a single zone serial for content hash mismatches
- `validate_zone_serial_collect()` — validate all zone serials, collecting errors
- `compute_content_hash()` — compute SHA-256 hash of zone file content

**abhaile.dns.renderer:**

- `build_provider_mapping()` — build map of provider names to providing services
- `get_zone_files_config()` — get zone_files configuration from a provider service
- `render_zone_template()` — render a zone file from a Jinja2 template

Backwards compatibility aliases (`_function_name`) remain for existing call sites.

### 2. Add shared YAML mapping validation helpers

**abhaile.utils.config:**

- `ensure_mapping(data, path)` — validate parsed YAML is a mapping; raise RenderError otherwise
- `read_yaml_mapping(path)` — load YAML and require top-level mapping in one call

### 3. Migrate call sites to use shared helpers

- Removed `_require_mapping` private helper from CLI
- Updated all CLI, composition, and service validation call sites to use `read_yaml_mapping`
- Updated all test imports to use public names directly (no aliases)

## Consequences

### Positive

- **Clear API boundaries**: Public helpers have non-underscored names; tests use stable public APIs
- **Consistent validation**: All YAML loading that expects mappings now uses centralized helpers
- **Reduced duplication**: Single mapping validation logic shared across modules
- **Better discoverability**: Public helpers are easier to find and use for future development
- **Safer testing**: Tests now reference stable public APIs rather than relying on private internals
- **Cleaner codebase**: No hidden aliases confusing the API surface

### Negative

- **API surface larger**: More public functions to maintain
- **Breaking change for prior test usage**: Tests using old underscore names must update imports

## Notes

- Tests should import and use public names directly (e.g., `from abhaile.dns.records import collect_zone_records`)
- Underscore-prefixed names are no longer available; migration to public names is required
- This is a breaking change for any external code or tests using the old private names

## References

- REVIEW.md: Section 8 (Code organization and consistency)
- abhaile/utils/config.py: New shared YAML mapping helpers
- abhaile/dns/records.py, serial_validator.py, renderer.py: Public helper promotion
