"""Write specs/ww2_global.mapspec.json - the WW2 global map (clusters layout).

Deliberately asymmetric: the imbalance is the design, so REGION_ADVANTAGE_STACK is expected to fire.
Run:  .venv\\Scripts\\python tools\\make_ww2_global.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mapgen import ROOT  # noqa: E402

EUROPE, PACIFIC, ATLANTIC = "europe", "pacific", "atlantic"


def home(zid, player, cluster, slot, tiers, biases, links="loop"):
    return {"id": zid, "kind": "home", "owner_player": player, "planet_count": len(tiers) + 1,
            "size_tiers": tiers, "slot_biases": biases, "resource_bias": "metal",
            "internal_links": links, "placement": {"kind": "cluster", "cluster": cluster, "slot": slot},
            "gated": False, "chokepoints": 0, "loot": "none", "npc": "none"}


def field(zid, a, b, tiers, bias):
    return {"id": zid, "kind": "border", "planet_count": len(tiers), "size_tiers": tiers,
            "resource_bias": bias, "internal_links": "tree",
            "placement": {"kind": "between", "zones": [a, b]},
            "gated": False, "chokepoints": 0, "loot": "none", "npc": "none"}


def crossing(zid, a, b, tier="S", bias="balanced"):
    return {"id": zid, "kind": "contested", "planet_count": 1, "size_tiers": [tier],
            "resource_bias": bias, "internal_links": "tree",
            "placement": {"kind": "between", "zones": [a, b]},
            "gated": False, "chokepoints": 0, "loot": "none", "npc": "none"}


def oil(zid, a, b, inner_tiers, chokepoints):
    """A gated crystal field: inner planets first, then one planet per chokepoint."""
    tiers = inner_tiers + ["L"] * chokepoints
    return {"id": zid, "kind": "core", "planet_count": len(tiers), "size_tiers": tiers,
            "resource_bias": "crystal", "internal_links": "loop",
            "placement": {"kind": "between", "zones": [a, b]},
            "gated": True, "chokepoints": chokepoints, "loot": "none", "npc": "none"}


def gap(zid, kind, count, cluster, tiers=None, bias="balanced", npc="none"):
    return {"id": zid, "kind": kind, "planet_count": count, "size_tiers": tiers or [],
            "resource_bias": bias if tiers else "none", "internal_links": "tree",
            "placement": {"kind": "cluster", "cluster": cluster, "slot": 0},
            "gated": False, "chokepoints": 0, "loot": "none", "npc": npc}


def link(a, b, lane="normal", chokepoint=False):
    return {"from_zone": a, "to_zone": b, "lane": lane, "via_contested_planets": 0,
            "chokepoint": chokepoint}


M, B, C = "metal", "balanced", "crystal"

zones = [
    # ---- Europe: Axis interior lines, Allied depth, three neutrals on the routes
    # Germany: most metal on the map, almost no crystal
    home("germany", 0, EUROPE, 0, ["L", "L", "M", "M", "S", "S"], [M, M, M, B, M, M]),
    # Italy: small and weak, holds the Mediterranean crossing
    home("italy", 1, EUROPE, 1, ["M", "S", "S"], [M, B, M]),
    # USSR: large, deep, metal-solid
    home("ussr", 3, EUROPE, 2, ["L", "L", "M", "M", "M", "S", "S"], [M, M, M, B, B, M, B]),
    # Turkey: neutral on the land route to the Caucasus
    home("turkey", 6, EUROPE, 3, ["M", "S", "S"], [B, M, B]),
    # Sweden: neutral, pure metal, between Germany and the USSR
    home("sweden", 8, EUROPE, 4, ["L", "M", "S"], [M, M, M]),
    # Spain: neutral on the Gibraltar chokepoint
    home("spain", 5, EUROPE, 5, ["M", "S", "S"], [B, M, B]),

    # ---- Atlantic / Americas
    # USA: richest homes, furthest from every front
    home("usa", 4, ATLANTIC, 0, ["L", "L", "M", "M", "M", "S"], [M, M, B, B, B, B]),   # crystal bias is banned in homes (all crystal tiers are research-gated), so the USA is
    # richest by breadth: two ferrous plus three desert, no research needed to use any of it
    # Britain: island - reachable only by wormhole
    home("britain", 2, ATLANTIC, 1, ["M", "M", "S", "S"], [B, B, B, M]),

    # ---- Pacific
    # Japan: isolated, metal-poor, crystal-starved
    home("japan", 7, PACIFIC, 0, ["M", "S", "S", "S"], [M, M, B, M]),
    # Siam: neutral on the approach to the East Indies
    home("siam", 9, PACIFIC, 1, ["M", "S", "S"], [B, M, B]),

    # ---- fronts and seams (Europe)
    field("f_alps", "germany", "italy", ["M"], B),
    field("f_eastern", "germany", "ussr", ["L", "L"], M),          # industrial front: metal, no crystal
    field("f_baltic", "germany", "sweden", ["M"], M),
    field("f_finland", "ussr", "sweden", ["S"], B),
    field("f_caucasus_road", "ussr", "turkey", ["M"], C),
    field("f_gibraltar", "spain", "italy", ["M"], B),              # Atlantic <-> Med, balanced
    field("f_aegean", "italy", "turkey", ["S"], C),
    field("f_east_indies_sea", "japan", "siam", ["M"], M),         # Pacific seam: metal only

    # ---- sea crossings (wormholes), each with a contested planet
    crossing("x_channel", "germany", "britain", "S", M),
    crossing("x_atlantic_north", "usa", "britain", "M"),
    crossing("x_atlantic_murmansk", "usa", "ussr", "M"),
    crossing("x_pacific_midway", "usa", "japan", "M", M),
    crossing("x_pacific_solomons", "japan", "siam", "S", M),
    crossing("x_pacific_philippines", "usa", "siam"),
    crossing("x_med_north_africa", "italy", "spain", "S", M),

    # ---- the four gated oil fields (crystal), each behind chokepoints
    oil("oil_ploiesti", "germany", "turkey", ["M", "M"], 1),            # small, shallow, Axis-adjacent
    oil("oil_caucasus", "ussr", "turkey", ["L", "L", "M", "M"], 1),     # large, one hard chokepoint
    oil("oil_persian_gulf", "turkey", "britain", ["L", "M", "M"], 2),   # medium, two ways in
    oil("oil_east_indies", "siam", "japan", ["L", "L", "M", "M"], 1),   # large, Japan's objective

    # ---- partisans in the occupied gaps, weighted to Europe
    gap("partisans_europe", "pirate", 5, EUROPE, npc="pirate"),
    gap("partisans_pacific", "pirate", 2, PACIFIC, npc="pirate"),
    gap("partisans_atlantic", "pirate", 1, ATLANTIC, npc="pirate"),
    gap("neutrals_europe", "filler", 8, EUROPE, ["S", "M", "S", "M", "S", "S", "M", "S"]),
    gap("neutrals_pacific", "filler", 5, PACIFIC, ["S", "M", "S", "S", "M"]),
    gap("neutrals_atlantic", "filler", 4, ATLANTIC, ["M", "S", "S", "M"]),
]

links = [
    # Europe: land fronts
    link("germany", "f_alps"), link("f_alps", "italy"),
    link("germany", "f_eastern"), link("f_eastern", "ussr"),
    link("germany", "f_baltic"), link("f_baltic", "sweden"),
    link("ussr", "f_finland"), link("f_finland", "sweden"),
    link("ussr", "f_caucasus_road"), link("f_caucasus_road", "turkey"),
    link("spain", "f_gibraltar"), link("f_gibraltar", "italy"),
    link("italy", "f_aegean"), link("f_aegean", "turkey"),
    # Pacific seam
    link("japan", "f_east_indies_sea"), link("f_east_indies_sea", "siam"),
    # sea crossings: wormhole out, normal lane in
    link("germany", "x_channel", "wormhole"), link("x_channel", "britain"),
    link("usa", "x_atlantic_north", "wormhole"), link("x_atlantic_north", "britain"),
    link("usa", "x_atlantic_murmansk", "wormhole"), link("x_atlantic_murmansk", "ussr"),
    link("usa", "x_pacific_midway", "wormhole"), link("x_pacific_midway", "japan"),
    link("japan", "x_pacific_solomons", "wormhole"), link("x_pacific_solomons", "siam"),
    link("usa", "x_pacific_philippines", "wormhole"), link("x_pacific_philippines", "siam"),
    link("italy", "x_med_north_africa", "wormhole"), link("x_med_north_africa", "spain"),
    # oil fields: land chokepoints, one lane in each
    link("germany", "oil_ploiesti", "normal", chokepoint=True),
    link("ussr", "oil_caucasus", "normal", chokepoint=True),
    link("turkey", "oil_persian_gulf", "normal", chokepoint=True),
    link("britain", "oil_persian_gulf", "normal", chokepoint=True),
    link("siam", "oil_east_indies", "normal", chokepoint=True),
]

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--name", default="ww2_global")
ap.add_argument("--display-name", dest="display_name", default="WW2: Global")
ap.add_argument("--scale", type=float, default=1.0,
                help="radius_scale: 1.8 keeps the map inside vanilla's largest footprint (|coord| 10061)")
ap.add_argument("--seed", type=int, default=1939)
args = ap.parse_args()

total = sum(z["planet_count"] for z in zones)
spec = {
    "meta": {"name": args.name, "display_name": args.display_name,
             "description": "Three theaters, ten powers, four oil fields. Asymmetric on purpose.",
             "players": 10, "teams": 0, "seed": args.seed},
    "layout": {"shape": "clusters", "radius_scale": args.scale},
    "zones": zones,
    "links": links,
    "constraints": {"total_planets": total, "max_bodies_per_star": 150, "symmetric": False,
                    "notes": ["asymmetric by design: REGION_ADVANTAGE_STACK is expected, not a fault",
                              "Axis hold metal and interior lines; their crystal is behind a gated oil field",
                              "Britain is reachable only by wormhole; the USA is furthest from every front",
                              "each neutral sits on a route whose alignment opens or closes a front"]},
}

out = ROOT / "specs" / f"{args.name}.mapspec.json"
out.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
kinds: dict[str, int] = {}
for z in zones:
    kinds[z["kind"]] = kinds.get(z["kind"], 0) + z["planet_count"]
print(f"wrote {out}\n  {total} planets: " + ", ".join(f"{v} {k}" for k, v in sorted(kinds.items())))
print(f"  {len(zones)} zones, {len(links)} links, "
      f"{sum(1 for l in links if l['lane'] == 'wormhole')} wormhole crossings, "
      f"{sum(1 for l in links if l['chokepoint'])} gated chokepoints")
