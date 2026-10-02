"""Default ring template (BRIEF S1): MapParams -> MapSpec.

Changing players/planets rescales the design; filler absorbs the remainder. If the counts cannot be
satisfied, TemplateError names the constraint that broke.
"""
from __future__ import annotations

from ..params import MapParams
from ..spec import Constraints, Layout, Link, MapSpec, Meta, Placement, Zone


class TemplateError(Exception):
    def __init__(self, constraint: str, message: str):
        super().__init__(f"[{constraint}] {message}")
        self.constraint = constraint


def convoy_pairs(players: int, skip: int) -> list[tuple[int, int]]:
    """Q3: chords (2k, 2k+skip) must form a perfect matching of the regions."""
    if players % 2:
        raise TemplateError("CONVOY_MATCHING", f"{players} players: one convoy per region needs an even player count")
    pairs = [(2 * k, (2 * k + skip) % players) for k in range(players // 2)]
    used = [r for p in pairs for r in p]
    if sorted(used) != list(range(players)):
        raise TemplateError("CONVOY_MATCHING",
                            f"--convoy-skip {skip} with {players} players does not give every region exactly one "
                            f"convoy (pairs {pairs}). Try another odd skip (3 works for 6, 8 and 10 players).")
    if any(abs(a - b) in (1, players - 1) for a, b in pairs):
        raise TemplateError("CONVOY_MATCHING", f"--convoy-skip {skip}: convoys would join ring neighbours")
    return pairs


def build_ring(p: MapParams, max_bodies_per_star: int) -> MapSpec:
    P = p.players
    if not 2 <= P <= 10:
        raise TemplateError("PLAYERS_RANGE", f"players must be 2..10, got {P}")
    majors = sorted(set(p.major_borders))
    if any(not 0 <= b < P for b in majors):
        raise TemplateError("MAJOR_BORDERS", f"major borders {majors} must be in 0..{P - 1}")
    access = list(dict.fromkeys(p.core_access))
    if not access or any(not 0 <= r < P for r in access):
        raise TemplateError("CORE_ACCESS", f"core access regions {access} must be non-empty and in 0..{P - 1}")
    pairs = convoy_pairs(P, p.convoy_skip)

    home_planets = P * (len(p.home_slot_tiers) + 1)
    border_planets = P + len(majors)
    convoy_planets = len(pairs)
    core_planets = len(p.core_inner_tiers) + len(access)
    fixed = home_planets + border_planets + convoy_planets + core_planets
    filler_total = p.planets - fixed
    if filler_total < p.pirates:
        raise TemplateError("PLANET_BUDGET",
                            f"{p.planets} planets < {fixed} fixed (homes {home_planets}, borders {border_planets}, "
                            f"convoys {convoy_planets}, core {core_planets}) + {p.pirates} pirates. "
                            f"Need --planets >= {fixed + p.pirates}.")

    zones: list[Zone] = []
    links: list[Link] = []
    for i in range(P):
        zones.append(Zone(id=f"home_{i}", kind="home", owner_player=i,
                          planet_count=len(p.home_slot_tiers) + 1, size_tiers=list(p.home_slot_tiers),
                          resource_bias=p.home_bias, internal_links=p.home_links,
                          slot_biases=list(p.home_slot_biases) if p.home_slot_biases else None,
                          placement=Placement("ring_slot", slot=i)))
    for i in range(P):
        j = (i + 1) % P
        major = i in majors
        zones.append(Zone(id=f"border_{i}", kind="border", planet_count=2 if major else 1,
                          size_tiers=[p.major_border_tier] * 2 if major else [p.minor_border_tier],
                          resource_bias=p.border_bias_cycle[i % len(p.border_bias_cycle)],
                          internal_links="tree", placement=Placement("between", zones=[f"home_{i}", f"home_{j}"])))
        links.append(Link(f"home_{i}", f"border_{i}", "normal"))
        links.append(Link(f"border_{i}", f"home_{j}", "normal"))
    for k, (a, b) in enumerate(pairs):
        zones.append(Zone(id=f"convoy_{k}", kind="contested", planet_count=1, size_tiers=[p.contested_tier],
                          resource_bias=p.contested_bias, internal_links="tree",
                          placement=Placement("between", zones=[f"home_{a}", f"home_{b}"])))
        links.append(Link(f"home_{a}", f"convoy_{k}", "wormhole"))
        links.append(Link(f"convoy_{k}", f"home_{b}", "normal"))
    zones.append(Zone(id="core", kind="core", planet_count=core_planets,
                      size_tiers=list(p.core_inner_tiers) + [p.core_chokepoint_tier] * len(access),
                      resource_bias=p.core_bias,
                      slot_biases=list(p.core_inner_biases) + [p.core_chokepoint_bias] * len(access),
                      internal_links="loop", placement=Placement("center"),
                      gated=True, chokepoints=len(access)))
    for r in access:
        links.append(Link(f"home_{r}", "core", "wormhole", chokepoint=True))
    neutral = filler_total - p.pirates
    if neutral:
        zones.append(Zone(id="filler", kind="filler", planet_count=neutral,
                          size_tiers=[p.filler_tier_cycle[k % len(p.filler_tier_cycle)] for k in range(neutral)],
                          resource_bias=p.filler_bias, internal_links="tree", placement=Placement("gap")))
    if p.pirates:
        zones.append(Zone(id="pirates", kind="pirate", planet_count=p.pirates, size_tiers=[],
                          resource_bias="none", internal_links="tree", placement=Placement("gap"), npc="pirate"))

    return MapSpec(
        meta=Meta(name=p.name, display_name=p.display_name, description=p.description,
                  players=P, teams=0, seed=p.seed),
        layout=Layout(shape="ring", radius_scale=1.0),
        zones=zones,
        links=links,
        constraints=Constraints(total_planets=p.planets, max_bodies_per_star=max_bodies_per_star, symmetric=True,
                                notes=[f"convoys {pairs}", f"core access {access}", f"major borders {majors}"]),
    )
