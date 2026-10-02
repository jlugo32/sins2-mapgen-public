"""Write a three-ring concentric map: depth = risk.

Outer decagon of homes, middle decagon (half a step round) of contested crystal, inner decagon of
rich planets, and a gated core at the centre. Every ring is laterally connected, so a chokepoint on
one spoke seals nothing - that is deliberate.

Run:  .venv\\Scripts\\python tools\\make_concentric.py
      ... --inner-arcs 2        2 arcs instead of 3 (a lopsided 2/1 core-gate split)
      ... --inner-arcs 1        one unbroken inner ring

--ungate-core is KNOWN BROKEN and refuses to run. See FINDINGS.md S10.1.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mapgen import ROOT  # noqa: E402

M, B, C = "metal", "balanced", "crystal"

REFUSED = """--ungate-core is known broken and will not run.
  1. It emits no garrison planets at all. The help text promised militia-heavy defenders; the
     random_city_planet count on the map it generates is zero.
  2. Its 'core pirates' do not guard the core. They are a gap-placement zone, so they scatter
     map-wide like any other filler: measured at radius 806, 806, 2532 and 3425 while the core
     sits at 432 - one of them on the far rim, at 100% of the map radius.
  The result is five large irradiated planets at the centre, 4-6 hops from every home, defended
  by nothing but their own militia.
  Fixing it means giving the core zone explicit garrison planets and anchoring the pirates to the
  centre instead of the gap pool. Measurements and reasoning: FINDINGS.md S10.1."""


def zone(zid, kind, tiers, bias, placement, **kw):
    z = {"id": zid, "kind": kind, "planet_count": kw.pop("planet_count", len(tiers)),
         "size_tiers": tiers, "resource_bias": bias, "internal_links": kw.pop("internal_links", "tree"),
         "placement": placement, "gated": kw.pop("gated", False), "chokepoints": kw.pop("chokepoints", 0),
         "loot": "none", "npc": kw.pop("npc", "none")}
    z.update(kw)
    return z


def link(a, b, lane="normal", chokepoint=False):
    return {"from_zone": a, "to_zone": b, "lane": lane, "via_contested_planets": 0, "chokepoint": chokepoint}


def build(args) -> dict:
    n = 10
    core_access = [0, 3, 7]                      # evenly spread inner vertices
    zones, links = [], []

    # OUTER band 0: one home per player, 4 planets, metal-leaning and crystal-poor
    for i in range(n):
        zones.append(zone(f"home_{i}", "home", ["L", "M", "S"], M,
                          {"kind": "band", "band": 0, "slot": i},
                          planet_count=4, internal_links="loop", owner_player=i,
                          slot_biases=[M, B, M]))
    for i in range(n):                           # outer ring lanes between adjacent homes
        links.append(link(f"home_{i}", f"home_{(i + 1) % n}"))

    # MIDDLE band 1: half a step round, so each sits between two homes. Crystal-leaning, 2 planets.
    for i in range(n):
        zones.append(zone(f"mid_{i}", "contested", ["M", "S"], C,
                          {"kind": "band", "band": 1, "slot": i}))
        links.append(link(f"home_{i}", f"mid_{i}"))
        links.append(link(f"mid_{i}", f"home_{(i + 1) % n}"))
        links.append(link(f"mid_{i}", f"mid_{(i + 1) % n}"))

    # INNER band 2: aligned with the homes, one rich planet each
    for i in range(n):
        zones.append(zone(f"inner_{i}", "custom", ["L"], C,
                          {"kind": "band", "band": 2, "slot": i}))
        links.append(link(f"inner_{i}", f"mid_{i}"))
    # lateral inner links: a full ring, or arcs with gaps that stop an attacker lapping it
    if args.inner_arcs <= 1:
        gaps = set()
    else:
        gaps = {round(k * n / args.inner_arcs) % n for k in range(args.inner_arcs)}
    for i in range(n):
        if i not in gaps:
            links.append(link(f"inner_{i}", f"inner_{(i + 1) % n}"))

    # CORE: 5 irradiated rich planets, plus one garrison chokepoint per access spoke
    if args.ungate_core:
        zones.append(zone("core", "core", ["L"] * 5, B, {"kind": "center"}, internal_links="loop"))
        for i in core_access:
            links.append(link(f"inner_{i}", "core"))
        zones.append(zone("core_pirates", "pirate", [], "none", {"kind": "gap"},
                          planet_count=args.core_pirates, npc="pirate"))
    else:
        zones.append(zone("core", "core", ["L"] * 5 + ["M"] * len(core_access), B,
                          {"kind": "center"}, internal_links="loop",
                          gated=True, chokepoints=len(core_access), chokepoint_role="garrison"))
        for i in core_access:
            links.append(link(f"inner_{i}", "core", "normal", chokepoint=True))

    # WORMHOLES: 5 diametric pairs, so every home has exactly one back door
    for i in range(n // 2):
        links.append(link(f"home_{i}", f"home_{i + n // 2}", "wormhole"))

    # FILLER in the gaps between the rings, pirate-heavy
    pirates = args.pirates if not args.ungate_core else max(0, args.pirates - args.core_pirates)
    filler = args.filler_total - pirates - (args.core_pirates if args.ungate_core else 0)
    zones.append(zone("partisans", "pirate", [], "none", {"kind": "gap"},
                      planet_count=pirates, npc="pirate"))
    zones.append(zone("drifters", "filler", [["S", "M"][k % 2] for k in range(filler)], B,
                      {"kind": "gap"}))

    total = sum(z["planet_count"] for z in zones)
    return {
        "meta": {"name": args.name, "display_name": args.display_name,
                 "description": "Three rings. The deeper you push, the richer it gets and the more "
                                "directions can reach you.",
                 "players": n, "teams": 0, "seed": args.seed},
        "layout": {"shape": "concentric", "radius_scale": args.scale,
                   "band_radii": [1.0, 0.70, 0.40], "band_offsets": [0.0, 0.5, 0.0]},
        "zones": zones, "links": links,
        "constraints": {"total_planets": total, "max_bodies_per_star": 150, "symmetric": True,
                        "notes": ["depth = risk: outer homes are metal-leaning and crystal-poor, all real "
                                  "crystal is in the middle ring and inward",
                                  "every ring is laterally connected, so one chokepoint seals nothing",
                                  "the 3 core-access inner vertices are the best real estate on the map",
                                  "5 diametric wormholes: every home has one back door, nobody has a safe rear"]},
    }


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--name", default="three_rings")
ap.add_argument("--display-name", dest="display_name", default="Three Rings")
ap.add_argument("--scale", type=float, default=1.35)
ap.add_argument("--seed", type=int, default=3)
ap.add_argument("--inner-arcs", dest="inner_arcs", type=int, default=3,
                help="3 = one core gate per arc (default); 2 = a lopsided 2/1 split; 1 = a full ring")
ap.add_argument("--ungate-core", dest="ungate_core", action="store_true",
                help="KNOWN BROKEN, refuses to run - see FINDINGS.md S10.1")
ap.add_argument("--pirates", type=int, default=15)
ap.add_argument("--core-pirates", dest="core_pirates", type=int, default=4)
ap.add_argument("--filler-total", dest="filler_total", type=int, default=25)
args = ap.parse_args()
if args.ungate_core:
    raise SystemExit(REFUSED)

spec = build(args)
out = ROOT / "specs" / f"{args.name}.mapspec.json"
out.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
kinds: dict[str, int] = {}
for z in spec["zones"]:
    kinds[z["kind"]] = kinds.get(z["kind"], 0) + z["planet_count"]
print(f"wrote {out}")
print(f"  {spec['constraints']['total_planets']} planets: " + ", ".join(f"{v} {k}" for k, v in sorted(kinds.items())))
print(f"  {len(spec['zones'])} zones, {len(spec['links'])} links, "
      f"{sum(1 for l in spec['links'] if l['lane'] == 'wormhole')} wormhole pairs, "
      f"{sum(1 for l in spec['links'] if l['chokepoint'])} gated chokepoints")
