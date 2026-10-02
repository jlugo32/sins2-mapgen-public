"""The concentric layout and the balance guarantees that depend on it.

specs/three_rings.mapspec.json is the worked example: three decagon bands plus a gated core.
"""
import collections
import math

import pytest

from mapgen import ROOT, rules
from mapgen.compiler import compile_spec
from mapgen.scenario_writer import to_galaxy_chart
from mapgen.spec import load

SPEC = ROOT / "specs" / "three_rings.mapspec.json"
SEEDS = (3, 11, 42)


@pytest.fixture(scope="module")
def three_rings():
    return compile_spec(load(SPEC))


def compiled(seed):
    spec = load(SPEC)
    spec.meta.seed = seed
    return compile_spec(spec)


def crystal(m, nid):
    """crystal_mean, not the midpoint: player_home_planet is a weighted roll whose range is [0, 8]
    but whose mean is 3.5 (see mapgen/fillings.py Resolved)."""
    return 0 if m.nodes[nid].role == "star" else m.nodes[nid].crystal_mean


def hops_from_homes(m):
    """Lane-hop distance from each player home, never passing through the gated core."""
    gated = {i for z in m.spec.zones if z.gated for i in m.zone_nodes[z.id]}
    adj = collections.defaultdict(set)
    for lane in m.lanes:
        adj[lane.a].add(lane.b)
        adj[lane.b].add(lane.a)
    out = {}
    for z in m.spec.zones:
        if z.kind != "home":
            continue
        start = next(i for i in m.zone_nodes[z.id] if m.nodes[i].role == "home")
        dist = {start: 0}
        queue = collections.deque([start])
        while queue:
            x = queue.popleft()
            for y in adj[x]:
                if y not in dist and y not in gated:
                    dist[y] = dist[x] + 1
                    queue.append(y)
        out[z.id] = dist
    return out


# ------------------------------------------------------------------ placement
def test_bands_sit_on_their_radii(three_rings):
    m = three_rings
    radii = m.spec.layout.band_radii
    assert len(radii) == 3
    for z in m.spec.zones:
        if z.placement.kind != "band":
            continue
        ids = m.zone_nodes[z.id]
        r = sum(math.dist((0.0, 0.0), m.nodes[i].pos) for i in ids) / len(ids)
        expected = radii[z.placement.band]
        outer = max(math.dist((0.0, 0.0), n.pos) for n in m.nodes if n.role != "star")
        assert r < outer * (expected + 0.25), f"{z.id} sits outside band {z.placement.band}"


def test_band_order_is_outer_home_then_contested_then_custom(three_rings):
    m = three_rings
    def mean_r(kind):
        ids = [i for z in m.spec.zones if z.kind == kind and z.placement.kind == "band"
               for i in m.zone_nodes[z.id]]
        return sum(math.dist((0.0, 0.0), m.nodes[i].pos) for i in ids) / len(ids)
    assert mean_r("home") > mean_r("contested") > mean_r("custom")


def test_middle_ring_is_identical_in_every_slot(three_rings):
    m = three_rings
    totals = {z.id: sum(crystal(m, i) for i in m.zone_nodes[z.id])
              for z in m.spec.zones if z.kind == "contested"}
    assert len(totals) == 10
    assert len(set(totals.values())) == 1, totals


# ------------------------------------------------------------------ balance
@pytest.mark.parametrize("seed", SEEDS)
def test_opening_crystal_is_even_for_every_player(seed):
    """The opening must not depend on the seed or on which home you drew.

    Before 2026-09-24 the two-hop figure ranged 20.0-35.0: filler scattered into any free spot could
    drop 10 crystal on one player's doorstep and none on six others, and the inter-home lane
    attached to whichever planet was still free, so what you could see from your capital depended on
    the order links happened to be wired in.

    One hop is exact. Two hops is bounded rather than exact, and deliberately so: the 2026-09-25
    attachment policy spreads a zone's external lanes across distinct planets, which is what stops a
    home being held with one starbase, and the price is that a home's two mid-ring lanes can land on
    two oceanic planets (5.0 each) or on an ice and an oceanic (7.0 + 5.0). That is a 2.0 band. The
    alternative - pinning those lanes too - buys spread 0.0 back at the cost of single-gateway home
    zones, which is the trade recorded in FINDINGS.md §12.4.
    """
    m = compiled(seed)
    reach = {home: sum(crystal(m, i) for i, k in dist.items() if k <= 1)
             for home, dist in hops_from_homes(m).items()}
    assert len(set(reach.values())) == 1, f"1-hop crystal differs on seed {seed}: {reach}"
    two = {home: sum(crystal(m, i) for i, k in dist.items() if k <= 2)
           for home, dist in hops_from_homes(m).items()}
    assert max(two.values()) - min(two.values()) <= 2.0, f"2-hop spread on seed {seed}: {two}"


@pytest.mark.parametrize("seed", SEEDS)
def test_every_home_zone_has_three_distinct_entrances(seed):
    """A home held with one starbase is not the same map as a home that needs three.

    Added 2026-09-25. home_0/4/7 funnelled all five external lanes onto a single planet; three
    gateways is the structural maximum at planet_count 4, since eligible() never targets the home
    planet itself.
    """
    m = compiled(seed)
    zone_of = {i: z for z, ids in m.zone_nodes.items() for i in ids}
    for z in (z for z in m.spec.zones if z.kind == "home"):
        ids = set(m.zone_nodes[z.id])
        ext = {a for lane in m.lanes for a, b in ((lane.a, lane.b), (lane.b, lane.a))
               if a in ids and zone_of.get(b) != z.id}
        assert len(ext) == 3, f"{z.id} has {len(ext)} entrances on seed {seed}"


@pytest.mark.parametrize("seed", SEEDS)
def test_expansion_is_forced(seed):
    """Every home must start crystal-poor enough that sitting still loses."""
    m = compiled(seed)
    for home, dist in hops_from_homes(m).items():
        own = sum(crystal(m, i) for i, k in dist.items() if k <= 1)
        # 10.0 = 6.5 from the zone's other planets + 3.5 expected on the home planet itself, which
        # the game rolls (random_fair_planet). Before 2026-09-25 the home planet counted as 0 and
        # this read 6.5. The bar is scarcity, not a specific number: a normal TEC opening spends
        # about 1,014 crystal in ten minutes, so anything near a single ring zone is still poor.
        assert own < 12, f"{home} starts with {own} crystal in reach on seed {seed}"


def test_no_filler_planet_touches_a_home_zone(three_rings):
    m = three_rings
    homes = {i for z in m.spec.zones if z.kind == "home" for i in m.zone_nodes[z.id]}
    gaps = {i for z in m.spec.zones if z.kind in ("filler", "pirate") for i in m.zone_nodes[z.id]}
    touching = [(a, b) for lane in m.lanes for a, b in [(lane.a, lane.b)]
                if (a in gaps and b in homes) or (b in gaps and a in homes)]
    assert touching == []


# ------------------------------------------------------------------ rules
def test_hop_spread_to_the_core_is_reported(three_rings, cfg):
    """4-6 hops is deliberate and legible, so it must sit inside the configured tolerance -
    but region_distances must still measure it rather than stay silent."""
    dist = rules.region_distances(three_rings)
    gates = [d["gate"] for d in dist.values()]
    assert (min(gates), max(gates)) == (4, 6)
    assert max(gates) - min(gates) <= cfg.limits.max_region_hop_spread


def test_a_tighter_tolerance_makes_the_core_spread_fire(three_rings):
    vs = rules.proximity_rules(three_rings, max_spread=1)
    assert [v.code for v in vs] == ["REGION_HOP_SPREAD"]
    assert vs[0].severity == "warning"
    assert "home_5" in vs[0].message and "home_0" in vs[0].message


def test_region_advantage_stack_reports_that_it_saw_nothing(three_rings):
    """The silent pass this whole rule family exists to prevent: three_rings has a gated core, but
    access is expressed through inner-ring spokes that region_advantages cannot read."""
    vs = rules.balance_rules(three_rings)
    assert [v.code for v in vs] == ["BALANCE_RULE_BLIND"]
    assert "REGION_ADVANTAGE_STACK" in vs[0].message


def test_blind_warning_stays_quiet_when_the_feature_is_absent(cfg):
    """A map with no gated zones and no border fields has nothing to be blind about."""
    m = compile_spec(load(ROOT / "specs" / "skill_test_quad.mapspec.json"))
    assert rules.check(m, to_galaxy_chart(m), cfg.limits) == []


def test_three_rings_has_no_errors(three_rings, cfg):
    vs = rules.check(three_rings, to_galaxy_chart(three_rings), cfg.limits)
    assert rules.errors(vs) == [], [v.code for v in rules.errors(vs)]
    assert {v.code for v in vs} == {"BODIES_PER_STAR_WARN", "BALANCE_RULE_BLIND"}


def test_counts_match_the_approved_design(three_rings):
    m = three_rings
    assert len(m.planets()) == 103
    assert len(m.bodies()) == 113
    assert len({s.chokepoint for s in m.spokes}) == 3
    assert all(m.nodes[s.chokepoint].filling_name == "random_city_planet" for s in m.spokes)


# ------------------------------------------------------------------ inner-ring arcs
def test_inner_ring_is_three_arcs_each_owning_one_core_gate(three_rings):
    """--inner-arcs 3, chosen 2026-09-24.

    The cut points land on the spoke vertices (0, 3, 7), so each arc is a wedge that owns exactly
    one core entrance, and the worst lateral inner-to-inner trip goes from 5 hops to 8 - which
    closes the "lap the inner ring and hit someone's rear" route. It costs nothing at the opening:
    the path to a gate is radial (home -> mid -> inner -> gate) and never runs around the ring, so
    hops to the core stay 4-6. --inner-arcs 2 costs the same for a lopsided 2/1 gate split.
    """
    m = three_rings
    inner = {z.id: m.zone_nodes[z.id][0] for z in m.spec.zones if z.id.startswith("inner_")}
    by_node = {n: z for z, n in inner.items()}
    adj = collections.defaultdict(set)
    for lane in m.lanes:
        if lane.a in by_node and lane.b in by_node:
            adj[lane.a].add(lane.b)
            adj[lane.b].add(lane.a)
    assert sum(len(v) for v in adj.values()) // 2 == 7, "expected 7 lateral inner lanes (10 - 3 gaps)"

    seen, arcs = set(), []
    for nid in inner.values():
        if nid in seen:
            continue
        comp, queue = {nid}, collections.deque([nid])
        while queue:
            x = queue.popleft()
            for y in adj[x]:
                if y not in comp:
                    comp.add(y)
                    queue.append(y)
        seen |= comp
        arcs.append(comp)
    assert len(arcs) == 3, f"inner ring should fall into 3 arcs, got {len(arcs)}"

    gates = {s.from_zone for s in m.spokes}
    per_arc = sorted(sum(1 for n in arc if by_node[n] in gates) for arc in arcs)
    assert per_arc == [1, 1, 1], f"each arc must own exactly one core gate, got {per_arc}"


def test_arcs_do_not_shorten_the_route_to_the_core(three_rings):
    """Cutting the inner ring must not change core access - that stays the 4-6 hop design."""
    gates = [d["gate"] for d in rules.region_distances(three_rings).values()]
    assert (min(gates), max(gates)) == (4, 6)
