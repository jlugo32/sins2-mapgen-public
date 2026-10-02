"""Pinned hashes of the rule functions.

repair.py fingerprints the rules at runtime, which catches tampering inside a single run. This catches
a rule that was weakened between runs: change rules.py and this test fails until the pin is updated.

Hashes cover the function source (not bytecode), so a Python upgrade does not move them.
"""
import hashlib
import inspect

import pytest

from mapgen import rules

# Updated 2026-09-23: MIN_SPACING added (a new rule, a tightening - nothing was loosened). The clusters
# layout put two planets at distance 0 and no rule caught it; 'check' changed only to call it.
# Updated 2026-09-24: REGION_HOP_SPREAD added and BALANCE_RULE_BLIND added to balance_rules. Both are
# tightenings. three_rings put one home 6 lane-hops from a core gate and three others 4, and nothing
# measured distance-to-advantage; separately REGION_ADVANTAGE_STACK returned clean there because all
# of its inputs were empty, which read as a pass. 'check' changed only to call proximity_rules.
# Updated 2026-09-25: GATEWAY_SPREAD added (a new rule, a tightening). Three of the ten home zones
# on three_rings funnelled all five external lanes onto a single planet while others spread across
# three - one starbase held a zone that should have cost three. Every rule we had measured resources
# or distance, none measured how many places a defender must cover. 'check' changed only to call it.
PINNED = {
    "check": "bdadce9fe8ef77e3",
    "engine_rules": "fb6b9536ee75ea17",
    "design_rules": "da0a4cc6f039cf8d",
    "balance_rules": "ae53a3023275903f",
    "spacing_rules": "9dc0e6b3bf482360",
    "proximity_rules": "3024ceb86f6733e2",
    "gateway_rules": "876b6aa1429f5466",
}

MESSAGE = ("rules.py changed - if intentional, update the pinned hash in tests/test_rule_fingerprints.py "
           "and say why in the commit message. A rule may only be added or tightened; loosening one "
           "needs an explicit decision recorded in BRIEF.md.")


@pytest.mark.parametrize("name,pinned", sorted(PINNED.items()))
def test_rule_source_is_pinned(name, pinned):
    got = hashlib.sha256(inspect.getsource(getattr(rules, name)).encode()).hexdigest()[:16]
    assert got == pinned, f"{name}: {got} != {pinned}\n{MESSAGE}"


def test_every_rule_function_is_pinned():
    """A new rule entry point must be pinned too, or it could be weakened unnoticed."""
    public = {n for n, fn in vars(rules).items()
              if callable(fn) and not n.startswith("_")
              and getattr(fn, "__module__", "") == rules.__name__
              and (n.endswith("rules") or n == "check")}
    assert public - set(PINNED) == set(), f"unpinned rule functions: {sorted(public - set(PINNED))}\n{MESSAGE}"


def test_runtime_fingerprint_matches_the_pinned_functions(cfg):
    """The runtime guard in repair.py must watch the same functions this test pins."""
    from mapgen.ai.repair import _fingerprint
    fp = _fingerprint(cfg.limits)
    assert rules.check.__code__.co_code in fp
    assert rules.engine_rules.__code__.co_code in fp
    assert rules.design_rules.__code__.co_code in fp
    assert rules.balance_rules.__code__.co_code in fp
    assert rules.spacing_rules.__code__.co_code in fp
    assert rules.proximity_rules.__code__.co_code in fp
    assert rules.gateway_rules.__code__.co_code in fp
    assert cfg.limits.warn_bodies_per_star in fp and cfg.limits.max_bodies_per_star in fp
    assert cfg.limits.max_region_hop_spread in fp
