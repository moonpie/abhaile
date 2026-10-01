"""Test quarantined invocation planning and explicit future flag mappings."""

import argparse
import json
import os
import traceback
from dataclasses import replace
from unittest.mock import Mock

import pytest

from abhaile.cli.apply import main, parse_apply_args
from abhaile.trust.ansible import (
    CAPSULES,
    RUNTIME,
    TEMPORARY,
    FLAG_CONTRACT,
    ApplyIntent,
    SecretTaskPolicy,
    _plan_ansible,
    map_apply_intent,
    reject_execution,
    sanitized_result,
)
from abhaile.trust.capsule import SealedCapsule
from abhaile.trust.errors import TrustError
from abhaile.utils.errors import ApplyError


@pytest.fixture
def inputs(tmp_path):
    """Build a synthetic protected filesystem and injected capsule verifier."""

    def fixed(path):
        return tmp_path / path.relative_to("/")

    capsule = SealedCapsule("a" * 40, "phobos", fixed(CAPSULES) / "phobos" / ("a" * 40))
    for directory in (
        capsule.source / "ansible/roles",
        capsule.source / "ansible/playbooks",
        capsule.rendered,
        fixed(RUNTIME) / "bin",
        fixed(TEMPORARY),
    ):
        directory.mkdir(parents=True, exist_ok=True)
    for path in (
        capsule.source / "ansible/ansible.cfg",
        capsule.source / "ansible/playbooks/converge.yml",
        fixed(RUNTIME) / "bin/python",
    ):
        path.write_text("fixture", encoding="utf-8")
    (capsule.rendered / "manifest.json").write_text(
        json.dumps({"version": "1", "host": "phobos", "entries": []}),
        encoding="utf-8",
    )
    (capsule.rendered / "convergence-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "host": "phobos",
                "rendered_root": ".",
                "execution_identities": {},
                "entries": [],
                "owners": {},
            }
        ),
        encoding="utf-8",
    )
    fixed(TEMPORARY).chmod(0o700)
    store = Mock()
    store.policy.host = "phobos"
    store.mirror.admit.return_value = capsule.revision
    store.verify.return_value = capsule
    return tmp_path, store, capsule


def test_deterministic_closed_plan(inputs, monkeypatch):
    """Ignore caller environment and independently recheck capsule authority."""
    root, store, capsule = inputs
    monkeypatch.setenv("ANSIBLE_CONFIG", "/opt/abhaile/evil.cfg")
    monkeypatch.setenv("PYTHONPATH", "/opt/abhaile/.venv")
    plan = _plan_ansible(store, capsule, ApplyIntent(), filesystem_root=root, owner_uid=os.getuid())
    assert plan == _plan_ansible(
        store, capsule, ApplyIntent(), filesystem_root=root, owner_uid=os.getuid()
    )
    assert plan.executable is False and "--check" in plan.argv
    assert plan.argv[1:4] == ("-I", "-m", "ansible.cli.playbook")
    inventory_index = plan.argv.index("-i")
    assert plan.argv[inventory_index : inventory_index + 2] == ("-i", "localhost,")
    assert plan.cwd == capsule.source
    assert plan.manifest == capsule.rendered / "convergence-manifest.json"
    assert plan.convergence.steps == ()
    assert "/opt/abhaile" not in repr(plan)
    env = dict(plan.environment)
    assert "PYTHONPATH" not in env
    assert "ANSIBLE_INVENTORY" not in env
    assert "ANSIBLE_CALLBACKS_ENABLED" not in env
    assert env["ANSIBLE_INVENTORY_ENABLED"] == "host_list"
    assert env["ANSIBLE_CONFIG"] == str(capsule.source / "ansible/ansible.cfg")
    assert env["ANSIBLE_NO_LOG"] == "True"
    variables = json.loads(plan.argv[plan.argv.index("--extra-vars") + 1])
    assert variables["abhaile_manifest"] == str(plan.manifest)
    assert "abhaile_source_root" not in variables
    store.verify.assert_called_with(capsule.path, capsule.revision)
    store.mirror.admit.assert_called_with(capsule.revision)


@pytest.mark.parametrize("relative", ["usr", "var/lib", "run/abhaile"])
def test_rejects_writable_ancestor(inputs, relative):
    """Validate complete ancestry for each independently protected namespace."""
    root, store, capsule = inputs
    (root / relative).chmod(0o777)
    with pytest.raises(TrustError):
        _plan_ansible(store, capsule, ApplyIntent(), filesystem_root=root, owner_uid=os.getuid())


def test_rejects_runtime_link(inputs):
    """Reject symlink dependencies even inside the fixed runtime."""
    root, store, capsule = inputs
    (root / RUNTIME.relative_to("/") / "injection").symlink_to("/opt/abhaile")
    with pytest.raises(TrustError):
        _plan_ansible(store, capsule, ApplyIntent(), filesystem_root=root, owner_uid=os.getuid())


def test_rejects_forged_capsule(inputs):
    """Reject caller checkout paths before consulting the verifier."""
    root, store, capsule = inputs
    with pytest.raises(TrustError):
        _plan_ansible(
            store,
            replace(capsule, path=root / "checkout"),
            ApplyIntent(),
            filesystem_root=root,
            owner_uid=os.getuid(),
        )
    store.verify.assert_not_called()


@pytest.mark.parametrize(
    "flags,field,expected",
    [
        (["--dry-run"], "dry_run", True),
        (["--dry-run", "--dry-run-validations"], "validations", True),
        (["--prune"], "prune", "safe"),
        (["--force-prune", "--allow-destructive"], "prune", "force"),
        (["--allow-destructive"], "allow_destructive", True),
        (["--json"], "json_report", True),
        (["-vv"], "verbosity", 2),
        (["--host", "phobos"], "prune", "none"),
    ],
)
def test_maps_every_supported_flag(flags, field, expected):
    """Preserve safety requests without executing their deferred semantics."""
    assert getattr(map_apply_intent(parse_apply_args(flags), "phobos"), field) == expected


@pytest.mark.parametrize(
    "flags",
    [
        ["--output", "/tmp"],
        ["--desired-manifest", "/tmp/a"],
        ["--applied-manifest", "/tmp/b"],
        ["--allow-host-mismatch"],
        ["--host", "deimos"],
        ["--prune", "--force-prune"],
        ["--dry-run-validations"],
        ["--force-prune"],
    ],
)
def test_rejects_unsafe_or_conflicting_flags(flags):
    """Fail explicitly for path overrides, host bypasses, and meaningless combinations."""
    with pytest.raises(TrustError):
        map_apply_intent(parse_apply_args(flags), "phobos")


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--dry-run"],
        ["--prune"],
        ["--force-prune"],
        ["--allow-destructive"],
        ["--json"],
        ["-vv"],
    ],
)
def test_cli_remains_unconditionally_quarantined(flags):
    """Keep every future mapped combination unavailable at the production CLI."""
    with pytest.raises(ApplyError, match="experimental and unavailable"):
        main(["--ansible", *flags])


def test_flag_inventory_matches_parser(monkeypatch):
    """Require future CLI options to receive an explicit contract entry."""
    seen: set[str] = set()
    original = argparse.ArgumentParser.add_argument

    def capture(self, *args, **kwargs):
        seen.update(arg for arg in args if arg.startswith("-"))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(argparse.ArgumentParser, "add_argument", capture)
    parse_apply_args([])
    assert seen == set(FLAG_CONTRACT)


def test_secret_channels_stay_closed(capsys, caplog):
    """Never echo an unmistakable synthetic payload through the status boundary."""
    placeholder = "{{ vault_placeholder_TEST_DO_NOT_DISCLOSE }}"
    try:
        raise RuntimeError(placeholder)
    except RuntimeError:
        result = sanitized_result(succeeded=False)
        with pytest.raises(TrustError) as error:
            reject_execution()
    policy = SecretTaskPolicy()
    assert policy.no_log and not policy.diff and not policy.gather_facts
    assert policy.temporary_mode == 0o700 and policy.umask == 0o077
    output = capsys.readouterr()
    captured = (
        json.dumps(result)
        + "".join(traceback.format_exception(error.value))
        + output.out
        + output.err
        + caplog.text
    )
    assert placeholder not in captured


def test_protected_boundary_sanitizes_failures(monkeypatch):
    """Suppress raw verifier errors including their exception chains."""
    import traceback
    from abhaile.trust.ansible import plan_ansible

    placeholder = "{{ vault_placeholder_VERIFIER_FAILURE }}"
    monkeypatch.setattr(
        "abhaile.trust.ansible._plan_ansible", Mock(side_effect=TrustError(placeholder))
    )
    with pytest.raises(TrustError) as error:
        plan_ansible(Mock(), Mock(), ApplyIntent())
    assert placeholder not in "".join(traceback.format_exception(error.value))
