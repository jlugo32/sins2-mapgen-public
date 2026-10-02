"""MapSpec → CompiledMap (nodes, lanes, positions). The only place filling_names are chosen.

Conventions (BRIEF §1 Compiler, FINDINGS §7):
- one star at (0, 0) is the root node; every body is its child; the star has no lanes;
- one shared id counter: nodes first, then lanes;
- every body is orbit-locked (orbit_speed_scalar 0.0, ignore_orbit_overlap_checks true);
- all randomness comes from random.Random(seed).
"""
from __future__ import annotations

import math
from collections import Counter
import random
from dataclasses import dataclass, field

from . import fillings
from .params import Geometry
from .spec import Link, MapSpec, Zone


class CompileError(Exception):
    pass


@dataclass
class Node:
    id: int
    filling_name: str
    pos: tuple[float, float]
    zone: str | None                 # None for the star and wormhole fixtures
    role: str                        # star | home | planet | chokepoint | pirate | wormhole
    tier: str | None = None
    bias: str | None = None
    research_gated: bool = False
    metal: tuple[int, int] = (0, 0)
    crystal: tuple[int, int] = (0, 0)
    expected_metal: float | None = None
    expected_crystal: float | None = None
    ownership: dict | None = None
    extra: dict = field(default_factory=dict)

    @property
    def metal_mean(self) -> float:
        """Use the weighted mean where the filling is a roll; the midpoint otherwise."""
        return self.expected_metal if self.expected_metal is not None else sum(self.metal) / 2

    @property
    def crystal_mean(self) -> float:
        return self.expected_crystal if self.expected_crystal is not None else sum(self.crystal) / 2


@dataclass
class Lane:
    id: int
    a: int
    b: int
    type: str = "normal"             # normal | star | wormhole ("normal" is written as an absent key)


@dataclass
class Spoke:
    """One gated-zone access path: entry planet → fixture → wormhole → fixture → chokepoint."""
    zone: str
    from_zone: str
    chokepoint: int
    path: list[int]


@dataclass
class CompiledMap:
    spec: MapSpec
    nodes: list[Node]
    lanes: list[Lane]
    star_id: int
    zone_nodes: dict[str, list[int]]
    spokes: list[Spoke]
    convoys: list[tuple[str, str, str]]          # (from_zone, contested_zone, to_zone)

    def node(self, nid: int) -> Node:
        return self.nodes[nid]

    def bodies(self) -> list[Node]:
        return [n for n in self.nodes if n.id != self.star_id]

    def planets(self) -> list[Node]:
        return [n for n in self.nodes if n.role in ("home", "planet", "chokepoint", "pirate")]

    def fixtures(self) -> list[Node]:
        return [n for n in self.nodes if n.role == "wormhole"]


LOCK = {"orbit_speed_scalar": 0.0, "ignore_orbit_overlap_checks": True}


class _Builder:
    def __init__(self, spec: MapSpec, geo: Geometry):
        self.spec = spec
        s = spec.layout.radius_scale
        self.g = Geometry(**{k: v * s for k, v in vars(geo).items()})
        self.min_spacing = geo.min_spacing  # spacing does not scale with radius
        self.rng = random.Random(spec.meta.seed)
        self.nodes: list[Node] = []
        self.lanes: list[tuple[int, int, str]] = []
        self.laned: set[frozenset] = set()            # node pairs that already have a lane
        self.ext_deg: Counter = Counter()             # external lanes landed on each planet
        self.zone_nodes: dict[str, list[int]] = {z.id: [] for z in spec.zones}
        self.spokes: list[Spoke] = []
        self.convoys: list[tuple[str, str, str]] = []
        self.P = spec.meta.players
        self.ring_slots = {z.id: z.placement.slot for z in spec.zones if z.placement.kind == "ring_slot"}
        self.shape = spec.layout.shape
        # clusters layout: theaters in spec order, each on a circle; powers ring their theater centre
        self.cluster_of = {z.id: z.placement.cluster for z in spec.zones if z.placement.kind == "cluster"}
        names: list[str] = []
        for z in spec.zones:
            if z.placement.kind == "cluster" and z.placement.cluster not in names:
                names.append(z.placement.cluster)
        self.cluster_names = names
        self.cluster_size = {n: sum(1 for c in self.cluster_of.values() if c == n) for n in names}
        # concentric layout: how many zones share each band, so a band divides the circle evenly
        self.band_count: dict[int, int] = {}
        for z in spec.zones:
            if z.placement.kind == "band":
                self.band_count[z.placement.band] = self.band_count.get(z.placement.band, 0) + 1

    # ------------------------------------------------------------------ helpers
    def angle(self, slot: int) -> float:
        return -math.pi / 2 + 2 * math.pi * slot / self.P

    def polar(self, r: float, a: float) -> tuple[float, float]:
        return (r * math.cos(a), r * math.sin(a))

    def add_node(self, **kw) -> int:
        nid = len(self.nodes)
        self.nodes.append(Node(id=nid, **kw))
        if kw.get("zone"):
            self.zone_nodes[kw["zone"]].append(nid)
        return nid

    def add_lane(self, a: int, b: int, kind: str = "normal") -> None:
        self.lanes.append((a, b, kind))
        self.laned.add(frozenset((a, b)))

    def free_pair(self, xs: list[int], ys: list[int]) -> tuple[int, int] | None:
        """Nearest (x, y) that does not already have a lane. None when every pair is joined."""
        best = None
        for x in xs:
            for y in ys:
                if x == y or frozenset((x, y)) in self.laned:
                    continue
                d = math.dist(self.nodes[x].pos, self.nodes[y].pos)
                if best is None or (d, x, y) < best:
                    best = (d, x, y)
        return (best[1], best[2]) if best else None

    def spread_pick(self, zid: str, toward: tuple[float, float], partner: int | None = None) -> int:
        """The zone's least-loaded entrance planet, nearest to `toward` among ties.

        concentric only. A zone's external lanes should land on as many different planets as the
        zone has entrances to give, so that holding it means holding several places rather than one
        chokepoint. free_pair takes the nearest still-free pair, which piles later lanes onto
        planets that already carry one: three of the ten home zones on three_rings ended up with
        all five of their external lanes on a single planet, and nothing measured it.
        """
        ids = self.eligible(zid)
        fewest = min(self.ext_deg[i] for i in ids)
        pool = [i for i in ids if self.ext_deg[i] == fewest]
        if partner is not None:
            free = [i for i in pool if frozenset((i, partner)) not in self.laned]
            pool = free or pool
        return self.nearest(pool, toward)

    def add_external_lane(self, a: int, b: int) -> bool:
        if frozenset((a, b)) in self.laned:
            return False
        self.add_lane(a, b)
        self.ext_deg[a] += 1
        self.ext_deg[b] += 1
        return True

    def zone_center(self, zid: str) -> tuple[float, float]:
        ids = self.zone_nodes[zid]
        return (sum(self.nodes[i].pos[0] for i in ids) / len(ids), sum(self.nodes[i].pos[1] for i in ids) / len(ids))

    def eligible(self, zid: str) -> list[int]:
        """Planets a link may attach to: not the player home (if the zone has others)."""
        ids = self.zone_nodes[zid]
        z = self.spec.zone(zid)
        if z.gated:
            return [i for i in ids if self.nodes[i].role != "chokepoint"]  # normal links into a gated zone bypass it
        non_home = [i for i in ids if self.nodes[i].role != "home"]
        return non_home or ids

    def nearest(self, ids: list[int], point: tuple[float, float]) -> int:
        return min(ids, key=lambda i: (math.dist(self.nodes[i].pos, point), i))

    def planet_node(self, z: Zone, tier: str, slot: int, pos, role="planet") -> int:
        if role == "chokepoint" and z.chokepoint_role == "garrison":
            g = fillings.role("garrison")
            return self.add_node(filling_name=g.filling_name, pos=pos, zone=z.id, role=role,
                                 tier=tier, bias=None, metal=g.metal, crystal=g.crystal,
                                 expected_metal=g.expected_metal, expected_crystal=g.expected_crystal,
                                 extra=dict(LOCK))
        slot_bias = z.slot_biases[slot] if z.slot_biases else None
        r = fillings.zone_planet(z.kind, z.resource_bias, tier, slot, slot_bias)
        return self.add_node(filling_name=r.filling_name, pos=pos, zone=z.id, role=role, tier=tier, bias=r.bias,
                             research_gated=r.research_gated, metal=r.metal, crystal=r.crystal,
                             expected_metal=r.expected_metal, expected_crystal=r.expected_crystal,
                             extra=dict(LOCK))

    # ------------------------------------------------------------------ placement
    def cluster_centre(self, name: str) -> tuple[float, float]:
        i = self.cluster_names.index(name)
        return self.polar(self.g.theater_radius, -math.pi / 2 + 2 * math.pi * i / len(self.cluster_names))

    def place_cluster_home(self, z: Zone) -> None:
        """clusters layout: a power sits at its slot around its theater's centre."""
        centre = self.cluster_centre(z.placement.cluster)
        n = self.cluster_size[z.placement.cluster]
        if n > 1:
            out = math.atan2(centre[1], centre[0])          # face the theater away from the map centre
            a = out + math.pi / 2 + 2 * math.pi * z.placement.slot / n
            spread = self.g.theater_spread * (0.55 + 0.15 * n)   # a crowded theater needs more room
            centre = (centre[0] + spread * math.cos(a), centre[1] + spread * math.sin(a))
        self.place_home_at(z, centre)

    def band_point(self, band: int, slot: int) -> tuple[float, float]:
        radii = self.spec.layout.band_radii or [1.0]
        offsets = self.spec.layout.band_offsets or [0.0] * len(radii)
        n = max(1, self.band_count.get(band, 1))
        a = -math.pi / 2 + 2 * math.pi * (slot + offsets[band]) / n
        return self.polar(self.g.ring_radius * radii[band], a)

    def place_band(self, z: Zone) -> None:
        """concentric layout: one vertex of a band, with the zone's planets around that vertex."""
        centre = self.band_point(z.placement.band, z.placement.slot)
        if z.kind == "home":
            return self.place_home_at(z, centre)
        n = len(z.size_tiers)
        if n == 1:
            return self.planet_node(z, z.size_tiers[0], 0, centre) and None
        spin = math.atan2(centre[1], centre[0])          # spread along the band, not across it
        for k, tier in enumerate(z.size_tiers):
            off = self.g.border_major_split * (2 * k / (n - 1) - 1)
            self.planet_node(z, tier, k, (centre[0] - math.sin(spin) * off,
                                          centre[1] + math.cos(spin) * off))

    def place_home(self, z: Zone) -> None:
        a = self.angle(z.placement.slot)
        c = self.polar(self.g.ring_radius, a)
        self.place_home_at(z, c)

    def place_home_at(self, z: Zone, c: tuple[float, float]) -> None:
        home = fillings.role("player_home")
        self.add_node(filling_name=home.filling_name, pos=c, zone=z.id, role="home",
                      ownership={"player_index": z.owner_player},
                      metal=home.metal, crystal=home.crystal,
                      expected_metal=home.expected_metal, expected_crystal=home.expected_crystal,
                      extra={"chance_of_loot": 0.0, "chance_of_first_planet_bonus": 0.0,
                             "chance_of_second_planet_bonus": 0.0, **LOCK})
        n = len(z.size_tiers)
        spin = self.rng.uniform(0, 2 * math.pi)
        for k, tier in enumerate(z.size_tiers):
            t = spin + 2 * math.pi * k / n + self.rng.uniform(-0.15, 0.15)
            r = self.g.cluster_radius * self.rng.uniform(0.9, 1.1)
            self.planet_node(z, tier, k, (c[0] + r * math.cos(t), c[1] + r * math.sin(t)))

    def place_between(self, z: Zone) -> None:
        za, zb = z.placement.zones
        if self.shape != "ring":
            return self.place_between_clusters(z, za, zb)
        sa, sb = self.ring_slots.get(za), self.ring_slots.get(zb)
        if sa is None or sb is None:
            raise CompileError(f"zone {z.id}: 'between' needs two ring_slot zones")
        if z.kind == "contested":
            # convoy target side: just outside zone B, offset so it clears B's own fixtures
            a = self.angle(sb) - 0.12
            r = self.g.ring_radius + self.g.cluster_radius + self.g.convoy_contested_offset
            for k, tier in enumerate(z.size_tiers):
                self.planet_node(z, tier, k, self.polar(r + k * self.min_spacing * 1.2, a))
            return
        aa, ab = self.angle(sa), self.angle(sb)
        mid = math.atan2(math.sin(aa) + math.sin(ab), math.cos(aa) + math.cos(ab))
        n = len(z.size_tiers)
        for k, tier in enumerate(z.size_tiers):
            off = 0.0 if n == 1 else self.g.border_major_split * (2 * k / (n - 1) - 1)
            self.planet_node(z, tier, k, self.polar(self.g.ring_radius + off, mid))

    def place_between_clusters(self, z: Zone, za: str, zb: str) -> None:
        """clusters layout: position from the real zone centres, so 'between' works across theaters.

        A gated zone is pushed off the direct line and its chokepoints face the zones that access it, so
        several gated zones can coexist - the ring layout only ever had one, at the centre.
        """
        ca, cb = self.zone_center(za), self.zone_center(zb)
        d = math.dist(ca, cb) or 1.0
        perp = (-(cb[1] - ca[1]) / d, (cb[0] - ca[0]) / d)      # unit normal to the a-b line
        # several zones can share the same two anchors (a border and a sea crossing between the same
        # powers); fan them along the line so they never land on the same midpoint
        peers = [o.id for o in self.spec.zones
                 if o.placement.kind == "between" and set(o.placement.zones or []) == {za, zb}]
        step = (peers.index(z.id) - (len(peers) - 1) / 2) if len(peers) > 1 else 0.0
        t = 0.5 + step * 0.22
        mid = (ca[0] + (cb[0] - ca[0]) * t, ca[1] + (cb[1] - ca[1]) * t)
        if not z.gated:
            n = len(z.size_tiers)
            for k, tier in enumerate(z.size_tiers):
                off = 0.0 if n == 1 else self.g.border_major_split * (2 * k / (n - 1) - 1)
                self.planet_node(z, tier, k, (mid[0] + perp[0] * off, mid[1] + perp[1] * off))
            return
        access = [l for l in self.spec.links if l.to_zone == z.id and l.chokepoint]
        if len(access) != z.chokepoints:
            raise CompileError(f"zone {z.id}: chokepoints={z.chokepoints} but {len(access)} chokepoint links")
        side = 1 if (mid[0] * perp[0] + mid[1] * perp[1]) >= 0 else -1    # push away from the map centre
        centre = (mid[0] + perp[0] * self.g.gated_offset * side,
                  mid[1] + perp[1] * self.g.gated_offset * side)
        inner = z.size_tiers[:len(z.size_tiers) - z.chokepoints]
        choke = z.size_tiers[len(inner):]
        for k, tier in enumerate(inner):
            a = 2 * math.pi * k / max(1, len(inner))
            r = self.g.core_radius * (1.0 if len(inner) <= 6 else 1.4)
            self.planet_node(z, tier, k, (centre[0] + r * math.cos(a), centre[1] + r * math.sin(a)))
        for k, (tier, link) in enumerate(zip(choke, access)):
            src = self.zone_center(link.from_zone)
            dx, dy = src[0] - centre[0], src[1] - centre[1]
            dd = math.hypot(dx, dy) or 1.0
            self.planet_node(z, tier, len(inner) + k,
                             (centre[0] + dx / dd * self.g.chokepoint_radius,
                              centre[1] + dy / dd * self.g.chokepoint_radius), role="chokepoint")

    def place_core(self, z: Zone) -> None:
        access = [l for l in self.spec.links if l.to_zone == z.id and l.chokepoint]
        if len(access) != z.chokepoints:
            raise CompileError(f"zone {z.id}: chokepoints={z.chokepoints} but {len(access)} chokepoint links")
        inner = z.size_tiers[:len(z.size_tiers) - z.chokepoints]
        choke = z.size_tiers[len(inner):]
        # An ungated centre zone has no chokepoint links; then the spin is arbitrary.
        def toward(zid: str) -> float:
            if self.shape == "ring" and zid in self.ring_slots:
                return self.angle(self.ring_slots[zid])
            c = self.zone_center(zid)                     # any other shape: aim at the real position
            return math.atan2(c[1], c[0])

        spin = (toward(access[0].from_zone) if access else 0.0) + math.pi / max(1, len(inner))
        rings = max(1, math.ceil(len(inner) / 8))     # keep spacing when a centre holds many planets
        for k, tier in enumerate(inner):
            per = math.ceil(len(inner) / rings)
            ring, idx = divmod(k, per)
            r = self.g.core_radius * (1 + ring * 0.75)
            self.planet_node(z, tier, k, self.polar(r, spin + 2 * math.pi * idx / min(per, len(inner))))
        for k, (tier, link) in enumerate(zip(choke, access)):
            a = toward(link.from_zone)
            self.planet_node(z, tier, len(inner) + k, self.polar(self.g.chokepoint_radius, a), role="chokepoint")

    def sector_plan(self, n: int) -> list[int] | None:
        """Which angular sector each gap planet goes in, near-evenly and shuffled.

        concentric only. Scattering gap planets into any free spot let a seed drop 10 crystal of
        filler next to one home and none next to six others - a 75% opening advantage that varied
        per seed, so no single build revealed it. Every sector now gets the same count +/- 1;
        which planet lands in which sector, and where inside it, stays random.
        """
        if self.shape != "concentric":
            return None                                   # ring and clusters output must not move
        slots = self.band_count.get(0) or self.spec.meta.players
        if slots < 2:
            return None
        plan = [i for i in range(slots) for _ in range(n // slots)]
        plan += self.rng.sample(range(slots), n % slots)   # the remainder, never always sector 0
        self.rng.shuffle(plan)
        return plan

    def place_gap(self, zones: list[Zone]) -> None:
        todo = []
        for z in zones:
            if z.kind == "pirate":
                todo += [(z, None, k) for k in range(z.planet_count)]
            else:
                todo += [(z, t, k) for k, t in enumerate(z.size_tiers)]
        sectors = self.sector_plan(len(todo))
        for idx, (z, tier, k) in enumerate(todo):
            anchor = (self.cluster_centre(z.placement.cluster)
                      if z.placement.kind == "cluster" else None)
            if anchor:
                pos = self.free_spot_near(anchor)
            elif sectors is not None:
                pos = self.free_spot_in_sector(sectors[idx], self.band_count.get(0)
                                               or self.spec.meta.players)
            else:
                pos = self.free_spot()
            if z.kind == "pirate":
                pr = fillings.role("pirate")
                self.add_node(filling_name=pr.filling_name, pos=pos, zone=z.id, role="pirate",
                              ownership=dict(pr.ownership), metal=pr.metal, crystal=pr.crystal,
                              expected_metal=pr.expected_metal, expected_crystal=pr.expected_crystal,
                              extra={"chance_of_loot": 0.0, **LOCK})
            else:
                self.planet_node(z, tier, k, pos)

    def free_spot(self) -> tuple[float, float]:
        if self.shape != "ring":
            return self.free_spot_clusters()
        clearance = self.min_spacing * 1.5
        for _ in range(4000):
            r = math.sqrt(self.rng.uniform(self.g.filler_inner ** 2, self.g.filler_outer ** 2))
            p = self.polar(r, self.rng.uniform(0, 2 * math.pi))
            if all(math.dist(p, n.pos) >= clearance for n in self.nodes if n.role != "star"):
                return p
        raise CompileError("[LAYOUT_SPACE] no free spot in the filler annulus; raise filler_outer or lower planets")

    def free_spot_near(self, centre: tuple[float, float]) -> tuple[float, float]:
        """A gap planet in the occupied space around one theater."""
        placed = [n for n in self.nodes if n.role != "star"]
        clearance = self.min_spacing * self.g.gap_clearance
        reach = self.g.theater_spread * 2.2
        for _ in range(8000):
            a = self.rng.uniform(0, 2 * math.pi)
            r = self.g.theater_spread * math.sqrt(self.rng.uniform(0.25, 1.0)) * 2.0
            p = (centre[0] + r * math.cos(a), centre[1] + r * math.sin(a))
            nearest = min(math.dist(p, n.pos) for n in placed)
            if clearance <= nearest <= reach:
                return p
        raise CompileError("[LAYOUT_SPACE] no free spot around that theater; lower its planet count")

    def free_spot_clusters(self) -> tuple[float, float]:
        """A gap planet sits in the space between blocs: clear of everything, but near something."""
        placed = [n for n in self.nodes if n.role != "star"]
        xs = [n.pos[0] for n in placed] or [0.0]
        ys = [n.pos[1] for n in placed] or [0.0]
        pad = self.g.theater_spread * 0.5
        clearance = self.min_spacing * self.g.gap_clearance
        for _ in range(8000):
            p = (self.rng.uniform(min(xs) - pad, max(xs) + pad),
                 self.rng.uniform(min(ys) - pad, max(ys) + pad))
            nearest = min(math.dist(p, n.pos) for n in placed)
            if nearest >= clearance and nearest <= self.g.gap_reach:
                return p
        raise CompileError("[LAYOUT_SPACE] no free spot between the clusters; raise gap_reach or "
                           "lower the planet count")

    def free_spot_in_sector(self, sector: int, slots: int) -> tuple[float, float]:
        """free_spot_clusters, restricted to one angular wedge of the map (concentric)."""
        half = math.pi / slots
        mid = -math.pi / 2 + 2 * math.pi * sector / slots
        placed = [n for n in self.nodes if n.role != "star"]
        span = max((math.dist((0.0, 0.0), n.pos) for n in placed), default=self.g.ring_radius)
        clearance = self.min_spacing * self.g.gap_clearance
        for _ in range(8000):
            a = mid + self.rng.uniform(-half, half)
            r = self.rng.uniform(self.g.ring_radius * 0.25, span + self.min_spacing)
            p = self.polar(r, a)
            nearest = min(math.dist(p, n.pos) for n in placed)
            if clearance <= nearest <= self.g.gap_reach:
                return p
        return self.free_spot_clusters()                  # sector full: fall back, never fail a build

    # ------------------------------------------------------------------ lanes
    def internal_lanes(self, z: Zone) -> None:
        ids = self.zone_nodes[z.id]
        if z.kind in ("filler", "pirate"):
            return  # gap planets attach to their nearest neighbour later
        if z.gated:
            inner = [i for i in ids if self.nodes[i].role != "chokepoint"]
            self.mesh(inner, z.internal_links)
            for c in (i for i in ids if self.nodes[i].role == "chokepoint"):
                self.add_lane(c, self.nearest(inner, self.nodes[c].pos))
            return
        self.mesh(ids, z.internal_links)

    def mesh(self, ids: list[int], style: str) -> None:
        if len(ids) < 2:
            return
        pairs = sorted(((math.dist(self.nodes[a].pos, self.nodes[b].pos), a, b)
                        for i, a in enumerate(ids) for b in ids[i + 1:]))
        parent = {i: i for i in ids}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        rest = []
        for d, a, b in pairs:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
                self.add_lane(a, b)
            else:
                rest.append((d, a, b))
        if style == "loop" and rest:
            for d, a, b in rest[:self.rng.randint(1, 2)]:
                self.add_lane(a, b)
        elif style == "dense":
            limit = 2 * self.g.cluster_radius
            for d, a, b in rest:
                if d <= limit:
                    self.add_lane(a, b)

    def wire(self, link: Link) -> None:
        src, dst = self.spec.zone(link.from_zone), self.spec.zone(link.to_zone)
        if link.lane == "normal" and link.chokepoint and dst.gated:
            chokes = [i for i in self.zone_nodes[dst.id] if self.nodes[i].role == "chokepoint"
                      and i not in {sp.chokepoint for sp in self.spokes}]
            if not chokes:
                raise CompileError(f"zone {dst.id}: more chokepoint links than chokepoint planets")
            target = self.nearest(chokes, self.zone_center(src.id))
            entry = self.nearest(self.eligible(src.id), self.nodes[target].pos)
            self.add_lane(entry, target)          # a land chokepoint: one lane in, no fixtures
            self.spokes.append(Spoke(zone=dst.id, from_zone=src.id, chokepoint=target,
                                     path=[entry, target]))
            return
        if link.lane == "normal":
            if dst.gated or src.gated:
                # deliberately wired to a non-chokepoint planet so rules.py reports the bypass
                g, o = (dst, src) if dst.gated else (src, dst)
                a = self.nearest(self.eligible(o.id), self.zone_center(g.id))
                b = self.nearest(self.eligible(g.id), self.nodes[a].pos)
                self.add_lane(a, b)
                return
            if self.shape == "concentric":
                if src.kind == "home" and dst.kind == "home":
                    # Ring lanes between neighbouring capitals keep the fixed slot 0. What a player
                    # can see from their capital at two hops IS their neighbour's slot-0 planet, so
                    # pinning it is what holds the opening flat across seeds. Slot 0 takes both
                    # neighbour lanes and nothing else: at five external lanes per zone that still
                    # leaves the other two planets to carry the rest.
                    a, b = self.eligible(src.id)[0], self.eligible(dst.id)[0]
                else:
                    # Everything else spreads. least-loaded-first puts the mid-ring lanes and the
                    # wormhole on the planets slot 0 is not already carrying, so a home zone ends
                    # with three distinct entrances instead of one.
                    a = self.spread_pick(src.id, self.zone_center(dst.id))
                    b = self.spread_pick(dst.id, self.nodes[a].pos, partner=a)
                self.add_external_lane(a, b)
                return
            pair = self.free_pair(self.eligible(src.id), self.eligible(dst.id))
            if pair is None:
                return        # these zones are already joined (gap zones attach to each other first)
            self.add_lane(*pair)
            return
        # wormhole
        wh = fillings.role("wormhole").filling_name
        if dst.gated and link.chokepoint and self.shape != "ring":
            # clusters: the spoke runs from the source zone to the chokepoint facing it
            chokes = [i for i in self.zone_nodes[dst.id] if self.nodes[i].role == "chokepoint"
                      and i not in {sp.chokepoint for sp in self.spokes}]
            if not chokes:
                raise CompileError(f"zone {dst.id}: more chokepoint links than chokepoint planets")
            ca = self.zone_center(src.id)
            target = self.nearest(chokes, ca)
            cb = self.nodes[target].pos
            d = math.dist(ca, cb) or 1.0
            u = ((cb[0] - ca[0]) / d, (cb[1] - ca[1]) / d)
            p_in = (ca[0] + u[0] * (self.g.cluster_radius + self.g.spoke_entry_offset),
                    ca[1] + u[1] * (self.g.cluster_radius + self.g.spoke_entry_offset))
            p_out = (cb[0] - u[0] * self.g.spoke_entry_offset, cb[1] - u[1] * self.g.spoke_entry_offset)
        elif dst.gated and link.chokepoint:
            slot = self.ring_slots[src.id]
            a = self.angle(slot)
            chokes = [i for i in self.zone_nodes[dst.id] if self.nodes[i].role == "chokepoint"]
            target = min(chokes, key=lambda c: abs(math.remainder(
                math.atan2(self.nodes[c].pos[1], self.nodes[c].pos[0]) - a, math.tau)))
            p_in = self.polar(self.g.ring_radius - self.g.cluster_radius - self.g.spoke_entry_offset, a)
            p_out = self.polar(self.g.spoke_exit_radius, a)
        elif dst.kind == "contested" and self.shape == "ring":
            a = self.angle(self.ring_slots[src.id]) + 0.12
            p_in = self.polar(self.g.ring_radius + self.g.cluster_radius + self.g.convoy_contested_offset, a)
            target = self.zone_nodes[dst.id][0]
            b = math.atan2(self.nodes[target].pos[1], self.nodes[target].pos[0])
            p_out = self.polar(self.g.ring_radius + self.g.cluster_radius + self.g.convoy_fixture_offset, b)
        else:
            ca, cb = self.zone_center(src.id), self.zone_center(dst.id)
            d = math.dist(ca, cb) or 1.0
            u = ((cb[0] - ca[0]) / d, (cb[1] - ca[1]) / d)
            off = self.g.cluster_radius + self.g.spoke_entry_offset
            p_in = (ca[0] + u[0] * off, ca[1] + u[1] * off)
            p_out = (cb[0] - u[0] * off, cb[1] - u[1] * off)
            target = (self.spread_pick(dst.id, p_out) if self.shape == "concentric"
                      else self.nearest(self.eligible(dst.id), p_out))
        entry = (self.spread_pick(src.id, p_in) if self.shape == "concentric"
                 else self.nearest(self.eligible(src.id), p_in))
        if self.shape == "concentric":
            self.ext_deg[entry] += 1                  # a wormhole mouth is an entrance too
            self.ext_deg[target] += 1
        f1 = self.add_node(filling_name=wh, pos=p_in, zone=None, role="wormhole", extra=dict(LOCK))
        f2 = self.add_node(filling_name=wh, pos=p_out, zone=None, role="wormhole", extra=dict(LOCK))
        self.add_lane(entry, f1)
        self.add_lane(f1, f2, "wormhole")
        self.add_lane(f2, target)
        if dst.gated and link.chokepoint:
            self.spokes.append(Spoke(zone=dst.id, from_zone=src.id, chokepoint=target, path=[entry, f1, f2, target]))

    def attach_gaps(self, zones: list[Zone]) -> None:
        """Prim-style: repeatedly attach the gap planet closest to the connected, non-gated part of the map."""
        gated = {i for z in self.spec.zones if z.gated for i in self.zone_nodes[z.id]}
        gap_ids = [i for z in zones for i in self.zone_nodes[z.id]]
        anchors = [n.id for n in self.nodes
                   if n.role in ("home", "planet") and n.id not in gated and n.id not in gap_ids]
        if self.shape == "concentric":
            # A drifter does not dock next to a capital: whether a stray filler planet happened to
            # land on someone's doorstep was worth up to 8.5 crystal of opening advantage.
            homes = {i for z in self.spec.zones if z.kind == "home" for i in self.zone_nodes[z.id]}
            anchors = [i for i in anchors if i not in homes] or anchors
        pending = list(gap_ids)
        while pending:
            pair = self.free_pair(pending, anchors)
            if pair is None:
                raise CompileError("[LAYOUT_SPACE] no free attachment left for gap-placed planets")
            g, a = pair
            self.add_lane(g, a)
            pending.remove(g)
            anchors.append(g)

    # ------------------------------------------------------------------ main
    def build(self) -> CompiledMap:
        star = fillings.role("star")
        star_id = self.add_node(filling_name=star.filling_name, pos=(0.0, 0.0), zone=None, role="star",
                                extra={"chance_of_loot": 0.0})
        order = {"ring_slot": 0, "cluster": 0, "band": 0, "between": 1, "center": 2, "gap": 3}

        def when(z: Zone) -> int:
            # a theater-anchored filler/pirate zone is placed last, like any other gap zone
            return 3 if (z.placement.kind == "cluster" and z.kind != "home") else order[z.placement.kind]

        zones = sorted(self.spec.zones, key=when)                     # stable: keeps spec order
        for z in zones:
            k = z.placement.kind
            if k == "ring_slot":
                if z.kind != "home":
                    raise CompileError(f"zone {z.id}: ring_slot placement is for home zones in the ring layout")
                self.place_home(z)
            elif k == "cluster" and z.kind == "home":
                self.place_cluster_home(z)
            elif k == "band":
                self.place_band(z)
            elif k == "between":
                self.place_between(z)
            elif k == "center":
                self.place_core(z)
        for z in self.spec.zones:
            self.internal_lanes(z)
        gaps = [z for z in zones if z.placement.kind == "gap"
                or (z.placement.kind == "cluster" and z.kind != "home")]
        gap_ids = {z.id for z in gaps}
        late = [l for l in self.spec.links if l.from_zone in gap_ids or l.to_zone in gap_ids]
        for link in self.spec.links:
            if link in late:
                continue  # gap planets do not exist yet
            self.wire(link)
            # a convoy is what rules.design_rules counts: a contested zone entered by a wormhole from a
            # home and left by a lane to a home. A contested zone wired any other way is not a convoy.
            if (link.lane == "wormhole" and self.spec.zone(link.to_zone).kind == "contested"
                    and self.spec.zone(link.from_zone).kind == "home"):
                back = [l for l in self.spec.links if l.from_zone == link.to_zone
                        and self.spec.zone(l.to_zone).kind == "home"]
                if back:
                    self.convoys.append((link.from_zone, link.to_zone, back[0].to_zone))
        self.place_gap(gaps)
        self.attach_gaps(gaps)
        for link in late:
            self.wire(link)

        if self.shape != "ring":              # ring output must stay byte-identical
            self.relax_spacing()
        lanes = [Lane(id=len(self.nodes) + k, a=a, b=b, type=t) for k, (a, b, t) in enumerate(self.lanes)]
        return CompiledMap(spec=self.spec, nodes=self.nodes, lanes=lanes, star_id=star_id,
                           zone_nodes=self.zone_nodes, spokes=self.spokes, convoys=self.convoys)


    def relax_spacing(self, rounds: int = 60) -> None:
        """Push apart any bodies closer than min_spacing. Deterministic, and topology never changes.

        Placement rules can legitimately put two things in the same place - a border field and a sea
        crossing between the same two powers, or two wormhole fixtures on the same approach.
        """
        floor = self.min_spacing
        movable = [n for n in self.nodes if n.role != "star"]
        for _ in range(rounds):
            worst = 0.0
            for i, a in enumerate(movable):
                for b in movable[i + 1:]:
                    dx, dy = b.pos[0] - a.pos[0], b.pos[1] - a.pos[1]
                    d = math.hypot(dx, dy)
                    if d >= floor:
                        continue
                    worst = max(worst, floor - d)
                    if d < 1e-6:                      # exactly coincident: separate deterministically
                        ang = (a.id * 2.399963) % (2 * math.pi)
                        dx, dy, d = math.cos(ang), math.sin(ang), 1.0
                    push = (floor - d) / 2 + 1.0
                    ux, uy = dx / d, dy / d
                    a.pos = (a.pos[0] - ux * push, a.pos[1] - uy * push)
                    b.pos = (b.pos[0] + ux * push, b.pos[1] + uy * push)
            if worst == 0.0:
                return


def compile_spec(spec: MapSpec, geometry: Geometry | None = None) -> CompiledMap:
    return _Builder(spec, geometry or Geometry()).build()


def to_galaxy_chart(m: CompiledMap, skybox: str = "skybox_random") -> dict:
    """galaxy_chart.json content (official schema shape; vanilla field patterns, FINDINGS §7)."""
    def node_json(n: Node) -> dict:
        d = {"id": n.id, "filling_name": n.filling_name,
             "position": [round(n.pos[0], 3), round(n.pos[1], 3)], **n.extra}
        if n.ownership:
            d["ownership"] = dict(n.ownership)
        return d
    star = node_json(m.nodes[m.star_id])
    star["child_nodes"] = [node_json(n) for n in m.nodes if n.id != m.star_id]
    lanes = []
    for l in m.lanes:
        d = {"id": l.id, "node_a": l.a, "node_b": l.b}
        if l.type != "normal":
            d["type"] = l.type
        lanes.append(d)
    return {"version": 1, "skybox": skybox, "root_nodes": [star], "phase_lanes": lanes}
