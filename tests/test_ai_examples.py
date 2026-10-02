"""Offline checks for the AI layer: no API call.

Every few-shot answer must validate against the wrapper schema and build clean through the compiler,
and the wire schema must respect the documented structured-outputs limits.
"""
import json

import pytest

from mapgen import rules
from mapgen.ai import prompts
from mapgen.ai.schemas import MAX_QUESTIONS, strict_schema, validation_errors, wire_schema
from mapgen.ai.translate import interpret
from mapgen.params import MapParams
from mapgen.pipeline import build
from mapgen.spec import SpecError

UNSUPPORTED = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
               "minLength", "maxLength", "maxItems", "uniqueItems", "oneOf", "not")


def walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


@pytest.mark.parametrize("name", list(prompts.EXAMPLE_REQUESTS))
def test_few_shot_examples_validate_and_build(name, cfg, tmp_path):
    request, answer = next((r, a) for (r, a) in prompts.examples() if r == prompts.EXAMPLE_REQUESTS[name])
    assert validation_errors(answer) == []
    t = interpret(answer)
    assert t.spec is not None and not t.asked
    res = build(t.spec, MapParams(), cfg, tmp_path / name)
    assert rules.errors(res.violations) == [], [v.code for v in res.violations]
    assert res.ok, [str(p) for p in res.problems]
    assert len(res.compiled.planets()) == t.spec.constraints.total_planets


def test_wire_schema_has_no_unsupported_keywords():
    for node in walk(wire_schema()):
        for key in UNSUPPORTED:
            assert key not in node, f"{key} reached the wire schema"
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False
        if "minItems" in node:
            assert node["minItems"] in (0, 1)


def test_wire_schema_within_documented_limits():
    optional = union = 0
    for node in walk(wire_schema()):
        if node.get("type") == "object" and "properties" in node:
            optional += len(set(node["properties"]) - set(node.get("required", [])))
        if "anyOf" in node or isinstance(node.get("type"), list):
            union += 1
    assert optional <= 24, f"{optional} optional parameters (limit 24)"
    assert union <= 16, f"{union} union-typed parameters (limit 16)"


def test_strict_schema_rejects_both_branches(ring_spec):
    both = {"spec": ring_spec.to_dict(), "clarifying_questions": ["which?"]}
    assert validation_errors(both), "a response with both branches must fail"
    with pytest.raises(SpecError):
        interpret(both)
    assert "oneOf" in strict_schema()


def test_questions_branch_blocks_the_build():
    t = interpret({"clarifying_questions": ["How many players?"]})
    assert t.asked and t.spec is None and t.questions == ["How many players?"]
    assert validation_errors({"clarifying_questions": ["q"] * (MAX_QUESTIONS + 1)})
    assert validation_errors({"clarifying_questions": []})


def test_empty_and_unknown_fields_are_rejected(ring_spec):
    assert validation_errors({})
    assert validation_errors({"spec": ring_spec.to_dict(), "bogus": 1})
    bad = ring_spec.to_dict()
    bad["zones"][0]["filling_name"] = "random_ferrous_planet"
    assert validation_errors({"spec": bad})


def test_system_prompt_carries_the_verified_rules(cfg):
    s = prompts.system_prompt(cfg.limits)
    for needle in (str(cfg.limits.warn_bodies_per_star), str(cfg.limits.max_bodies_per_star),
                   "wormhole lanes only ever join two wormhole fixtures".capitalize()[:20],
                   "one home planet per player", "NO planet-type ownership restriction",
                   "XL balanced planet and is core-only", "one research-gated planet per home cluster",
                   "NEVER write filling names"):
        assert needle.lower() in s.lower(), needle
    assert "random_ferrous_planet" in s  # named only as an example of what NOT to write


def test_messages_carry_three_examples_then_the_request():
    msgs = prompts.messages("build me something", seed=5)
    assert len(msgs) == 7 and [m["role"] for m in msgs] == ["user", "assistant"] * 3 + ["user"]
    assert "seed 5" in msgs[-1]["content"]
    for m in msgs[1::2]:
        assert validation_errors(json.loads(m["content"])) == []


# --------------------------------------------------------------------------- stripped constraints
def bad_payloads(spec_dict):
    """Each payload breaks a constraint the wire schema no longer carries."""
    players = json.loads(json.dumps(spec_dict))
    players["meta"]["players"] = 12                       # schema maximum: 10
    negative = json.loads(json.dumps(spec_dict))
    negative["zones"][0]["planet_count"] = -3             # schema minimum: 1
    mismatch = json.loads(json.dumps(spec_dict))
    core = next(z for z in mismatch["zones"] if z["id"] == "core")
    core["slot_biases"] = ["crystal"]                     # cross-field: one per size_tiers entry
    empty = json.loads(json.dumps(spec_dict))
    empty["zones"] = []
    return {"players_over_max": players, "negative_planet_count": negative,
            "slot_biases_length": mismatch, "empty_zones": empty}


@pytest.mark.parametrize("case", ["players_over_max", "negative_planet_count", "slot_biases_length",
                                  "empty_zones"])
def test_stripped_constraints_are_still_enforced_locally(ring_spec, case):
    payload = {"spec": bad_payloads(ring_spec.to_dict())[case]}
    with pytest.raises(SpecError):
        interpret(payload)
    if case != "slot_biases_length":      # that one is a cross-field rule, not expressible in JSON Schema
        assert validation_errors(payload), f"{case} passed the strict schema"
    else:
        from mapgen.spec import from_dict
        assert validation_errors(payload) == []
        with pytest.raises(SpecError):
            from_dict(payload["spec"])


def test_wire_schema_really_lacks_the_stripped_keywords():
    """Guards the test above: it must not pass because the wire schema still carries the constraints."""
    nodes = list(walk(wire_schema()))
    for keyword in ("maximum", "minimum", "maxLength", "minLength", "maxItems", "multipleOf"):
        assert not any(keyword in n for n in nodes), f"{keyword} still on the wire"
    # the wire root is a bare anyOf with every $ref inlined: the API rejects siblings next to anyOf
    w = wire_schema()
    assert list(w) == ["anyOf"] and "$ref" not in json.dumps(w) and "$defs" not in json.dumps(w)
    mapspec = w["anyOf"][0]["properties"]["spec"]["properties"]
    assert mapspec["meta"]["properties"]["players"] == {"type": "integer",
                                                        "description": "(minimum: 2; maximum: 10)"}
    count = mapspec["zones"]["items"]["properties"]["planet_count"]
    assert "minimum" not in count and "minimum: 1" in count.get("description", "")
    # minItems 0/1 IS supported by structured outputs, so it legitimately stays
    assert mapspec["zones"]["minItems"] == 1


# --------------------------------------------------------------------------- few-shot sync
@pytest.mark.parametrize("name", list(prompts.EXAMPLE_REQUESTS))
def test_few_shot_totals_match_zone_sums(name, cfg, tmp_path):
    """total_planets must equal the sum of zone planet_counts, and the example must compile clean."""
    answer = dict(prompts.examples()[list(prompts.EXAMPLE_REQUESTS).index(name)][1])
    assert validation_errors(answer) == []
    spec = interpret(answer).spec
    declared = spec.constraints.total_planets
    summed = sum(z.planet_count for z in spec.zones)
    assert declared == summed, f"{name}: total_planets {declared} != zone sum {summed}"
    res = build(spec, MapParams(), cfg, tmp_path / name)
    assert res.ok and not rules.errors(res.violations)
    assert len(res.compiled.planets()) == declared


def test_every_example_file_is_used_as_a_few_shot():
    from mapgen.ai.prompts import EXAMPLES_DIR
    on_disk = {p.name.replace(".mapspec.json", "") for p in EXAMPLES_DIR.glob("*.mapspec.json")}
    assert on_disk <= set(prompts.EXAMPLE_REQUESTS), "example file not wired into the prompt"
