"""Read-only inspector for a Sins of a Solar Empire II install (STEP 1.3).

Never writes inside the game folder. Copies vanilla files into data/reference/
(gitignored) and writes one report: data/reference/inspect_report.md.

Usage (Windows, Python 3.12):
    py -3.12 tools\\inspect_vanilla.py
    py -3.12 tools\\inspect_vanilla.py --game "D:\\SteamLibrary\\steamapps\\common\\Sins2"

Stdlib only, so it runs before `pip install`.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

DEFAULT_GAME = r"C:\Program Files (x86)\Steam\steamapps\common\Sins2"
STEAM_APP_ID = "1575940"  # Sins of a Solar Empire II on Steam
ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "data" / "reference"

out_lines: list[str] = []


def say(text: str = "") -> None:
    print(text)
    out_lines.append(text)


def h(title: str) -> None:
    say()
    say("## " + title)
    say()


def load_json(path: Path):
    """Game JSON may carry a UTF-8 BOM. Returns None (and reports) on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001 - report every parse failure, keep going
        say(f"- PARSE FAIL `{path}`: {exc}")
        return None


def key_tree(obj, depth: int = 0, max_depth: int = 8) -> list[str]:
    """Merged key structure with types. List items are merged into one shape."""
    pad = "  " * depth
    lines: list[str] = []
    if depth > max_depth:
        return [pad + "..."]
    if isinstance(obj, dict):
        for k in sorted(obj):
            v = obj[k]
            lines.append(f"{pad}{k}: {type_name(v)}")
            if isinstance(v, (dict, list)):
                lines += key_tree(v, depth + 1, max_depth)
    elif isinstance(obj, list):
        dicts = [x for x in obj if isinstance(x, dict)]
        if dicts:
            merged: dict = {}
            for d in dicts:
                for k, v in d.items():
                    merged.setdefault(k, v)
            lines += key_tree(merged, depth, max_depth)
    return lines


def type_name(v) -> str:
    if isinstance(v, bool):
        return f"bool = {v}"
    if isinstance(v, (int, float)):
        return f"{type(v).__name__} = {v}"
    if isinstance(v, str):
        return f"str = {v!r}" if len(v) < 60 else "str"
    if isinstance(v, list):
        return f"list[{len(v)}]"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def walk_nodes(nodes, parent=None, depth=0):
    for n in nodes or []:
        yield n, parent, depth
        yield from walk_nodes(n.get("child_nodes"), n, depth + 1)


def strip_children(n: dict) -> dict:
    return {k: v for k, v in n.items() if k != "child_nodes"}


# ----------------------------------------------------------------------------- a
def inspect_scenarios(game: Path, max_copy: int) -> dict:
    h("a) Vanilla .scenario files")
    found = sorted(p for p in game.rglob("*.scenario") if p.is_file())
    say(f"Found {len(found)} .scenario files under the install.")
    for p in found:
        say(f"- `{p.relative_to(game)}` ({p.stat().st_size} bytes)")
    if not found:
        say("**NONE FOUND.** Scenario files may live elsewhere or be packed. Report this.")
        return {}

    dst = REF / "scenarios"
    unz = REF / "unzipped"
    dst.mkdir(parents=True, exist_ok=True)
    unz.mkdir(parents=True, exist_ok=True)
    charts: dict[str, dict] = {}
    infos: dict[str, dict] = {}
    fillings_files: dict[str, object] = {}
    zip_members: dict[str, list[str]] = {}

    # copy ALL (they are small) so we can pick the best examples; max_copy caps tree printing
    for p in found:
        shutil.copy2(p, dst / p.name)  # copy2 reads the source only
        target = unz / p.stem
        try:
            with zipfile.ZipFile(p) as z:
                zip_members[p.stem] = z.namelist()
                z.extractall(target)
        except zipfile.BadZipFile:
            say(f"- `{p.name}` is NOT a zip. First bytes: {p.read_bytes()[:40]!r}")
            continue
        gc = target / "galaxy_chart.json"
        si = target / "scenario_info.json"
        gf = target / "galaxy_chart_fillings.json"
        if gc.exists():
            charts[p.stem] = load_json(gc) or {}
        if si.exists():
            infos[p.stem] = load_json(si) or {}
        if gf.exists():
            fillings_files[p.stem] = load_json(gf)

    h("a1) Zip members per scenario")
    member_sets = collections.Counter(tuple(sorted(m)) for m in zip_members.values())
    for members, count in member_sets.most_common():
        say(f"- {count} scenario(s): {list(members)}")

    h("a2) scenario_info.json — key union and value spread")
    vals: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for info in infos.values():
        for k, v in info.items():
            vals[k][json.dumps(v, sort_keys=True)[:120]] += 1
    say(f"Keys seen (count of scenarios with key / {len(infos)}):")
    for k in sorted(vals):
        top = ", ".join(f"{v} x{c}" for v, c in vals[k].most_common(6))
        say(f"- `{k}` ({sum(vals[k].values())}): {top}")
    if infos:
        name, info = next(iter(sorted(infos.items())))
        say(f"\nFull example (`{name}`):\n```json\n{json.dumps(info, indent=2, sort_keys=True)}\n```")

    h("a3) galaxy_chart_fillings.json — distinct contents")
    distinct = collections.Counter(json.dumps(v, sort_keys=True) for v in fillings_files.values())
    for text, count in distinct.most_common(5):
        say(f"- {count} scenario(s):\n```json\n{text[:3000]}\n```")

    h("a4) galaxy_chart.json — merged key tree (all maps)")
    say("Top level:")
    top: dict = {}
    all_nodes: list[dict] = []
    all_lanes: list[dict] = []
    for c in charts.values():
        for k, v in c.items():
            top.setdefault(k, v)
        all_nodes += [strip_children(n) for n, _, _ in walk_nodes(c.get("root_nodes"))]
        all_lanes += c.get("phase_lanes", [])
    for k in sorted(top):
        say(f"- `{k}`: {type_name(top[k]) if k not in ('root_nodes', 'phase_lanes') else 'list'}")
    say("\nNode keys (union, with count of nodes using each):")
    node_keys = collections.Counter(k for n in all_nodes for k in n)
    for k, c in node_keys.most_common():
        say(f"- `{k}`: {c}")
    say("\nNode key tree (merged):\n```")
    for line in key_tree(all_nodes):
        say(line)
    say("```\nLane keys / lane types:")
    say(f"- keys: {dict(collections.Counter(k for l in all_lanes for k in l))}")
    say(f"- type values: {dict(collections.Counter(l.get('type', '<absent>') for l in all_lanes))}")

    h("a5) Per-map stats (stars, bodies per star, players, coords, depth)")
    say("| map | stars | max bodies/star | total nodes | lanes | max depth | player homes | |x|max | |y|max | skybox |")
    say("|---|---|---|---|---|---|---|---|---|---|")
    for name, c in sorted(charts.items()):
        roots = c.get("root_nodes", [])
        per_star = [sum(1 for _ in walk_nodes(r.get("child_nodes"))) for r in roots]
        nodes = list(walk_nodes(roots))
        homes = [n for n, _, _ in nodes if isinstance(n.get("ownership"), dict)
                 and "player_index" in n["ownership"]]
        xs = [abs(n["position"][0]) for n, _, _ in nodes if isinstance(n.get("position"), list) and n["position"]]
        ys = [abs(n["position"][1]) for n, _, _ in nodes if isinstance(n.get("position"), list) and len(n["position"]) > 1]
        say(f"| {name} | {len(roots)} | {max(per_star or [0])} | {len(nodes)} | {len(c.get('phase_lanes', []))} "
            f"| {max((d for _, _, d in nodes), default=0)} | {len(homes)} | {max(xs or [0]):.0f} | {max(ys or [0]):.0f} "
            f"| {c.get('skybox')!r} |")

    h("a6) Home planet nodes (player_index set) — full node, first 3 maps")
    shown = 0
    for name, c in sorted(charts.items()):
        homes = [(n, p) for n, p, _ in walk_nodes(c.get("root_nodes"))
                 if isinstance(n.get("ownership"), dict) and "player_index" in n["ownership"]]
        if not homes:
            continue
        n, p = homes[0]
        say(f"`{name}` (parent filling: {p.get('filling_name') if p else None!r}):\n```json\n"
            f"{json.dumps(strip_children(n), indent=2, sort_keys=True)}\n```")
        say(f"home fillings in this map: {dict(collections.Counter(h_.get('filling_name') for h_, _ in homes))}")
        shown += 1
        if shown >= 3:
            break

    h("a7) NPC-owned nodes (npc_filling_type / npc_filling_name) across all maps")
    npc = collections.Counter()
    for c in charts.values():
        for n, _, _ in walk_nodes(c.get("root_nodes")):
            o = n.get("ownership")
            if isinstance(o, dict) and ("npc_filling_type" in o or "npc_filling_name" in o):
                npc[(o.get("npc_filling_type"), o.get("npc_filling_name"), n.get("filling_name"))] += 1
    for (t, nm, fill), cnt in npc.most_common():
        say(f"- type={t!r} name={nm!r} on filling={fill!r}: {cnt}")
    if not npc:
        say("- none")

    h("a8) Wormhole wiring (first 2 maps that have wormhole nodes or lanes)")
    shown = 0
    for name, c in sorted(charts.items()):
        nodes = {n["id"]: (n, p) for n, p, _ in walk_nodes(c.get("root_nodes")) if "id" in n}
        wh_ids = {i for i, (n, _) in nodes.items() if "wormhole" in str(n.get("filling_name", ""))}
        wh_lanes = [l for l in c.get("phase_lanes", []) if l.get("type") == "wormhole"]
        if not wh_ids and not wh_lanes:
            continue
        say(f"### `{name}`: {len(wh_ids)} wormhole-named nodes, {len(wh_lanes)} wormhole lanes")
        for i in sorted(wh_ids)[:6]:
            n, p = nodes[i]
            say(f"- node {i} filling={n.get('filling_name')!r} parent={p.get('filling_name') if p else None!r} "
                f"(parent id {p.get('id') if p else None}); keys={sorted(strip_children(n))}")
            for l in c.get("phase_lanes", []):
                if i in (l.get("node_a"), l.get("node_b")):
                    other = l["node_b"] if l.get("node_a") == i else l["node_a"]
                    of = nodes.get(other, ({}, None))[0].get("filling_name")
                    say(f"    lane {l.get('id')} type={l.get('type', '<absent>')!r} -> {other} ({of!r})")
        shown += 1
        if shown >= 2:
            break
    if shown == 0:
        say("- no wormhole nodes or lanes in any vanilla map")

    h("a9) Star-lane wiring (lane type 'star' endpoints)")
    ends = collections.Counter()
    for c in charts.values():
        nodes = {n["id"]: n for n, _, _ in walk_nodes(c.get("root_nodes")) if "id" in n}
        roots = {r.get("id") for r in c.get("root_nodes", [])}
        for l in c.get("phase_lanes", []):
            if l.get("type") == "star":
                ends[(l["node_a"] in roots, l["node_b"] in roots)] += 1
    say(f"(a_is_root_star, b_is_root_star) -> count: {dict(ends) or 'no star lanes'}")

    h("a10) Largest map by node count — first 40 lines of key tree")
    if charts:
        big = max(charts.items(), key=lambda kv: sum(1 for _ in walk_nodes(kv[1].get("root_nodes"))))
        say(f"`{big[0]}`\n```")
        for line in key_tree(big[1])[:40]:
            say(line)
        say("```")

    # b) filling names
    h("b) Distinct filling_names across vanilla maps -> data/fillings_seen.txt")
    per_fill = collections.Counter()
    maps_with = collections.defaultdict(set)
    for name, c in charts.items():
        for n, _, _ in walk_nodes(c.get("root_nodes")):
            f = n.get("filling_name")
            per_fill[f] += 1
            maps_with[f].add(name)
    lines = [f"{f}\t{cnt}\t{len(maps_with[f])}" for f, cnt in sorted(per_fill.items(), key=lambda kv: str(kv[0]))]
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "fillings_seen.txt").write_text(
        "# filling_name\tnode_count\tmap_count  (source: vanilla install, tools/inspect_vanilla.py)\n"
        + "\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    say(f"{len(per_fill)} distinct filling_names:")
    for line in lines:
        say(f"- {line}")
    return charts


# ----------------------------------------------------------------------------- c
def find_one(game: Path, filename: str) -> list[Path]:
    return sorted(p for p in game.rglob(filename) if p.is_file())


def inspect_fillings(game: Path) -> None:
    h("c) Filling definitions (galaxy_generator.uniforms) and resources")
    hits = find_one(game, "galaxy_generator.uniforms")
    say(f"galaxy_generator.uniforms found at: {[str(p.relative_to(game)) for p in hits]}")
    if not hits:
        say("**NOT FOUND.** Report this.")
        return
    dst = REF / "uniforms"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(hits[0], dst / hits[0].name)
    gg = load_json(hits[0]) or {}
    say(f"Top-level keys: {sorted(gg)}")
    for extra in ("max_ancient_starbases", "max_capturable_units", "min_jumps_to_any_home_planet_for_loot_level",
                  "player_phase_resonance_points", "minimum_gravity_well_distances_by_hierarchy_depth"):
        if extra in gg:
            say(f"- `{extra}` = {json.dumps(gg[extra])}")

    # schema names base_fillings / combined_fillings; the 2026-09 vanilla build uses a single `fillings`
    merged: dict[str, dict[str, dict]] = collections.defaultdict(dict)
    for section in ("fillings", "base_fillings", "combined_fillings"):
        block = gg.get(section) or {}
        say(f"\n`{section}` lists: " + ", ".join(f"{k}[{len(v)}]" for k, v in block.items() if isinstance(v, list)))
        for kind, items in block.items():
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict) and "name" in it:
                        merged[kind][it["name"]] = it.get("filling", {})

    node_f = merged.get("node_fillings", {})
    rand_f = merged.get("random_fixture_fillings", {})
    fix_f = merged.get("fixture_fillings", {})
    npc_f = merged.get("npc_fillings", {})
    worm_f = merged.get("wormhole_fillings", {})

    def resolve_fixtures(name: str | None, seen=None) -> list[str]:
        """random_fixture_filling -> weighted items -> fixture names (recursive)."""
        if not name:
            return []
        seen = seen or set()
        if name in seen:
            return []
        seen.add(name)
        if name in fix_f:
            return [name]
        out = []
        for item in (rand_f.get(name, {}) or {}).get("items", []):
            out += resolve_fixtures(item.get("name"), seen)
        return out

    def asteroids(fx: dict, key: str) -> str:
        tiers = (fx.get(key) or {}).get("tiers", [])
        return ";".join(f"t{t.get('tier')}:{t.get('count')}" for t in tiers) or "-"

    seen_names = set()
    seen_path = ROOT / "data" / "fillings_seen.txt"
    if seen_path.exists():
        seen_names = {ln.split("\t")[0] for ln in seen_path.read_text(encoding="utf-8").splitlines()
                      if ln and not ln.startswith("#")}

    say("\n### node_fillings -> fixtures -> resources")
    say("| node filling_name | in vanilla maps | home? | primary random fixture | fixtures (resolved) | "
        "entity | metal asteroids | crystal asteroids | required bonuses |")
    say("|---|---|---|---|---|---|---|---|---|")
    for nm in sorted(node_f):
        f = node_f[nm]
        prim = f.get("primary_random_fixture_filling_name") or f.get("primary_random_fixture_with_moon_filling_name")
        fixtures = resolve_fixtures(prim)
        ent = sorted({str(fix_f[x].get("entity_definition")) for x in fixtures})
        metal = sorted({asteroids(fix_f[x], "random_metal_asteroids") for x in fixtures})
        crys = sorted({asteroids(fix_f[x], "random_crystal_asteroids") for x in fixtures})
        bon = sorted({json.dumps(fix_f[x].get("required_planet_bonuses", [])) for x in fixtures})
        say(f"| {nm} | {'yes' if nm in seen_names else ''} | {f.get('is_primary_fixture_player_home_planet', '')} "
            f"| {prim} | {', '.join(fixtures[:4])}{'…' if len(fixtures) > 4 else ''} | {', '.join(ent)[:80]} "
            f"| {' / '.join(metal)} | {' / '.join(crys)} | {' / '.join(bon)[:60]} |")

    say("\n### Raw example of one node_filling and one fixture_filling")
    for d in (node_f, fix_f):
        if d:
            k = sorted(d)[0]
            say(f"`{k}`:\n```json\n{json.dumps(d[k], indent=2, sort_keys=True)[:2500]}\n```")

    say("\n### npc_fillings (pirates / militia / guardians)")
    for nm in sorted(npc_f):
        say(f"- `{nm}`: {json.dumps(npc_f[nm], sort_keys=True)}")

    say("\n### wormhole_fillings")
    for nm in sorted(worm_f):
        say(f"- `{nm}`: {json.dumps(worm_f[nm], sort_keys=True)[:300]}")

    # entity files: what makes a planet ownable / its type
    say("\n### Planet entity files for fixtures used by home + ownable candidates")
    ent_names = set()
    for nm in ("player_home_planet",):
        if nm in node_f:
            for x in resolve_fixtures(node_f[nm].get("primary_random_fixture_filling_name")):
                ent_names.add(fix_f[x].get("entity_definition"))
    for nm, f in node_f.items():
        if any(t in nm for t in ("terran", "desert", "ferrous", "city")):
            for x in resolve_fixtures(f.get("primary_random_fixture_filling_name")):
                ent_names.add(fix_f[x].get("entity_definition"))
    ent_names.discard(None)
    for en in sorted(ent_names)[:12]:
        paths = find_one(game, f"{en}.unit") + find_one(game, f"{en}.entity")
        if not paths:
            say(f"- `{en}`: file not found (looked for {en}.unit / {en}.entity)")
            continue
        data = load_json(paths[0]) or {}
        planet = data.get("planet", {}) if isinstance(data, dict) else {}
        say(f"- `{en}` ({paths[0].relative_to(game)}): top keys={sorted(data)[:25]}")
        if planet:
            say(f"    planet keys: {sorted(planet)}")
            for k in sorted(planet):
                if any(t in k for t in ("type", "colon", "home", "own", "resource", "asteroid", "bonus")):
                    say(f"    planet.{k} = {json.dumps(planet[k])[:200]}")

    for fname in ("random_map_generator.uniforms", "scenario.uniforms"):
        h(f"c2) {fname}")
        hits2 = find_one(game, fname)
        say(f"found at: {[str(p.relative_to(game)) for p in hits2]}")
        if hits2:
            shutil.copy2(hits2[0], dst / hits2[0].name)
            data = load_json(hits2[0])
            say(f"```json\n{json.dumps(data, indent=2, sort_keys=True)[:6000]}\n```")


# ----------------------------------------------------------------------------- d
def inspect_localized(game: Path, charts: dict) -> None:
    h("d) localized_text structure")
    cands = sorted(p for p in game.rglob("en.localized_text*") if p.is_file())
    say(f"candidates: {[str(p.relative_to(game)) for p in cands]}")
    for p in cands[:2]:
        raw = p.read_bytes()
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        say(f"### `{p.relative_to(game)}` ({len(raw)} bytes), BOM={has_bom}")
        say(f"first 400 bytes:\n```\n{raw[:400].decode('utf-8', 'replace')}\n```")
        try:
            data = json.loads(raw.decode("utf-8-sig"))
            say(f"JSON top-level type: {type(data).__name__}")
            if isinstance(data, dict):
                say(f"top keys (first 10): {list(data)[:10]}")
                for k, v in list(data.items())[:3]:
                    say(f"- {k!r}: {json.dumps(v)[:300]}")
        except Exception as exc:  # noqa: BLE001
            say(f"not JSON: {exc}")
        # where do vanilla scenario_info name keys live?
        text = raw.decode("utf-8-sig", "replace")
        for probe in ("scenario_options_view_resources_high", "scenario_options_view_map_type"):
            idx = text.find(probe)
            say(f"probe {probe!r}: {'found: ' + repr(text[max(0, idx - 60):idx + 120]) if idx >= 0 else 'not found'}")


# ----------------------------------------------------------------------------- e
def inspect_mods() -> None:
    h("e) Installed mods: .mod_meta_data (compatibility_version)")
    places = []
    la = os.environ.get("LOCALAPPDATA")
    if la:
        places.append(Path(la) / "sins2" / "mods")
        dis = Path(la) / "sins2" / "drop_in_scenarios"
        say(f"drop_in_scenarios exists: {dis.exists()} ({dis})")
    for steam in (Path(r"C:\Program Files (x86)\Steam"),):
        places.append(steam / "steamapps" / "workshop" / "content" / STEAM_APP_ID)
    found = 0
    for base in places:
        say(f"- looking in `{base}` (exists={base.exists()})")
        if not base.exists():
            continue
        for meta in sorted(base.glob("*/.mod_meta_data"))[:5]:
            data = load_json(meta)
            say(f"  - `{meta.parent.name}`: {json.dumps(data, sort_keys=True)[:600]}")
            say(f"    folder contents: {sorted(p.name for p in meta.parent.iterdir())[:20]}")
            found += 1
    if not found:
        say("No installed mods found. compatibility_version stays UNVERIFIED (doc says 2).")


# ----------------------------------------------------------------------------- f
def inspect_rifts(game: Path) -> None:
    h("f) Rift / Harbinger names (file names and filling names containing 'rift')")
    files = sorted(str(p.relative_to(game)) for p in game.rglob("*rift*") if p.is_file())
    say(f"files with 'rift' in the name: {len(files)}")
    for f in files[:40]:
        say(f"- {f}")
    gg = find_one(game, "galaxy_generator.uniforms")
    if gg:
        text = gg[0].read_text(encoding="utf-8-sig", errors="replace")
        names = sorted({tok.strip('"') for tok in text.replace(",", " ").split() if "rift" in tok.lower()})
        say(f"tokens with 'rift' in galaxy_generator.uniforms: {names[:40]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", default=os.environ.get("SINS2_GAME_DIR", DEFAULT_GAME))
    ap.add_argument("--max-copy", type=int, default=999)
    args = ap.parse_args()
    game = Path(args.game)
    if not game.exists():
        print(f"Game folder not found: {game}\nPass --game \"<path to Sins2>\".", file=sys.stderr)
        return 2
    REF.mkdir(parents=True, exist_ok=True)
    say("# Vanilla inspection report")
    say(f"game dir: `{game}`")
    for vf in ("version.txt", "build_version.txt"):
        for p in find_one(game, vf)[:1]:
            say(f"{vf}: {p.read_text(errors='replace').strip()[:200]}")
    charts = inspect_scenarios(game, args.max_copy)
    inspect_fillings(game)
    inspect_localized(game, charts)
    inspect_mods()
    inspect_rifts(game)
    report = REF / "inspect_report.md"
    report.write_text("\n".join(out_lines) + "\n", encoding="utf-8", newline="\n")
    print(f"\nREPORT WRITTEN: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
