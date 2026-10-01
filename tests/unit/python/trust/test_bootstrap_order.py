"""Test lifecycle ownership and prerequisite ordering without host access."""

from dataclasses import replace

import pytest

from abhaile.trust.bootstrap_order import (
    FOUNDATION_STEPS,
    FoundationOwner,
    convergence_may_manage,
    foundation_order,
)
from abhaile.trust.errors import TrustError


def test_foundations_follow_declared_dependencies() -> None:
    order = foundation_order()
    positions = {name: index for index, name in enumerate(order)}
    for step in FOUNDATION_STEPS:
        assert all(positions[requirement] < positions[step.name] for requirement in step.requires)


def test_credentials_and_trust_are_preserved_during_adoption() -> None:
    protected = {
        "deploy-key",
        "pinned-known-hosts",
        "protected-launcher",
        "protected-python-runtime",
        "protected-ansible-runtime",
    }
    steps = {step.name: step for step in FOUNDATION_STEPS}
    for name in protected:
        assert steps[name].preserve_existing is True
        assert convergence_may_manage(steps[name], fresh_enrollment=False) is False


def test_sudo_install_and_live_proof_remain_adoption_work() -> None:
    step = next(step for step in FOUNDATION_STEPS if step.name == "sudo-candidate-validation")
    assert step.owner is FoundationOwner.ADOPTION
    assert step.live_proof_phase == 6
    assert convergence_may_manage(step, fresh_enrollment=False) is False


def test_incomplete_and_cyclic_graphs_fail_closed() -> None:
    with pytest.raises(TrustError):
        foundation_order((replace(FOUNDATION_STEPS[0], requires=("missing",)),))
    first = replace(FOUNDATION_STEPS[0], requires=(FOUNDATION_STEPS[1].name,))
    second = replace(FOUNDATION_STEPS[1], requires=(FOUNDATION_STEPS[0].name,))
    with pytest.raises(TrustError):
        foundation_order((first, second))
