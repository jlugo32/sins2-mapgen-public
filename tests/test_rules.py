import copy
from dataclasses import replace

import pytest

from mapgen import rules
from mapgen.compiler import compile_spec, to_galaxy_chart
from mapgen.config import Limits
from mapgen.params import MapParams
from mapgen.spec import Link
from mapgen.templates import TemplateError, build_ring


def codes(vs):
    return {v.code for v in vs}


def run(spec, limits):
    m = compile_spec(spec)
    return m, to_galaxy_chart(m), rules.check(m, to_galaxy_chart(m), limits)


def test_default_ring_passes_with_only_the_size_warning(ring_spec, cfg):
    m, _, vs = run(ring_spec, cfg.limits)
    assert rules.errors(vs) == []
    # REGION_HOP_SPREAD from 2026-09-24: the ring has always put home_5 twelve hops from a core gate
    # and home_0/3/7 four. That is real and pre-existing; the rule is new, the spread is not.
    assert codes(vs) == {"BODIES_PER_STAR_WARN", "REGION_HOP_SPREAD"}
    assert len(m.planets()) == 100 and len(m.fixtures()) == 16 and len(m.bodies()) == 116


def test_default_counts_match_brief(ring_spec):
    m = compile_spec(ring_spec)
    kinds = {}
    for n in m.planets():
        k = ring_spec.zone(n.zone).kind
        kinds[k] = kinds.get(k, 0) + 1
    assert kinds == {"home": 60, "border": 14, "contested": 5, "core": 6, "filler": 12, "pirate": 3}
    assert sorted((a, b) for a, _, b in m.convoys) == sorted(
        [("home_0", "home_3"), ("home_2", "home_5"), ("home_4", "home_7"), ("home_6", "home_9"), ("home_8", "home_1")])
    assert sorted(s.from_zone for s in m.spokes) == ["home_0", "home_3", "home_7"]


def test_body_limits_come_from_config(ring_spec):
    _, _, vs = run(ring_spec, Limits(warn_bodies_per_star=50, max_bodies_per_star=100, max_stars=10))
    assert "BODIES_PER_STAR_MAX" in codes(rules.errors(vs))


@pytest.mark.parametrize("mutate,code", [
    (lambda c: c["phase_lanes"].append({"id": 9000, "node_a": 1, "node_b": 1}), "SELF_LOOP"),
    (lambda c: c["phase_lanes"].append({**c["phase_lanes"][0], "id": 9001}), "DUPLICATE_LANE"),
    (lambda c: c["phase_lanes"][0].__setitem__("type", "star"), "STAR_LANE_ENDPOINT"),
    (lambda c: c["phase_lanes"][0].__setitem__("type", "wormhole"), "WORMHOLE_LANE_ENDPOINT"),
    (lambda c: c["root_nodes"][0]["child_nodes"][1].__setitem__("filling_name", "random_made_up_planet"),
     "FILLING_UNVERIFIED"),
    (lambda c: c["root_nodes"][0]["child_nodes"][0]["ownership"].__setitem__("player_index", 10),
     "PLAYER_INDEX_RANGE"),
    (lambda c: c["root_nodes"][0]["child_nodes"][0].pop("ownership"), "HOME_PER_PLAYER"),
    (lambda c: c["root_nodes"][0]["child_nodes"].append(
        {"id": 8000, "filling_name": "random_barren_planet", "position": [0, 5000]}), "LANE_MISSING"),
    (lambda c: c["root_nodes"].append(
        {"id": 8001, "filling_name": "random_barren_planet", "position": [0, 9000]}), "PARENT_STAR"),
])
def test_engine_rules_catch_broken_charts(ring_spec, cfg, mutate, code):
    m = compile_spec(ring_spec)
    chart = copy.deepcopy(to_galaxy_chart(m))
    mutate(chart)
    assert code in codes(rules.errors(rules.engine_rules(chart, 10, cfg.limits)))


def test_chokepoint_bypass_is_caught(ring_spec, cfg):
    ring_spec.links.append(Link("filler", "core", "normal"))
    _, _, vs = run(ring_spec, cfg.limits)
    assert "CHOKEPOINT_BYPASS" in codes(rules.errors(vs))


def test_second_lane_into_chokepoint_is_caught(ring_spec, cfg):
    m = compile_spec(ring_spec)
    choke = m.spokes[0].chokepoint
    home0 = m.zone_nodes["home_0"][1]
    m.lanes.append(type(m.lanes[0])(id=99999, a=home0, b=choke))
    vs = rules.design_rules(m)
    assert "CHOKEPOINT_ENTRY" in codes(vs)


def test_gas_giant_in_home_is_caught(cfg):
    p = MapParams(home_slot_tiers=["L", "XL", "M", "S", "S"])  # slot 1 is balanced → gas giant
    _, _, vs = run(build_ring(p, cfg.limits.max_bodies_per_star), cfg.limits)
    assert {"GAS_GIANT_PLACEMENT", "HOME_TIER_BIAS"} <= codes(rules.errors(vs))


def test_two_research_gated_planets_in_home_are_caught(cfg):
    p = MapParams(home_slot_tiers=["L", "L", "M", "S", "M"])  # irradiated (R) + volcanic (R)
    _, _, vs = run(build_ring(p, cfg.limits.max_bodies_per_star), cfg.limits)
    assert "HOME_RESEARCH_GATED" in codes(rules.errors(vs))


def test_home_cluster_has_at_most_one_research_gated(ring_spec):
    m = compile_spec(ring_spec)
    for z in (z for z in ring_spec.zones if z.kind == "home"):
        assert sum(m.nodes[i].research_gated for i in m.zone_nodes[z.id]) <= 1


@pytest.mark.parametrize("players,planets", [(6, 70), (8, 90), (10, 120)])
def test_rescaled_rings_build_clean(cfg, players, planets):
    access = [0, 3] if players < 8 else [0, 3, 7]
    majors = [0, 2] if players < 8 else [0, 2, 5, 7]
    p = MapParams(players=players, planets=planets, core_access=access, major_borders=majors)
    _, _, vs = run(build_ring(p, cfg.limits.max_bodies_per_star), cfg.limits)
    assert rules.errors(vs) == []


@pytest.mark.parametrize("kw,constraint", [
    ({"players": 9}, "CONVOY_MATCHING"),
    ({"planets": 80}, "PLANET_BUDGET"),
    ({"core_access": [0, 12]}, "CORE_ACCESS"),
    ({"convoy_skip": 1}, "CONVOY_MATCHING"),
    ({"players": 11}, "PLAYERS_RANGE"),
])
def test_unsatisfiable_counts_name_the_constraint(kw, constraint):
    with pytest.raises(TemplateError) as exc:
        build_ring(replace(MapParams(), **kw), 150)
    assert exc.value.constraint == constraint


def test_balance_check_warns_when_advantages_stack(cfg):
    p = MapParams(major_borders=[0, 2, 5, 7])  # pre-load-test layout: majors on core-access borders
    m = compile_spec(build_ring(p, cfg.limits.max_bodies_per_star))
    vs = rules.balance_rules(m)
    assert codes(vs) == {"REGION_ADVANTAGE_STACK"}
    assert vs[0].severity == "warning"
    adv = rules.region_advantages(m)
    assert [r for r, (core, majors) in adv.items() if core and majors] == ["home_0", "home_3", "home_7"]
    assert [r for r, (core, majors) in adv.items() if not core and not majors] == ["home_4", "home_9"]


def test_default_majors_do_not_stack_with_core_access(ring_spec):
    m = compile_spec(ring_spec)
    assert rules.balance_rules(m) == []
    adv = rules.region_advantages(m)
    assert not [r for r, (core, majors) in adv.items() if core and majors]
    assert not [r for r, (core, majors) in adv.items() if not core and not majors]


def test_core_is_one_gas_giant_plus_crystalline(ring_spec):
    m = compile_spec(ring_spec)
    core = sorted(m.nodes[i].filling_name for i in m.zone_nodes["core"])
    assert core == ["random_crystalline_planet"] * 5 + ["random_gas_giant_planet"]
    assert sum(sum(m.nodes[i].crystal) / 2 for i in m.zone_nodes["core"]) == 56.5


def test_home_cluster_has_two_ferrous_and_no_barren(ring_spec):
    m = compile_spec(ring_spec)
    ids = [i for i in m.zone_nodes["home_0"] if m.nodes[i].role != "home"]
    names = sorted(m.nodes[i].filling_name for i in ids)
    assert names == ["random_desert_planet", "random_ferrous_planet", "random_ferrous_planet",
                     "random_ship_graveyard_planet", "random_volcanic_planet"]
    assert sum(sum(m.nodes[i].metal) / 2 for i in ids) == 34.5
    assert sum(sum(m.nodes[i].crystal) / 2 for i in ids) == 6.5


def test_crystal_reachable_outside_the_core_clears_the_floor(ring_spec):
    from mapgen.pipeline import reachable_resources
    data = reachable_resources(compile_spec(ring_spec))
    assert min(crystal for _, crystal, _ in data.values()) == 22
    assert all(crystal >= 15 for _, crystal, _ in data.values())


# --------------------------------------------------------------- regressions from the live smoke call
# specs/six_ring_center.mapspec.json is the exact model output that broke the compiler: an ungated
# 12-planet contested centre, linked normally from every home, with no wormholes at all.
import math  # noqa: E402

from mapgen import ROOT  # noqa: E402
from mapgen.spec import Link, load  # noqa: E402

LIVE_SPEC = ROOT / "specs" / "six_ring_center.mapspec.json"


@pytest.fixture
def live_spec():
    return load(LIVE_SPEC)


def test_ungated_centre_with_no_access_links_compiles(live_spec, cfg):
    """place_core used to assume >= 1 chokepoint link and raised IndexError."""
    centre = next(z for z in live_spec.zones if z.placement.kind == "center")
    assert not centre.gated and centre.chokepoints == 0
    assert not [l for l in live_spec.links if l.chokepoint]
    m, _, vs = run(live_spec, cfg.limits)
    assert rules.errors(vs) == [], [v.code for v in rules.errors(vs)]
    assert len(m.zone_nodes[centre.id]) == centre.planet_count
    assert len(m.planets()) == live_spec.constraints.total_planets


def test_large_centre_keeps_minimum_spacing(live_spec):
    """A 12-planet centre is spread over concentric rings; nothing may collide."""
    from mapgen.params import Geometry
    m = compile_spec(live_spec)
    centre = next(z for z in live_spec.zones if z.placement.kind == "center")
    ids = m.zone_nodes[centre.id]
    assert len(ids) >= 12
    floor = Geometry().min_spacing
    worst = min(math.dist(m.nodes[a].pos, m.nodes[b].pos)
                for i, a in enumerate(ids) for b in ids[i + 1:])
    assert worst >= floor, f"centre planets {worst:.0f} apart, below min_spacing {floor}"
    every = [n for n in m.bodies()]
    worst_all = min(math.dist(a.pos, b.pos) for i, a in enumerate(every) for b in every[i + 1:])
    assert worst_all >= floor, f"two bodies {worst_all:.0f} apart, below min_spacing {floor}"


def test_contested_zone_without_convoys_is_accepted(live_spec, cfg):
    """COUNT_CONVOYS used to demand one convoy per region whenever a contested zone existed."""
    assert any(z.kind == "contested" for z in live_spec.zones)
    assert not [l for l in live_spec.links if l.lane == "wormhole"]
    _, _, vs = run(live_spec, cfg.limits)
    assert "COUNT_CONVOYS" not in codes(vs)


def test_declared_convoy_that_does_not_compile_still_fails(ring_spec):
    """The spec declares 5 convoys; if the compiler wires fewer, the counts must disagree."""
    m = compile_spec(ring_spec)
    assert len(m.convoys) == 5
    m.convoys.pop()                        # stand in for a compiler that dropped one
    vs = rules.design_rules(m)
    assert "COUNT_CONVOYS" in codes(rules.errors(vs))
    assert "spec declares 1 convoys, compiled 0" in next(
        v.message for v in vs if v.code == "COUNT_CONVOYS")


def test_convoy_without_a_return_leg_is_not_a_convoy(ring_spec, cfg):
    """An entry wormhole with no exit lane is a dead-end outpost: declared 0, compiled 0, no error."""
    ring_spec.links = [l for l in ring_spec.links
                       if not (l.from_zone == "convoy_0" and l.to_zone == "home_3")]
    m, _, vs = run(ring_spec, cfg.limits)
    assert rules.errors(vs) == [], [v.code for v in rules.errors(vs)]
    assert len(m.convoys) == 4


def test_ring_convoy_counts_still_match(ring_spec, cfg):
    _, _, vs = run(ring_spec, cfg.limits)
    assert "COUNT_CONVOYS" not in codes(vs)
    m = compile_spec(ring_spec)
    assert len(m.convoys) == 5


# ------------------------------------------------------- DUPLICATE_LANE from gap zones (live session)
# specs/eastern_front_2024.mapspec.json is the map from the 2026-09-22 live chat session. Only the
# post-repair spec was saved, so the triggering shape (a link between two gap-placed zones) is added
# back here: that is what produced DUPLICATE_LANE on both live requests.
LIVE_CHAT_SPEC = ROOT / "specs" / "eastern_front_2024.mapspec.json"


def pairs_with_two_lanes(m):
    from collections import Counter
    return [sorted(p) for p, n in Counter(frozenset((l.a, l.b)) for l in m.lanes).items() if n > 1]


def test_live_chat_spec_still_builds_clean(cfg):
    spec = load(LIVE_CHAT_SPEC)
    m, _, vs = run(spec, cfg.limits)
    assert rules.errors(vs) == [], [v.code for v in rules.errors(vs)]
    assert pairs_with_two_lanes(m) == []
    assert len(m.planets()) == spec.constraints.total_planets


@pytest.mark.parametrize("a,b", [("filler", "pirates_west"), ("pirates_west", "pirates_east")])
def test_link_between_gap_zones_makes_no_duplicate_lane(cfg, a, b):
    spec = load(LIVE_CHAT_SPEC)
    spec.links.append(Link(a, b, "normal"))
    m, _, vs = run(spec, cfg.limits)
    assert "DUPLICATE_LANE" not in codes(rules.errors(vs)), [v.message for v in rules.errors(vs)]
    assert pairs_with_two_lanes(m) == []


def test_ring_link_between_filler_and_pirates_makes_no_duplicate_lane(ring_spec, cfg):
    ring_spec.links.append(Link("filler", "pirates", "normal"))
    m, _, vs = run(ring_spec, cfg.limits)
    assert "DUPLICATE_LANE" not in codes(rules.errors(vs))
    assert pairs_with_two_lanes(m) == []
    assert rules.errors(vs) == []


def test_duplicate_lane_rule_still_fires_when_a_chart_really_has_one(ring_spec, cfg):
    """The compiler stops producing them; the rule must still catch them."""
    m = compile_spec(ring_spec)
    chart = to_galaxy_chart(m)
    chart["phase_lanes"].append({**chart["phase_lanes"][0], "id": 99999})
    assert "DUPLICATE_LANE" in codes(rules.errors(rules.engine_rules(chart, 10, cfg.limits)))


# ------------------------------------------------------------------ clusters layout (WW2 global map)
WW2_SPEC = ROOT / "specs" / "ww2_global.mapspec.json"


def test_clusters_map_builds_with_only_the_expected_warnings(cfg):
    """Asymmetric by design: REGION_ADVANTAGE_STACK and the size warning are correct here."""
    m, _, vs = run(load(WW2_SPEC), cfg.limits)
    assert rules.errors(vs) == [], [v.code for v in rules.errors(vs)]
    # GATEWAY_SPREAD from 2026-09-25: italy and turkey have always had all their external lanes on
    # one planet while spain has three. Real and pre-existing; the rule is new, the imbalance is not.
    assert codes(vs) == {"BODIES_PER_STAR_WARN", "REGION_ADVANTAGE_STACK", "REGION_HOP_SPREAD",
                         "GATEWAY_SPREAD"}
    assert len(m.planets()) == 111 and len(m.fixtures()) == 14 and len(m.bodies()) == 125


def test_clusters_gated_fields_are_really_gated(cfg):
    spec = load(WW2_SPEC)
    m = compile_spec(spec)
    gated = [z for z in spec.zones if z.gated]
    assert len(gated) == 4, "four oil fields"
    assert "CHOKEPOINT_BYPASS" not in codes(rules.design_rules(m))
    # a land chokepoint has no fixtures: the spoke is entry -> chokepoint
    land = [s for s in m.spokes if len(s.path) == 2]
    assert len(land) == 5, "five gated chokepoint links, all land routes"


def test_zones_sharing_two_anchors_do_not_collide(cfg):
    """f_gibraltar and x_med_north_africa both sit between spain and italy."""
    m = compile_spec(load(WW2_SPEC))
    a = m.zone_nodes["f_gibraltar"][0]
    b = m.zone_nodes["x_med_north_africa"][0]
    assert math.dist(m.nodes[a].pos, m.nodes[b].pos) >= MapParams().geometry.min_spacing


def test_min_spacing_rule_catches_overlapping_bodies(ring_spec):
    m = compile_spec(ring_spec)
    assert rules.spacing_rules(m) == []
    m.nodes[2].pos = m.nodes[1].pos                 # drop one planet onto another
    vs = rules.spacing_rules(m)
    assert [v.code for v in vs] == ["MIN_SPACING"] and vs[0].severity == "error"
