"""MapSpec -> validated mod folder. Shared by the CLI, the tests and (later) the AI layer."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import rules
from .compiler import CompiledMap, compile_spec, to_galaxy_chart
from .config import Config
from .mod_writer import mod_files, write_tree
from .params import MapParams
from .preview import render
from .spec import MapSpec
from .validate import Problem, validate_mod


@dataclass
class BuildResult:
    compiled: CompiledMap
    violations: list[rules.Violation]
    problems: list[Problem] = field(default_factory=list)
    mod_dir: Path | None = None
    preview: Path | None = None
    spec_path: Path | None = None

    @property
    def ok(self) -> bool:
        return not rules.errors(self.violations) and not self.problems


def build(spec: MapSpec, params: MapParams, cfg: Config, out_root: Path, preview_only: bool = False) -> BuildResult:
    m = compile_spec(spec, params.geometry)
    chart = to_galaxy_chart(m)
    res = BuildResult(compiled=m, violations=rules.check(m, chart, cfg.limits))
    if rules.errors(res.violations):
        return res  # any rule violation means no output
    out_root.mkdir(parents=True, exist_ok=True)
    name = spec.meta.name
    res.preview = out_root / f"{name}_preview.png"
    res.preview.write_bytes(render(m, 1600, labels=True))
    res.spec_path = out_root / f"{name}.mapspec.json"
    spec.save(res.spec_path)
    if preview_only:
        return res
    stage = out_root / f".{name}.staging" / name
    write_tree(stage, mod_files(m, params, render(m, 512)))
    res.problems = validate_mod(stage, cfg)
    if res.problems:
        shutil.rmtree(stage.parent)
        return res
    final = out_root / name
    if final.exists():
        shutil.rmtree(final)
    stage.rename(final)
    shutil.rmtree(stage.parent)
    res.mod_dir = final
    return res


def balance_table(m: CompiledMap, console: Console | None = None) -> None:
    """Per-region core access and major fields touched (BRIEF S5 balance check)."""
    console = console or Console()
    adv = rules.region_advantages(m)
    t = Table(title="Region advantages")
    for col in ("region", "core access", "majors touched", "advantages"):
        t.add_column(col)
    for region, (core, majors) in sorted(adv.items()):
        n = (1 if core else 0) + len(majors)
        flag = "none" if n == 0 else ("both" if core and majors else str(n))
        t.add_row(region, "spoke" if core else "-", ", ".join(majors) or "-", flag)
    console.print(t)


def reachable_resources(m: CompiledMap) -> dict[str, tuple[float, float, list[str]]]:
    """Per home region: average metal/crystal reachable WITHOUT entering a gated zone.

    Counts the region's own non-home planets plus every border/contested zone it links to. The player
    home planet itself is excluded (player_home_planet resolves to a random 'fair' planet at load time).
    Border and contested planets are shared with a neighbour, so these totals are an upper bound.
    """
    out: dict[str, tuple[float, float, list[str]]] = {}
    for z in m.spec.zones:
        if z.kind != "home":
            continue
        zones = {z.id}
        for l in m.spec.links:
            for a, b in ((l.from_zone, l.to_zone), (l.to_zone, l.from_zone)):
                if a == z.id and m.spec.zone(b).kind in ("border", "contested"):
                    zones.add(b)
        metal = crystal = 0.0
        for zid in zones:
            for i in m.zone_nodes[zid]:
                n = m.nodes[i]
                if n.role == "home":
                    continue
                metal += n.metal_mean
                crystal += n.crystal_mean
        out[z.id] = (metal, crystal, sorted(zones - {z.id}))
    return out


def reachability_table(m: CompiledMap, console: Console | None = None, crystal_floor: float = 15.0) -> None:
    console = console or Console()
    data = reachable_resources(m)
    t = Table(title=f"Reachable without entering the core (crystal floor {crystal_floor:g})")
    for col in ("region", "metal", "crystal", "crystal/metal", "sources", "flag"):
        t.add_column(col)
    for region, (metal, crystal, sources) in sorted(data.items()):
        low = crystal < crystal_floor
        t.add_row(region, f"{metal:g}", f"{crystal:g}", f"{crystal / metal:.2f}" if metal else "-",
                  ", ".join(sources), "[red]LOW[/]" if low else "ok")
    console.print(t)


def summary(m: CompiledMap, console: Console | None = None) -> None:
    console = console or Console()
    spec = m.spec
    homes = sorted((z for z in spec.zones if z.kind == "home"), key=lambda z: z.owner_player)
    partner = {}
    for a, c, b in m.convoys:
        partner[a] = f"-> {b} ({c})"
        partner[b] = f"<- {a} ({c})"
    access = {s.from_zone for s in m.spokes}
    borders = {tuple(z.placement.zones): z for z in spec.zones if z.kind == "border"}

    t = Table(title=f"{spec.meta.display_name} - per region")
    for col in ("region", "planets", "lanes", "metal/crystal (avg, non-home)", "(R)", "convoy", "borders", "core"):
        t.add_column(col)
    for z in homes:
        ids = m.zone_nodes[z.id]
        lanes = sum(1 for l in m.lanes if l.a in ids or l.b in ids)
        others = [m.nodes[i] for i in ids if m.nodes[i].role != "home"]
        metal = sum(n.metal_mean for n in others)
        crystal = sum(n.crystal_mean for n in others)
        r = sum(1 for n in others if n.research_gated)
        bs = []
        for (a, b), bz in borders.items():
            if z.id in (a, b):
                bs.append(f"{bz.id}{'*' if bz.planet_count > 1 else ''}")
        t.add_row(z.id, str(len(ids)), str(lanes), f"{metal:g} / {crystal:g}", str(r), partner.get(z.id, "-"),
                  ", ".join(sorted(bs)), "spoke" if z.id in access else "-")
    console.print(t)
    kinds = {}
    for z in spec.zones:
        kinds[z.kind] = kinds.get(z.kind, 0) + z.planet_count
    console.print(f"planets {len(m.planets())} ({', '.join(f'{k} {v}' for k, v in kinds.items())}); "
                  f"wormhole fixtures {len(m.fixtures())} (reported separately); star 1; "
                  f"bodies under star {len(m.bodies())}; lanes {len(m.lanes)} "
                  f"({sum(1 for l in m.lanes if l.type == 'wormhole')} wormhole)")
    balance_table(m, console)
    reachability_table(m, console)
    console.print("* = major field (2 planets). Chokepoints: "
                  + ", ".join(f"{s.from_zone}->node {s.chokepoint}" for s in m.spokes))
