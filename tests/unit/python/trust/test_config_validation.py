"""Test host identity and non-decrypting bootstrap rule validation."""

from __future__ import annotations

import json
import traceback

import pytest
import yaml

from abhaile.trust.config_validation import select_bootstrap_rule, validate_admitted_config
from abhaile.trust.errors import TrustError

RECIPIENT = "age1" + "q" * 58


@pytest.fixture
def admitted_config(tmp_path):
    """Build isolated admitted config and schema fixtures."""
    data = {
        "config/mapping.yaml": {"abhaile": [{"deimos": []}]},
        "config/network.yaml": {"hosts": {"deimos": {}}, "vlans": {}},
        "config/hosts/deimos/host.yaml": {},
        ".sops.yaml": {"creation_rules": [{"path_regex": r"secrets/deimos/.*", "age": RECIPIENT}]},
    }
    for relative, value in data.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(value))
    for name in ("mapping", "network", "host"):
        path = tmp_path / "schemas" / f"{name}.schema.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(
            json.dumps({"$schema": "http://json-schema.org/draft-07/schema#", "type": "object"})
        )
    bundle = tmp_path / "secrets/deimos/vault-agent.sops.yaml"
    bundle.parent.mkdir(parents=True)
    bundle.write_text("ENCRYPTED_FIXTURE_NOT_READ")
    return tmp_path


class TestHostValidation:
    """Exercise structured membership and sanitized validation errors."""

    def test_valid_config_never_reads_secret_bundle(self, admitted_config, monkeypatch):
        from pathlib import Path

        original = Path.open

        def guarded_open(path, *args, **kwargs):
            assert "secrets" not in path.parts
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", guarded_open)
        result = validate_admitted_config(admitted_config, "deimos", "deimos")
        assert result.host == "deimos"
        assert result.creation_rule == 0

    @pytest.mark.parametrize("host,local", [("deimos", "phobos"), ("../deimos", "../deimos")])
    def test_mismatch_rejected_before_config_read(self, tmp_path, host, local):
        with pytest.raises(TrustError, match="identity"):
            validate_admitted_config(tmp_path, host, local)

    @pytest.mark.parametrize(
        "relative,value",
        [
            ("config/mapping.yaml", {"abhaile": [{"phobos": []}]}),
            ("config/network.yaml", {"hosts": {"phobos": {}}, "vlans": {}}),
            ("config/mapping.yaml", {"abhaile": [{"deimos": []}, {"deimos": []}]}),
        ],
    )
    def test_missing_or_ambiguous_host(self, admitted_config, relative, value):
        (admitted_config / relative).write_text(yaml.safe_dump(value))
        with pytest.raises(TrustError):
            validate_admitted_config(admitted_config, "deimos", "deimos")

    def test_missing_bundle(self, admitted_config):
        (admitted_config / "secrets/deimos/vault-agent.sops.yaml").unlink()
        with pytest.raises(TrustError, match="invalid"):
            validate_admitted_config(admitted_config, "deimos", "deimos")

    def test_missing_host_file(self, admitted_config):
        (admitted_config / "config/hosts/deimos/host.yaml").unlink()
        with pytest.raises(TrustError, match="invalid"):
            validate_admitted_config(admitted_config, "deimos", "deimos")

    def test_schema_validation_is_used(self, admitted_config):
        schema = admitted_config / "schemas/host.schema.json"
        schema.write_text(
            json.dumps(
                {
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "required": ["physical_device"],
                }
            )
        )
        with pytest.raises(TrustError, match="invalid"):
            validate_admitted_config(admitted_config, "deimos", "deimos")

    def test_error_does_not_expose_values(self, admitted_config, capsys, caplog):
        sentinel = "PLACEHOLDER_SECRET_DO_NOT_LOG"
        (admitted_config / "config/mapping.yaml").write_text(yaml.safe_dump(sentinel))
        with pytest.raises(TrustError) as caught:
            validate_admitted_config(admitted_config, "deimos", "deimos")
        assert sentinel not in "".join(traceback.format_exception(caught.value))
        output = capsys.readouterr()
        assert sentinel not in output.out + output.err + caplog.text


class TestCreationRules:
    """Preserve first-match and catch-all semantics without decryption."""

    @pytest.mark.parametrize(
        "pattern", [r"secrets/deimos/vault-agent\.sops\.yaml$", r"^secrets/deimos/.*$", ""]
    )
    def test_matching_rule(self, pattern):
        assert (
            select_bootstrap_rule(
                {"creation_rules": [{"path_regex": pattern, "age": RECIPIENT}]}, "deimos"
            )
            == 0
        )

    def test_first_match_cannot_be_bypassed(self):
        with pytest.raises(TrustError, match="recipients"):
            select_bootstrap_rule({"creation_rules": [{}, {"age": RECIPIENT}]}, "deimos")

    def test_nonmatching_rule_and_age_list(self):
        assert (
            select_bootstrap_rule(
                {
                    "creation_rules": [
                        {"path_regex": "phobos", "age": RECIPIENT},
                        {"age": [RECIPIENT]},
                    ]
                },
                "deimos",
            )
            == 1
        )

    @pytest.mark.parametrize(
        "rules",
        [
            None,
            [],
            [None],
            [{"path_regex": 4}],
            [{"path_regex": "["}],
            [{"path_regex": "(?=secret)"}],
            [{"path_regex": "phobos", "age": RECIPIENT}],
            [{"age": "PLACEHOLDER_SECRET_DO_NOT_LOG"}],
            [{"age": RECIPIENT, "key_groups": []}],
        ],
    )
    def test_malformed_or_unsupported_rules_fail_sanitized(self, rules):
        with pytest.raises(TrustError) as caught:
            select_bootstrap_rule({"creation_rules": rules}, "deimos")
        assert "PLACEHOLDER_SECRET_DO_NOT_LOG" not in str(caught.value)
