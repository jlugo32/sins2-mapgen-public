"""Rule checks (BRIEF S1). Any error-severity violation means no output.

Engine rules read the galaxy_chart dict that will actually be written. Design rules read the CompiledMap.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field

from . import fillings
from .compiler import CompiledMap
from .config import Limits


@dataclass
class Violation:
    code: str
    message: str
    hint: str
    node_ids: list[int] = field(default_factory=list)
    severity: str = "error"            # error | warning


def errors(vs: list[Violation]) -> list[Violation]:
    return [v for v in vs if v.severity == "error"]


# ----------------------------------------------------------------------------- engine
def engine_rules(chart: dict, players: int, limits: Limits) -> list[Violation]:
    out: list[Violation] = []
    roots = chart.get("root_nodes", [])
    stars = fillings.star_fillings()
    verified = fillings.verified_names()

    nodes: dict[int, dict] = {}
    parent_of: dict[int, list[int]] = defaultdict(list)
    id_count: Counter = Counter()

    def walk(n, root_id, depth):
        id_count[n["id"]] += 1
        nodes[n["id"]] = n
        if depth:
            parent_of[n["id"]].append(root_id)
        for c in n.get("child_nodes", []):
            walk(c, root_id, depth + 1)

    for r in roots:
        walk(r, r["id"], 0)
        if r["filling_name"] not in stars:
            out.append(Violation("PARENT_STAR", f"root node {r['id']} ({r['filling_name']}) is not a star",
                                 "every root node must be a star filling", [r["id"]]))
    root_ids = {r["id"] for r in roots}

    if len(roots) > limits.max_stars:
        out.append(Violation("STAR_COUNT_MAX", f"{len(roots)} stars > max_stars {limits.max_stars}",
                             "reduce stars or raise [limits].max_stars in config.toml"))
    for r in roots:
        n_bodies = sum(1 for _ in _descendants(r))
        if n_bodies > limits.max_bodies_per_star:
            out.append(Violation("BODIES_PER_STAR_MAX",
                                 f"star {r['id']} has {n_bodies} bodies > hard limit {limits.max_bodies_per_star}",
                                 "remove planets or add a star", [r["id"]]))
        elif n_bodies > limits.warn_bodies_per_star:
            out.append(Violation("BODIES_PER_STAR_WARN",
                                 f"star {r['id']} has {n_bodies} bodies > proven-safe {limits.warn_bodies_per_star} "
                                 f"(largest vanilla single-star map)",
                                 "load-test in game before relying on this map", [r["id"]], "warning"))

    for nid, cnt in id_count.items():
        if cnt > 1:
            out.append(Violation("ID_DUPLICATE", f"node id {nid} used {cnt} times", "ids must be unique", [nid]))
    for nid in nodes:
        if nid not in root_ids and len(parent_of[nid]) != 1:
            out.append(Violation("PARENT_STAR", f"node {nid} has {len(parent_of[nid])} parent stars",
                                 "each body sits under exactly one star", [nid]))
    for nid, n in nodes.items():
        if n["filling_name"] not in verified:
            out.append(Violation("FILLING_UNVERIFIED", f"node {nid}: filling_name {n['filling_name']!r} "
                                 "is not in data/fillings.json verified_filling_names",
                                 "use a vanilla node filling", [nid]))

    lane_ids = Counter(l["id"] for l in chart.get("phase_lanes", []))
    for lid, cnt in lane_ids.items():
        if cnt > 1 or lid in nodes:
            out.append(Violation("ID_DUPLICATE", f"lane id {lid} is not unique", "ids must be unique across nodes and lanes"))
    seen_pairs: Counter = Counter()
    degree: Counter = Counter()
    for l in chart.get("phase_lanes", []):
        a, b, t = l["node_a"], l["node_b"], l.get("type", "normal")
        if a not in nodes or b not in nodes:
            out.append(Violation("LANE_UNKNOWN_NODE", f"lane {l['id']} references a missing node",
                                 "lanes must join existing nodes", [a, b]))
            continue
        if a == b:
            out.append(Violation("SELF_LOOP", f"lane {l['id']} joins node {a} to itself", "remove the lane", [a]))
        seen_pairs[frozenset((a, b))] += 1
        degree[a] += 1
        degree[b] += 1
        if t == "star" and not (a in root_ids and b in root_ids):
            out.append(Violation("STAR_LANE_ENDPOINT", f"star lane {l['id']} joins {a}-{b}, not star-star",
                                 "star lanes only join two root stars (vanilla 32/32)", [a, b]))
        wh = fillings.role("wormhole").filling_name
        if t == "wormhole" and not (nodes[a]["filling_name"] == wh and nodes[b]["filling_name"] == wh):
            out.append(Violation("WORMHOLE_LANE_ENDPOINT", f"wormhole lane {l['id']} joins {a}-{b}",
                                 "wormhole lanes only join two wormhole_fixture nodes (vanilla 62/62)", [a, b]))
    for pair, cnt in seen_pairs.items():
        if cnt > 1:
            out.append(Violation("DUPLICATE_LANE", f"{cnt} lanes join {sorted(pair)}", "keep one lane", sorted(pair)))
    for nid in nodes:
        if nid not in root_ids and degree[nid] == 0:
            out.append(Violation("LANE_MISSING", f"body {nid} ({nodes[nid]['filling_name']}) has no lanes",
                                 "every body needs at least one lane (unlinked bodies cause stray lanes)", [nid]))

    homes = [n for n in nodes.values() if "player_index" in (n.get("ownership") or {})]
    per_player = Counter(n["ownership"]["player_index"] for n in homes)
    for n in homes:
        pi = n["ownership"]["player_index"]
        if not 0 <= pi < players:
            out.append(Violation("PLAYER_INDEX_RANGE", f"node {n['id']} player_index {pi} not in 0..{players - 1}",
                                 "player_index is 0-based", [n["id"]]))
        if n["filling_name"] != fillings.role("player_home").filling_name:
            out.append(Violation("HOME_FILLING", f"node {n['id']} is player-owned but not player_home_planet",
                                 "player-owned nodes use player_home_planet", [n["id"]]))
    for p in range(players):
        if per_player[p] != 1:
            out.append(Violation("HOME_PER_PLAYER", f"player {p} has {per_player[p]} player_home_planet nodes",
                                 "exactly one home per player"))
    return out


def _descendants(n):
    for c in n.get("child_nodes", []):
        yield c
        yield from _descendants(c)


# ----------------------------------------------------------------------------- design
def _adjacency(m: CompiledMap, removed: set[int] = frozenset(), only: set[int] | None = None):
    adj = defaultdict(set)
    for l in m.lanes:
        if l.a in removed or l.b in removed:
            continue
        if only is not None and (l.a not in only or l.b not in only):
            continue
        adj[l.a].add(l.b)
        adj[l.b].add(l.a)
    return adj


def _reach(adj, starts) -> set[int]:
    seen = set(starts)
    q = deque(starts)
    while q:
        x = q.popleft()
        for y in adj[x]:
            if y not in seen:
                seen.add(y)
                q.append(y)
    return seen


def _hops(adj, start: int) -> dict[int, int]:
    d = {start: 0}
    q = deque([start])
    while q:
        x = q.popleft()
        for y in adj[x]:
            if y not in d:
                d[y] = d[x] + 1
                q.append(y)
    return d


def _blind(code: str, subject: str) -> Violation:
    """A rule that cannot see its subject must say so rather than return clean.

    Added 2026-09-24: REGION_ADVANTAGE_STACK returned no violation on three_rings because every
    home scored (no core spoke, no major fields) - the map expresses core access through inner-ring
    spokes, which the rule does not read. An empty input set is not a passing grade.
    """
    return Violation("BALANCE_RULE_BLIND", f"{code} evaluated nothing: {subject}",
                     "the map has the feature this rule polices but the rule could not see it - "
                     "widen the rule's inputs; do not read the clean result as a pass",
                     severity="warning")


def region_advantages(m: CompiledMap) -> dict[str, tuple[bool, list[str]]]:
    """Per home region: does it have a core spoke, and which major fields does it touch?"""
    access = {s.from_zone for s in m.spokes}
    out: dict[str, tuple[bool, list[str]]] = {}
    for z in m.spec.zones:
        if z.kind != "home":
            continue
        majors = sorted(b.id for b in m.spec.zones
                        if b.kind == "border" and b.planet_count > 1 and z.id in (b.placement.zones or []))
        out[z.id] = (z.id in access, majors)
    return out


def balance_rules(m: CompiledMap) -> list[Violation]:
    """Core access and major fields should not stack on the same regions (BRIEF S5)."""
    adv = region_advantages(m)
    if not adv:
        return []
    both = sorted(r for r, (core, majors) in adv.items() if core and majors)
    neither = sorted(r for r, (core, majors) in adv.items() if not core and not majors)
    if both and neither:
        return [Violation("REGION_ADVANTAGE_STACK",
                          f"{', '.join(both)} have core access and a major field, while "
                          f"{', '.join(neither)} have neither",
                          "move the major fields to borders between regions without core access",
                          severity="warning")]
    # no signal at all. On a map that has none of these features that is correct; on a map that does
    # have them it means the rule could not read them, which must not look like a pass.
    if not any(core or majors for core, majors in adv.values()):
        subject = []
        if any(z.gated for z in m.spec.zones):
            subject.append("gated zones exist but no home region owns a core spoke")
        if any(z.kind == "border" and z.planet_count > 1 for z in m.spec.zones):
            subject.append("multi-planet border zones exist but no home region touches one")
        if subject:
            return [_blind("REGION_ADVANTAGE_STACK", "; ".join(subject))]
    return []


def region_distances(m: CompiledMap) -> dict[str, dict[str, int | None]]:
    """Per home region: lane-hops to the nearest gated-zone entrance and to the nearest
    multi-planet contested zone.

    Advantage is not only what a region touches, it is how far it has to walk to reach it.
    """
    adj = _adjacency(m)
    targets = {
        "gate": sorted({s.chokepoint for s in m.spokes}),
        "contested": sorted(i for z in m.spec.zones
                            if z.kind == "contested" and z.planet_count > 1
                            for i in m.zone_nodes[z.id]),
    }
    out: dict[str, dict[str, int | None]] = {}
    for z in m.spec.zones:
        if z.kind != "home":
            continue
        start = next((i for i in m.zone_nodes[z.id] if m.nodes[i].role == "home"), None)
        if start is None:
            continue
        d = _hops(adj, start)
        out[z.id] = {k: min((d[i] for i in ids if i in d), default=None) for k, ids in targets.items()}
    return out


def proximity_rules(m: CompiledMap, max_spread: int = 2) -> list[Violation]:
    """Distance to an advantage is an advantage (BRIEF S5).

    Added 2026-09-24 after three_rings: three homes sat 4 hops from a core gate and one sat 6, and
    no rule measured it. region_advantages only asks what a region touches, never how far it is.
    """
    out: list[Violation] = []
    dist = region_distances(m)
    if len(dist) < 2:
        return out
    for key, label, present in (
            ("gate", "a gated-zone entrance", any(z.gated for z in m.spec.zones)),
            ("contested", "a multi-planet contested zone",
             any(z.kind == "contested" and z.planet_count > 1 for z in m.spec.zones))):
        vals = {r: d[key] for r, d in dist.items() if d[key] is not None}
        if len(vals) < 2:
            if present:
                out.append(_blind("REGION_HOP_SPREAD",
                                  f"the map has {label} but {len(vals)} of {len(dist)} home regions "
                                  f"can reach one"))
            continue
        lo, hi = min(vals.values()), max(vals.values())
        if hi - lo > max_spread:
            near = ", ".join(sorted(r for r, v in vals.items() if v == lo))
            far = ", ".join(sorted(r for r, v in vals.items() if v == hi))
            out.append(Violation(
                "REGION_HOP_SPREAD",
                f"hops to {label} range {lo}-{hi} (spread {hi - lo} > {max_spread}): "
                f"{near} at {lo}, {far} at {hi}",
                "even out the distances, or accept it deliberately and raise "
                "[limits].max_region_hop_spread in config.toml",
                severity="warning"))
    return out


def design_rules(m: CompiledMap) -> list[Violation]:
    out: list[Violation] = []
    spec = m.spec
    bodies = [n.id for n in m.bodies()]
    adj = _adjacency(m)
    reached = _reach(adj, [bodies[0]]) if bodies else set()
    missing = sorted(set(bodies) - reached)
    if missing:
        out.append(Violation("GRAPH_DISCONNECTED", f"{len(missing)} bodies unreachable from the rest",
                             "link every zone into the graph", missing[:20]))

    # counts vs spec
    homes = [n for n in m.nodes if n.role == "home"]
    if len(homes) != spec.meta.players:
        out.append(Violation("COUNT_PLAYERS", f"{len(homes)} homes for {spec.meta.players} players",
                             "one home zone per player"))
    n_planets = len(m.planets())
    want = sum(z.planet_count for z in spec.zones)
    if n_planets != spec.constraints.total_planets or n_planets != want:
        out.append(Violation("COUNT_PLANETS", f"compiled {n_planets} planets; zones sum {want}; "
                             f"spec total_planets {spec.constraints.total_planets}",
                             "zone planet_counts must add up to total_planets"))
    for z in spec.zones:
        if len(m.zone_nodes[z.id]) != z.planet_count:
            out.append(Violation("COUNT_ZONE", f"zone {z.id}: {len(m.zone_nodes[z.id])} planets, spec {z.planet_count}",
                                 "compiler/spec mismatch"))
    pirates_spec = sum(z.planet_count for z in spec.zones if z.kind == "pirate")
    pirates = sum(1 for n in m.nodes if n.role == "pirate")
    if pirates != pirates_spec:
        out.append(Violation("COUNT_PIRATES", f"{pirates} pirate planets, spec {pirates_spec}", "compiler/spec mismatch"))
    # convoys per region must match what the spec declares (a contested zone entered by a wormhole link
    # and left by a lane to a home). A contested zone wired some other way is a valid design, not a fault.
    declared: Counter = Counter()
    for z in spec.zones:
        if z.kind != "contested":
            continue
        entries = [l.from_zone for l in spec.links if l.to_zone == z.id and l.lane == "wormhole"]
        exits = [l.to_zone for l in spec.links if l.from_zone == z.id]
        if entries and exits:
            for end in entries + exits:
                if spec.zone(end).kind == "home":
                    declared[end] += 1
    compiled: Counter = Counter()
    for a, _, b in m.convoys:
        compiled[a] += 1
        compiled[b] += 1
    for zid in sorted(set(declared) | set(compiled)):
        if declared[zid] != compiled[zid]:
            out.append(Violation("COUNT_CONVOYS",
                                 f"region {zid}: spec declares {declared[zid]} convoys, compiled {compiled[zid]}",
                                 "compiler/spec mismatch in convoy wiring"))

    # chokepoint proof
    home_ids = [n.id for n in homes]
    for z in spec.zones:
        if not z.gated:
            continue
        zone_ids = set(m.zone_nodes[z.id])
        chokes = {i for i in zone_ids if m.nodes[i].role == "chokepoint"}
        inner = zone_ids - chokes
        if len(chokes) != z.chokepoints:
            out.append(Violation("CHOKEPOINT_COUNT", f"zone {z.id}: {len(chokes)} chokepoints, spec {z.chokepoints}",
                                 "one chokepoint per gated access link"))
        cut = _reach(_adjacency(m, removed=chokes), home_ids)
        leaked = sorted(inner & cut)
        if leaked:
            out.append(Violation("CHOKEPOINT_BYPASS",
                                 f"zone {z.id}: {len(leaked)} gated planets reachable from homes without a chokepoint",
                                 "remove lanes into the gated zone that do not go through a chokepoint", leaked))
        for c in sorted(chokes):
            outside = [y for y in adj[c] if y not in zone_ids]
            if len(outside) != 1:
                out.append(Violation("CHOKEPOINT_ENTRY", f"chokepoint {c} has {len(outside)} lanes from outside {z.id}",
                                     "a chokepoint has a single lane in", [c]))
        for s in (s for s in m.spokes if s.zone == z.id):
            sub = zone_ids | set(s.path)
            reach = _reach(_adjacency(m, removed={s.chokepoint}, only=sub), [s.path[0]])
            if reach & inner:
                out.append(Violation("CHOKEPOINT_NOT_CUT",
                                     f"spoke {s.from_zone}->{z.id}: chokepoint {s.chokepoint} is not a cut vertex",
                                     "the spoke must reach the core only through its chokepoint", [s.chokepoint]))
            if not (_reach(_adjacency(m, only=sub), [s.path[0]]) & inner):
                out.append(Violation("CHOKEPOINT_NOT_CUT", f"spoke {s.from_zone}->{z.id} does not reach the core",
                                     "wire the spoke into its chokepoint", [s.chokepoint]))

    # resource rules
    for n in m.planets():
        if not fillings.is_gas_giant(n.filling_name):
            continue
        z = spec.zone(n.zone) if n.zone else None
        if z and z.kind == "home":
            out.append(Violation("GAS_GIANT_PLACEMENT", f"gas giant {n.id} in home zone {z.id}",
                                 "gas giant is XL balanced, core only", [n.id]))
        if n.bias == "metal":
            out.append(Violation("GAS_GIANT_PLACEMENT", f"gas giant {n.id} in a metal-bias slot",
                                 "gas giant is XL balanced, core only", [n.id]))
    for z in spec.zones:
        if z.kind != "home":
            continue
        ids = [i for i in m.zone_nodes[z.id] if m.nodes[i].role != "home"]
        gated = [i for i in ids if m.nodes[i].research_gated]
        if len(gated) > 1:
            out.append(Violation("HOME_RESEARCH_GATED", f"home {z.id} has {len(gated)} (R) planets",
                                 "at most one research-gated planet per home cluster", gated))
        for i in ids:
            n = m.nodes[i]
            if n.tier not in ("S", "M", "L") or n.bias not in ("metal", "balanced"):
                out.append(Violation("HOME_TIER_BIAS", f"home {z.id} planet {i} is {n.tier}/{n.bias}",
                                     "home planets come from metal-bias and balanced S/M/L tiers", [i]))
    return out


def spacing_rules(m: CompiledMap, floor: float = 160.0) -> list[Violation]:
    """No two bodies may sit closer than the vanilla nearest-neighbour floor.

    Added 2026-09-23 after the clusters layout put two planets at distance 0: several 'between' zones
    sharing the same two anchors resolved to the same midpoint. Nothing caught it, and coincident
    gravity wells are a defect in game. Vanilla's own closest pair across big maps is 54-194.
    """
    out: list[Violation] = []
    b = [n for n in m.nodes if n.role != "star"]
    for i, x in enumerate(b):
        for y in b[i + 1:]:
            d = math.dist(x.pos, y.pos)
            if d < floor:
                out.append(Violation("MIN_SPACING",
                                     f"bodies {x.id} and {y.id} are {d:.0f} apart, under the {floor:.0f} floor",
                                     "two bodies must not overlap; move a zone or lower the planet count",
                                     [x.id, y.id]))
    return out


def zone_gateways(m: CompiledMap) -> dict[str, int]:
    """Per zone: how many distinct planets of it receive a lane from outside the zone."""
    zone_of = {i: z for z, ids in m.zone_nodes.items() for i in ids}
    out: dict[str, set[int]] = {z.id: set() for z in m.spec.zones}
    for lane in m.lanes:
        za, zb = zone_of.get(lane.a), zone_of.get(lane.b)
        if za != zb:                                   # a fixture has no zone, so it counts as outside
            if za is not None:
                out[za].add(lane.a)
            if zb is not None:
                out[zb].add(lane.b)
    return {k: len(v) for k, v in out.items()}


def gateway_rules(m: CompiledMap, max_spread: int = 1) -> list[Violation]:
    """Comparable zones should be about equally hard to hold (BRIEF S5).

    Added 2026-09-25. A zone whose external lanes all land on one planet is held with one starbase;
    a zone with three entrances needs three. On three_rings, home_0/4/7 funnelled all five of their
    external lanes onto a single planet while home_1/3 spread across three, and nothing measured it
    - every rule we had looked at resources or distance, never at how many places a defender has to
    cover. Zones are comparable when they share a kind and a planet count.
    """
    out: list[Violation] = []
    gw = zone_gateways(m)
    groups: dict[tuple[str, int], list[str]] = defaultdict(list)
    for z in m.spec.zones:
        if z.kind in ("filler", "pirate") or z.planet_count < 2:
            continue                                   # scattered zones have nothing to compare
        groups[(z.kind, z.planet_count)].append(z.id)
    for (kind, count), ids in sorted(groups.items()):
        if len(ids) < 2:
            continue
        vals = {i: gw.get(i, 0) for i in ids}
        lo, hi = min(vals.values()), max(vals.values())
        if hi - lo > max_spread:
            few = ", ".join(sorted(i for i, v in vals.items() if v == lo))
            many = ", ".join(sorted(i for i, v in vals.items() if v == hi))
            out.append(Violation(
                "GATEWAY_SPREAD",
                f"{kind} zones of {count} planets have {lo}-{hi} distinct entrances "
                f"(spread {hi - lo} > {max_spread}): {few} at {lo}, {many} at {hi}",
                "a zone whose lanes all land on one planet is held with one starbase; spread the "
                "external lanes across distinct planets so every comparable zone costs the same "
                "to defend",
                severity="warning"))
    return out


def check(m: CompiledMap, chart: dict, limits: Limits) -> list[Violation]:
    return (engine_rules(chart, m.spec.meta.players, limits) + design_rules(m)
            + balance_rules(m) + spacing_rules(m)
            + proximity_rules(m, limits.max_region_hop_spread) + gateway_rules(m))
