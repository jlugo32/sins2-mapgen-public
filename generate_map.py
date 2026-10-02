"""sins2-mapgen CLI: build | ai | validate | install | inspect | unpack | pack."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from rich.console import Console

from mapgen import ROOT, rules
from mapgen.config import ConfigError, load_config
from mapgen.mod_writer import InstallError, install
from mapgen.params import MapParams
from mapgen.pipeline import build, summary
from mapgen.spec import SpecError, load as load_spec
from mapgen.templates import TEMPLATES, TemplateError
from mapgen.scenario_writer import ScenarioError, pack_scenario, unpack_scenario
from mapgen.validate import ValidatorBroken, validate_mod, validate_scenario

console = Console(width=150)
OUT = ROOT / "out"


def ints(text: str) -> list[int]:
    return [int(x) for x in text.split(",") if x.strip()]


def cmd_build(a) -> int:
    cfg = load_config()
    params = MapParams.from_file(Path(a.params)) if a.params else MapParams()
    for key in ("players", "planets", "seed", "name", "display_name", "convoy_skip", "inline_names"):
        v = getattr(a, key)
        if v is not None and v is not False:
            setattr(params, key, v)
    if a.core_access:
        params.core_access = ints(a.core_access)
    if a.spec:
        spec = load_spec(Path(a.spec))
        params.name, params.display_name = spec.meta.name, spec.meta.display_name
    else:
        spec = TEMPLATES[a.template](params, cfg.limits.max_bodies_per_star)
    res = build(spec, params, cfg, OUT, preview_only=a.preview_only)
    summary(res.compiled, console)
    for v in res.violations:
        style = "yellow" if v.severity == "warning" else "red"
        ids = f" nodes {v.node_ids}" if v.node_ids else ""
        console.print(f"[{style}]{v.severity.upper()} {v.code}[/]: {v.message}{ids}\n    hint: {v.hint}")
    if rules.errors(res.violations):
        console.print("[red]Rule violations: no output written.[/]")
        return 1
    for p in res.problems:
        console.print(f"[red]INVALID[/] {p}")
    if res.problems:
        console.print("[red]Validation failed: no mod written.[/]")
        return 1
    console.print(f"preview: {res.preview}\nspec:    {res.spec_path}")
    if res.mod_dir:
        console.print(f"[green]mod:     {res.mod_dir}[/]  (schemas OK, validator self-test OK, vanilla key diff OK)")
        if a.install:
            console.print(f"installed: {install(res.mod_dir, cfg.mods_dir)}")
    return 0


def cmd_validate(a) -> int:
    """Validates a mod folder, a .scenario file, or an unpacked scenario folder (Solar Forge output)."""
    cfg = load_config()
    target = Path(a.mod_dir)
    if target.is_file() or (target.is_dir() and (target / "galaxy_chart.json").exists()):
        probs = validate_scenario(target, cfg, strict_members=not a.loose_members)
    else:
        probs = validate_mod(target, cfg)
    for p in probs:
        console.print(f"[red]INVALID[/] {p}")
    if not probs:
        console.print("[green]valid[/] (validator self-test passed)")
    return 1 if probs else 0


def only_scenario(mod: Path) -> Path:
    """The single .scenario inside a mod folder, or the path itself if it already is one."""
    if mod.is_file():
        return mod
    found = sorted((mod / "scenarios").glob("*.scenario"))
    if len(found) != 1:
        raise ScenarioError(f"expected exactly one .scenario under {mod / 'scenarios'}, found {len(found)}")
    return found[0]


def cmd_unpack(a) -> int:
    """Extract a mod's .scenario into a folder Solar Forge can open."""
    src = only_scenario(Path(a.mod_dir))
    dest = Path(a.dest) if a.dest else OUT / "solarforge_test" / src.stem
    names = unpack_scenario(src, dest)
    console.print(f"unpacked {src} -> [bold]{dest}[/]")
    for n in names:
        console.print(f"  {n}")
    console.print("")
    console.print("Solar Forge: File -> open scenario [bold]folder[/], then pick that folder.")
    console.print(f"When you have saved, run:  generate_map.py pack {dest} --into {a.mod_dir} --install")
    return 0


def cmd_pack(a) -> int:
    """Zip an edited scenario folder back into a mod, validate it, and optionally install."""
    cfg = load_config()
    folder = Path(a.folder)
    mod = Path(a.into)
    target = only_scenario(mod)
    probs = validate_scenario(folder, cfg, strict_members=not a.loose_members)
    if probs:
        for pr in probs:
            console.print(f"[red]INVALID[/] {pr}")
        console.print("[red]refusing to pack[/] - fix the folder or re-export it from Solar Forge")
        return 1
    if target.exists() and not a.no_backup:
        backup = target.with_suffix(".scenario.bak")
        backup.write_bytes(target.read_bytes())
        console.print(f"previous scenario kept at {backup}")
    names = pack_scenario(folder, target)
    console.print(f"packed {folder} -> [bold]{target}[/] ({', '.join(names)})")
    probs = validate_mod(mod, cfg)
    for pr in probs:
        console.print(f"[red]INVALID[/] {pr}")
    if probs:
        return 1
    console.print("[green]valid[/] (validator self-test passed)")
    if a.install:
        console.print(f"installed: {install(mod, cfg.mods_dir)}")
        console.print("In game: Modding -> Local -> disable -> Apply Changes -> enable -> Apply Changes.")
    return 0


def cmd_install(a) -> int:
    cfg = load_config()
    mod = Path(a.mod_dir)
    probs = validate_mod(mod, cfg)
    if probs:
        for p in probs:
            console.print(f"[red]INVALID[/] {p}")
        return 1
    console.print(f"installed: {install(mod, cfg.mods_dir)}")
    return 0


def cmd_inspect(a) -> int:
    """With a path: serve the read-only map inspector. Without: re-run the vanilla game-files inspector."""
    cfg = load_config()
    if not a.target:
        return subprocess.call([sys.executable, str(ROOT / "tools" / "inspect_vanilla.py"),
                                "--game", str(cfg.game_dir)])
    from mapgen.inspector import build_page, serve
    html, data = build_page(Path(a.target), cfg)
    console.print(f"{data['meta']['display_name']}: {data['meta']['planets']} planets, "
                  f"{len(data['findings'])} rule finding(s)")
    if a.write:
        out = Path(a.write)
        out.write_text(html, encoding="utf-8", newline="\n")
        console.print(f"wrote {out}")
        return 0
    serve(html, port=a.port, open_browser=not a.no_open)
    return 0


def cmd_setup(a) -> int:
    from mapgen.ai.setup_key import run
    return run(from_stdin=a.from_stdin)


def cmd_ai(a) -> int:
    from mapgen.ai import describe
    from mapgen.ai.chat import Chat
    from mapgen.ai.client import POLICY, SESSION, AIError, find_key, KEY_HELP
    from mapgen.ai.repair import repair
    cfg = load_config()
    params = MapParams.from_file(Path(a.params)) if a.params else MapParams()
    if not find_key():
        console.print(f"[red]error:[/] {KEY_HELP}")
        return 2
    POLICY.max_cost = a.max_cost
    POLICY.assume_yes = a.yes
    rounds = max(0, min(3, a.max_repair_rounds))
    try:
        if a.chat:
            return Chat(cfg=cfg, params=params, console=console, max_rounds=rounds,
                        auto_open=a.open).run()
        request = " ".join(a.rest).strip()
        if not request:
            console.print("[yellow]give a description, or use --chat[/]")
            return 2
        res = repair(request, cfg.limits, params, seed=a.seed, max_rounds=rounds)
        for line in res.summary_lines():
            console.print(line, markup=False)
        for line in res.cost_lines():
            console.print(f"[dim]{line}[/]")
        if res.asked:
            console.print("[bold]the model needs to know:[/]")
            for q in res.questions:
                console.print(f"  ? {q}")
            return 3
        if not res.ok:
            console.print(f"[red]still failing after {len(res.rounds)} round(s); nothing written.[/]")
            for v in rules.errors(res.violations):
                console.print(f"[red]{v.code}[/]: {v.message}\n    hint: {v.hint}")
            console.print("options: rephrase the request, relax the constraint that keeps breaking, "
                          "or build the closest spec by hand with --spec after saving it.")
            return 1
        describe.report(res.compiled, console, request=request, assumptions=res.assumptions)
        if a.dry_run:
            console.print("[yellow]--dry-run: nothing written[/]")
            return 0
        from mapgen.pipeline import build as build_mod
        out = build_mod(res.spec, params, cfg, OUT)
        res.spec.save(OUT / f"{res.spec.meta.name}.mapspec.json")
        if out.mod_dir:
            console.print(f"[green]mod: {out.mod_dir}[/]\npreview: {out.preview}")
        console.print(f"[dim]{SESSION.line()}[/]")
        return 0 if out.mod_dir else 1
    except AIError as exc:
        console.print(f"[red]error:[/] {exc}")
        return 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="generate_map.py", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build a map from a template or a MapSpec")
    src = b.add_mutually_exclusive_group()
    src.add_argument("--template", choices=sorted(TEMPLATES), default="ring")
    src.add_argument("--spec", help="MapSpec JSON file")
    b.add_argument("--params", help="MapParams JSON file (template knobs)")
    b.add_argument("--players", type=int)
    b.add_argument("--planets", type=int)
    b.add_argument("--seed", type=int)
    b.add_argument("--name")
    b.add_argument("--display-name", dest="display_name")
    b.add_argument("--convoy-skip", dest="convoy_skip", type=int)
    b.add_argument("--core-access", dest="core_access", help="comma list of region indexes, e.g. 0,3,7")
    b.add_argument("--inline-names", dest="inline_names", action="store_true")
    b.add_argument("--preview-only", dest="preview_only", action="store_true")
    b.add_argument("--install", action="store_true")
    b.add_argument("--open", action="store_true", help="open the preview when the build finishes")
    b.set_defaults(func=cmd_build)
    v = sub.add_parser("validate", help="validate a mod folder, a .scenario file, or an unpacked scenario folder")
    v.add_argument("mod_dir", metavar="PATH")
    v.add_argument("--loose-members", dest="loose_members", action="store_true",
                   help="allow extra files beside the four scenario members (e.g. editor leftovers)")
    v.set_defaults(func=cmd_validate)
    up = sub.add_parser("unpack", help="extract a mod's .scenario into a folder Solar Forge can open")
    up.add_argument("mod_dir", help="a built mod folder, or a .scenario file")
    up.add_argument("--dest", help="where to unpack (default out/solarforge_test/<name>)")
    up.set_defaults(func=cmd_unpack)
    pk = sub.add_parser("pack", help="zip an edited scenario folder back into a mod (Solar Forge round-trip)")
    pk.add_argument("folder", help="the scenario folder Solar Forge saved")
    pk.add_argument("--into", required=True, help="the mod folder whose .scenario is replaced")
    pk.add_argument("--install", action="store_true", help="also copy the mod into the game's mods folder")
    pk.add_argument("--no-backup", action="store_true", help="do not keep the previous .scenario as .bak")
    pk.add_argument("--loose-members", action="store_true", help="allow extra files in the folder")
    pk.set_defaults(func=cmd_pack)
    i = sub.add_parser("install", help="copy a built mod into %%LOCALAPPDATA%%\\sins2\\mods")
    i.add_argument("mod_dir")
    i.set_defaults(func=cmd_install)
    ins = sub.add_parser("inspect", help="serve the read-only map inspector; with no PATH, re-run the "
                                        "vanilla game-files inspector")
    ins.add_argument("target", nargs="?", metavar="PATH",
                     help="a .mapspec.json, or a built mod folder whose spec sits beside it")
    ins.add_argument("--port", type=int, default=8765)
    ins.add_argument("--no-open", dest="no_open", action="store_true", help="do not open a browser")
    ins.add_argument("--write", metavar="FILE", help="write the page to a file instead of serving it")
    ins.set_defaults(func=cmd_inspect)
    ai = sub.add_parser("ai", help="natural language -> MapSpec -> mod")
    ai.add_argument("rest", nargs="*", help="the map description")
    ai.add_argument("--chat", action="store_true", help="REPL that edits the current spec")
    ai.add_argument("--seed", type=int)
    ai.add_argument("--params", help="MapParams JSON file")
    ai.add_argument("--dry-run", dest="dry_run", action="store_true", help="describe, write nothing")
    ai.add_argument("--max-cost", dest="max_cost", type=float, default=1.00,
                    help="stop the session before it passes this many USD (default 1.00)")
    ai.add_argument("--yes", "-y", action="store_true", help="skip the per-call cost confirmation")
    ai.add_argument("--open", action="store_true", help="open each new preview automatically")
    ai.add_argument("--max-repair-rounds", dest="max_repair_rounds", type=int, default=3,
                    help="0-3 repair rounds after the first attempt (default 3)")
    ai.set_defaults(func=cmd_ai)
    st = sub.add_parser("setup", help="store an Anthropic API key in .env (only for the `ai` path)")
    st.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                    help="read the key from stdin instead of a hidden prompt (for scripts)")
    st.set_defaults(func=cmd_setup)
    a = ap.parse_args(argv)
    try:
        return a.func(a)
    except (ConfigError, SpecError, TemplateError, InstallError, ValidatorBroken, FileNotFoundError) as exc:
        console.print(f"[red]error:[/] {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
