"""Plain-English summary of what was ACTUALLY built.

Everything here is computed from the compiled graph. The model's own account of its map is never used;
its assumptions are printed separately, clearly labelled as claims rather than findings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rich.console import Console

from .. import rules
from ..compiler import CompiledMap
from ..pipeline import reachable_resources, summary


@dataclass
class Check:
    asked: str
    built: str
    ok: bool


def describe(m: CompiledMap) -> list[str]:
    """Sentences about the compiled map. Derived only from nodes, lanes and zones."""
    spec = m.spec
    homes = [n for n in m.nodes if n.role == "home"]
    fixtures = m.fixtures()
    gated = [z for z in spec.zones if z.gated]
    pirates = [n for n in m.nodes if n.role == "pirate"]
    kinds: dict[str, int] = {}
    for n in m.planets():
        kinds[spec.zone(n.zone).kind if n.zone else "?"] = \
            kinds.get(spec.zone(n.zone).kind if n.zone else "?", 0) + 1

    out = [f"{spec.meta.display_name}: {len(homes)} players, {len(m.planets())} planets and "
           f"{len(fixtures)} wormhole fixtures around 1 star ({len(m.bodies())} bodies), "
           f"{len(m.lanes)} lanes of which {sum(1 for l in m.lanes if l.type == 'wormhole')} are wormholes."]
    out.append("Planets by role: " + ", ".join(f"{v} {k}" for k, v in sorted(kinds.items())) + ".")

    if m.convoys:
        pairs = ", ".join(f"{a}-{b}" for a, _, b in m.convoys)
        out.append(f"{len(m.convoys)} convoys, each a wormhole pair with a contested planet: {pairs}.")
    else:
        out.append("No convoys: no wormhole route joins two home regions through a contested planet.")

    for z in gated:
        ids = m.zone_nodes[z.id]
        chokes = [i for i in ids if m.nodes[i].role == "chokepoint"]
        froms = sorted(s.from_zone for s in m.spokes if s.zone == z.id)
        out.append(f"Zone '{z.id}' is gated: {len(ids)} planets behind {len(chokes)} chokepoint(s), "
                   f"reached only from {', '.join(froms) or 'nowhere'}. Removing the chokepoints cuts it "
                   f"off from every home planet.")
    if not gated:
        out.append("Nothing is gated: every zone is reachable without passing a chokepoint.")

    if pirates:
        out.append(f"{len(pirates)} pirate planet(s) in the gaps.")
    reach = reachable_resources(m)
    if reach:
        crystal = {r: c for r, (mt, c, _) in reach.items()}
        lo, hi = min(crystal.values()), max(crystal.values())
        metal = {r: mt for r, (mt, c, _) in reach.items()}
        out.append(f"Reachable without entering a gated zone: metal {min(metal.values()):g}-"
                   f"{max(metal.values()):g}, crystal {lo:g}-{hi:g} per region.")
    adv = rules.region_advantages(m)
    both = [r for r, (core, majors) in adv.items() if core and majors]
    neither = [r for r, (core, majors) in adv.items() if not core and not majors]
    if both and neither:
        out.append(f"Uneven: {', '.join(both)} hold both core access and a major field while "
                   f"{', '.join(neither)} hold neither.")
    return out


def compare_request(m: CompiledMap, request: str) -> list[Check]:
    """Cheap, honest checks of the request text against the built graph.

    Only claims we can read off the graph are checked; anything else is left to the summary above.
    """
    spec = m.spec
    text = request.lower()
    checks: list[Check] = []

    def number_before(*words: str) -> int | None:
        for w in words:
            hit = re.search(rf"(\d+)\s*(?:-|\s)?\s*{w}", text)
            if hit:
                return int(hit.group(1))
        return None

    want_players = number_before("player", "players", "way", "empires", "factions")
    if want_players is not None:
        built = len([n for n in m.nodes if n.role == "home"])
        checks.append(Check(f"{want_players} players", f"{built} players", want_players == built))
    want_planets = number_before("planet", "planets")
    if want_planets is not None:
        built = len(m.planets())
        checks.append(Check(f"{want_planets} planets", f"{built} planets", want_planets == built))

    if any(w in text for w in ("gated", "chokepoint", "choke point", "only be reached", "locked")):
        gated = [z for z in spec.zones if z.gated]
        chokes = sum(z.chokepoints for z in gated)
        checks.append(Check("a gated area behind chokepoints",
                            f"{len(gated)} gated zone(s), {chokes} chokepoint(s)" if gated
                            else "nothing gated",
                            bool(gated)))
    if "wormhole" in text or "convoy" in text:
        checks.append(Check("wormholes", f"{len(m.fixtures())} fixtures, {len(m.convoys)} convoys",
                            bool(m.fixtures())))
    if "pirate" in text:
        n = sum(1 for x in m.nodes if x.role == "pirate")
        checks.append(Check("pirates", f"{n} pirate planet(s)", n > 0))
    if "team" in text:
        checks.append(Check("teams", f"teams = {spec.meta.teams}", spec.meta.teams > 0))
    if "symmetric" in text or "symmetrical" in text:
        sizes = {len(m.zone_nodes[z.id]) for z in spec.zones if z.kind == "home"}
        checks.append(Check("symmetric regions", f"home sizes {sorted(sizes)}", len(sizes) == 1))
    return checks


def report(m: CompiledMap, console: Console | None = None, request: str | None = None,
           assumptions: list[str] | None = None, tables: bool = True) -> None:
    console = console or Console()
    console.print("[bold]What was built[/] (computed from the compiled map, not from the model):")
    for line in describe(m):
        console.print(f"  {line}", markup=False)      # map text may contain [brackets]
    if tables:
        summary(m, console)                           # already prints the advantage + reachability tables
    if request:
        checks = compare_request(m, request)
        if checks:
            console.print("\n[bold]Against your request:[/]")
            for c in checks:
                mark = "[green]match[/]" if c.ok else "[red]DIFFERS[/]"
                console.print(f"  {mark}  asked: {c.asked}  ->  built: {c.built}")
    if assumptions:
        console.print("\n[bold]Assumptions the model reported[/] (its claims, not checked):")
        for a in assumptions:
            console.print(f"  - {a}", markup=False)
