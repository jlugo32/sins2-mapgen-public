import copy

import pytest

from mapgen.spec import SpecError, from_dict


def test_ring_spec_round_trips(ring_spec):
    d = ring_spec.to_dict()
    assert from_dict(copy.deepcopy(d)).to_dict() == d


def test_spec_file_round_trip(ring_spec, tmp_path):
    from mapgen.spec import load
    p = tmp_path / "x.mapspec.json"
    ring_spec.save(p)
    assert load(p).to_dict() == ring_spec.to_dict()


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d.__setitem__("bogus", 1), "Additional properties"),
    (lambda d: d["zones"][0].__setitem__("filling_name", "random_ferrous_planet"), "Additional properties"),
    (lambda d: d["zones"][0].__setitem__("size_tiers", ["XXL"]), "XXL"),
    (lambda d: d["meta"].__setitem__("players", 11), "11"),
    (lambda d: d["links"][0].__setitem__("to_zone", "nowhere"), "unknown zone nowhere"),
    # dead enum values were removed rather than left to fail deep in the compiler
    (lambda d: d["layout"].__setitem__("shape", "grid"),
     "'grid' is not one of ['ring', 'clusters', 'concentric']"),
    (lambda d: d["zones"][4].__setitem__("resource_bias", "none"), "only valid for a zone with no size_tiers"),
    (lambda d: d["zones"][0].__setitem__("loot", "large"), "loot"),
    (lambda d: d.__setitem__("features", {"rifts": 2}), "Harbinger"),
])
def test_spec_rejects(ring_spec, mutate, needle):
    d = ring_spec.to_dict()
    mutate(d)
    with pytest.raises(SpecError) as exc:
        from_dict(d)
    assert needle in str(exc.value)


def test_slot_biases_override_zone_bias(ring_spec):
    from mapgen.compiler import compile_spec
    core = ring_spec.zone("core")
    assert core.resource_bias == "balanced"
    assert core.slot_biases == ["balanced", "crystal", "crystal", "crystal", "crystal", "crystal"]
    m = compile_spec(ring_spec)
    assert sorted(m.nodes[i].bias for i in m.zone_nodes["core"]) == ["balanced"] + ["crystal"] * 5


def test_slot_biases_length_must_match_size_tiers(ring_spec):
    d = ring_spec.to_dict()
    next(z for z in d["zones"] if z["id"] == "core")["slot_biases"] = ["crystal"]
    with pytest.raises(SpecError) as exc:
        from_dict(d)
    assert "slot_biases has 1 entries" in str(exc.value)
