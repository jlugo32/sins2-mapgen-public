"""Build data/fillings.json from the vanilla install (read-only).

The table layout (which filling fills which tier x bias cell) is the decision recorded in BRIEF.md §0
Resources. Every number in the output is read from the game files here, never typed in by hand.

Usage:  .venv\\Scripts\\python tools\\build_fillings.py
"""
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# BRIEF.md §0 Resources. XL metal/crystal reuse L on purpose; gas giant is XL balanced only.
TABLE = {
    "S": {"metal": "random_ship_graveyard_planet", "crystal": "random_oceanic_planet", "balanced": "random_barren_planet"},
    "M": {"metal": "random_volcanic_planet", "crystal": "random_ice_planet", "balanced": "random_desert_planet"},
    "L": {"metal": "random_ferrous_planet", "crystal": "random_crystalline_planet", "balanced": "random_irradiated_planet"},
    "XL": {"metal": "random_ferrous_planet", "crystal": "random_crystalline_planet", "balanced": "random_gas_giant_planet"},
}
# Fixed roles. Each filling name is checked against vanilla node_fillings below.
ROLES = {
    "star": {"filling_name": "random_star",
             "note": "most-used star filling in vanilla maps (84 nodes, 54 maps)"},
    "player_home": {"filling_name": "player_home_planet",
                    "note": "vanilla home pattern: ownership.player_index (0-based)"},
    "pirate": {"filling_name": "player_home_planet", "ownership": {"npc_filling_name": "pirate"},
               "note": "vanilla pirate pattern, 34 uses (e.g. public_agamemnons_bounty node 27)"},
    "wormhole": {"filling_name": "wormhole_fixture",
                 "note": "vanilla wormhole_fillings.default_wormhole_fixture"},
    "garrison": {"filling_name": "random_city_planet",
                 "note": "pure defence: city_planet has 0 metal and 0 crystal but militia_supply "
                         "125-135 (entities/city_planet.unit, planet.uniforms). Expensive to take, "
                         "worthless to hold - what a chokepoint should be. Not reachable through "
                         "tier x bias, which is resource-based."},
}
HOME_BIAS_PATTERN = ["metal", "balanced"]


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def asteroid_range(planet: dict, kind: str) -> list[int]:
    lo = hi = 0
    for prefix in ("non_random_", "random_"):
        for t in (planet.get(f"{prefix}{kind}_asteroids") or {}).get("tiers", []):
            lo += t["count"][0]
            hi += t["count"][1]
    return [lo, hi]


def main() -> int:
    cfg = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
    game = Path(cfg["game_dir"])
    fill = load(game / "uniforms" / "galaxy_generator.uniforms")["fillings"]
    node_f = {i["name"]: i["filling"] for i in fill["node_fillings"]}
    rand_f = {i["name"]: i["filling"] for i in fill["random_fixture_fillings"]}
    fix_f = {i["name"]: i["filling"] for i in fill["fixture_fillings"]}

    # research gating: playable factions are the .player files with a planet_types list
    gated: dict[str, list[str]] = {}
    playable: list[str] = []
    for p in sorted((game / "entities").glob("*.player")):
        found = find_planet_types(load(p))  # planet_types sits under different parents per file
        if not found:
            continue
        playable.append(p.stem)
        for entry in found:
            if entry.get("colonization_research_prerequisites"):
                gated.setdefault(entry["planet_type"], []).append(p.stem)

    def entry(name: str) -> dict:
        nf = node_f[name]
        items = rand_f[nf["primary_random_fixture_filling_name"]]["items"]
        if len(items) != 1:
            raise SystemExit(f"{name}: expected a single-type filling, got {len(items)} items")
        entity = fix_f[items[0]["name"]]["entity_definition"]
        unit = f"entities/{entity}.unit"
        planet = load(game / unit)["planet"]
        pt = planet["planet_type"]
        return {
            "filling_name": name,
            "unit_file": unit,
            "planet_type": pt,
            "metal": asteroid_range(planet, "metal"),
            "crystal": asteroid_range(planet, "crystal"),
            "research_gated": sorted(gated.get(pt, [])) == sorted(playable),
        }

    def role_entry(name: str) -> dict | None:
        """Resolve a role filling to its asteroid numbers, tolerating what entry() cannot.

        Added 2026-09-25. Roles carried no metal/crystal at all, so every player home and every
        pirate planet was accounted as 0/0 while the game gives them real asteroids.

        Two things entry() cannot do. A star and a wormhole fixture are not planets, so they have no
        asteroids: return None. And player_home_planet is not one planet - it resolves to
        random_fair_planet, a weighted roll over four entities that the GAME performs at load, not
        us. Its 'metal'/'crystal' are therefore the range across every outcome, and the expected_*
        values are probability-weighted, because the midpoint of the range is not the mean when the
        outcomes are not uniform.
        """
        nf = node_f.get(name)
        if not nf:
            return None
        items = rand_f[nf["primary_random_fixture_filling_name"]]["items"]
        roll, total = [], sum(i["probability"] for i in items)
        for it in items:
            entity = fix_f[it["name"]]["entity_definition"]
            unit = f"entities/{entity}.unit"
            body = load(game / unit)
            if "planet" not in body:
                return None                       # a star or a fixture: no asteroids to account for
            pl = body["planet"]
            roll.append({"entity": entity, "planet_type": pl["planet_type"],
                         "probability": it["probability"] / total,
                         "metal": asteroid_range(pl, "metal"),
                         "crystal": asteroid_range(pl, "crystal"), "unit_file": unit})
        out = {
            "metal": [min(r["metal"][0] for r in roll), max(r["metal"][1] for r in roll)],
            "crystal": [min(r["crystal"][0] for r in roll), max(r["crystal"][1] for r in roll)],
            "expected_metal": round(sum(r["probability"] * sum(r["metal"]) / 2 for r in roll), 4),
            "expected_crystal": round(sum(r["probability"] * sum(r["crystal"]) / 2 for r in roll), 4),
        }
        if len(roll) == 1:
            out["planet_type"] = roll[0]["planet_type"]
            out["unit_file"] = roll[0]["unit_file"]
            pt = roll[0]["planet_type"]
            out["research_gated"] = sorted(gated.get(pt, [])) == sorted(playable)
        else:
            out["roll"] = sorted(roll, key=lambda r: r["entity"])
            out["planet_type"] = "(rolled by the game: " + ", ".join(
                sorted(r["planet_type"] for r in roll)) + ")"
        return out

    roles = {}
    for key, role in ROLES.items():
        if role["filling_name"] not in node_f:
            raise SystemExit(f"role filling {role['filling_name']} not in vanilla node_fillings")
        out_role = dict(role)
        resolved = role_entry(role["filling_name"])
        if resolved:
            out_role.update(resolved)
        roles[key] = out_role

    out = {
        "_about": {
            "generated_by": "tools/build_fillings.py",
            "game_dir": str(game),
            "decisions": "BRIEF.md §0 Resources",
            "values": "asteroid counts [min, max] = planet.non_random_* + planet.random_* in unit_file",
            "research_gated": "true = every playable faction needs research to colonize this planet type "
                              "(entities/*.player planet_types[].colonization_research_prerequisites)",
            "playable_factions": playable,
        },
        "tiers": {t: {b: entry(n) for b, n in row.items()} for t, row in TABLE.items()},
        "roles": roles,
        "home_bias_pattern": {
            "pattern": HOME_BIAS_PATTERN,
            "note": "home zones with resource_bias 'metal' are metal-leaning: non-home slot k uses "
                    "pattern[k % 2], so homes mix metal-bias and balanced planets (BRIEF §0 Home fairness)",
        },
        "verified_filling_names": sorted(node_f),
    }
    dst = ROOT / "data" / "fillings.json"
    dst.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {dst}")
    for t, row in out["tiers"].items():
        for b, e in row.items():
            print(f"  {t:2} {b:8} {e['filling_name']:30} {e['unit_file']:36} "
                  f"metal {e['metal']} crystal {e['crystal']} {'(R)' if e['research_gated'] else ''}")
    print("  roles:")
    for k, r in sorted(out["roles"].items()):
        if "metal" not in r:
            print(f"    {k:12} {r['filling_name']:22} (not a planet: no asteroids)")
            continue
        print(f"    {k:12} {r['filling_name']:22} metal {r['metal']} crystal {r['crystal']}"
              f"  expected {r['expected_metal']}/{r['expected_crystal']}")
        for x in r.get("roll", []):
            print(f"      {x['probability']*100:5.1f}%  {x['planet_type']:10} "
                  f"metal {x['metal']} crystal {x['crystal']}")
    return 0


def find_planet_types(obj) -> list[dict]:
    if isinstance(obj, dict):
        v = obj.get("planet_types")
        if isinstance(v, list) and v and isinstance(v[0], dict) and "can_ever_be_colonized" in v[0]:
            return v
        for x in obj.values():
            r = find_planet_types(x)
            if r:
                return r
    elif isinstance(obj, list):
        for x in obj:
            r = find_planet_types(x)
            if r:
                return r
    return []


if __name__ == "__main__":
    sys.exit(main())
