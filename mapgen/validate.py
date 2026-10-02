"""Validate a built mod folder against the official schemas and vanilla key sets (BRIEF S2).

Official schemas declare draft-07 but use unevaluatedProperties, which draft-07 validators ignore, so we
use Draft202012Validator explicitly and prove it bites with a bogus-field self-test on every run.
"""
from __future__ import annotations

import copy
import json
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from .config import Config


class ValidatorBroken(Exception):
    pass


@dataclass
class Problem:
    file: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.file} -> {self.path or '<root>'} -> {self.message}"


def _schema(cfg: Config, name: str) -> dict:
    p = cfg.schema_dir / name
    if not p.exists():
        raise FileNotFoundError(f"official schema missing: {p} (check schema_dir in config.toml)")
    return json.loads(p.read_text(encoding="utf-8"))


def _errors(validator: Draft202012Validator, data, file: str) -> list[Problem]:
    return [Problem(file, "/".join(str(x) for x in e.absolute_path), e.message)
            for e in sorted(validator.iter_errors(data), key=lambda e: [str(x) for x in e.absolute_path])]


def self_test(chart_validator: Draft202012Validator, chart: dict) -> None:
    """Inject bogus_field on a node and on a lane; both must fail or validation is meaningless."""
    for where in ("node", "lane"):
        bad = copy.deepcopy(chart)
        if where == "node":
            target = (bad["root_nodes"][0].get("child_nodes") or bad["root_nodes"])[0]
        else:
            if not bad["phase_lanes"]:
                continue
            target = bad["phase_lanes"][0]
        target["bogus_field"] = 1
        if chart_validator.is_valid(bad):
            raise ValidatorBroken(f"schema validator accepted bogus_field on a {where}; aborting")


@lru_cache(maxsize=4)
def vanilla_keys(game_dir: Path) -> dict[str, frozenset]:
    """Union of top-level keys per member across vanilla .scenario zips."""
    keys: dict[str, set] = {"scenario_info.json": set(), "galaxy_chart_fillings.json": set()}
    files = sorted((game_dir / "scenarios").glob("*.scenario"))
    if not files:
        raise FileNotFoundError(f"no vanilla .scenario files under {game_dir / 'scenarios'}")
    for f in files:
        with zipfile.ZipFile(f) as z:
            for member in keys:
                if member in z.namelist():
                    keys[member] |= set(json.loads(z.read(member).decode("utf-8-sig")))
    return {k: frozenset(v) for k, v in keys.items()}


SCENARIO_MEMBERS = {"scenario_info.json", "galaxy_chart.json", "galaxy_chart_fillings.json", "picture.png"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def read_scenario(path: Path) -> dict[str, bytes]:
    """Members of a .scenario zip, or of an unpacked scenario folder (what Solar Forge saves)."""
    if path.is_dir():
        return {f.name: f.read_bytes() for f in path.iterdir() if f.is_file()}
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def check_scenario_members(members: dict[str, bytes], label: str, chart_v: Draft202012Validator,
                           vk: dict[str, frozenset], strict_members: bool = True) -> list[Problem]:
    probs: list[Problem] = []
    names = set(members)
    if strict_members and names != SCENARIO_MEMBERS:
        probs.append(Problem(label, "", f"members {sorted(names)} != {sorted(SCENARIO_MEMBERS)}"))
    missing = SCENARIO_MEMBERS - names
    if missing:
        probs.append(Problem(label, "", f"missing {sorted(missing)}"))
        return probs
    chart = json.loads(members["galaxy_chart.json"])
    self_test(chart_v, chart)
    probs += _errors(chart_v, chart, f"{label}:galaxy_chart.json")
    for member in ("scenario_info.json", "galaxy_chart_fillings.json"):
        extra = set(json.loads(members[member])) - vk[member]
        if extra:
            probs.append(Problem(f"{label}:{member}", "", f"keys not seen in vanilla: {sorted(extra)}"))
    png = members["picture.png"]
    if (png[:8] != PNG_SIGNATURE or int.from_bytes(png[16:20], "big") != 512
            or int.from_bytes(png[20:24], "big") != 512):
        probs.append(Problem(f"{label}:picture.png", "", "must be a 512x512 PNG"))
    return probs


def validate_scenario(path: Path, cfg: Config, strict_members: bool = True) -> list[Problem]:
    """Validate one .scenario file or unpacked folder on its own (e.g. after a Solar Forge round-trip)."""
    chart_v = Draft202012Validator(_schema(cfg, "galaxy-chart-schema.json"))
    return check_scenario_members(read_scenario(path), path.name, chart_v,
                                  vanilla_keys(cfg.game_dir), strict_members)


def validate_mod(mod_dir: Path, cfg: Config) -> list[Problem]:
    probs: list[Problem] = []
    chart_v = Draft202012Validator(_schema(cfg, "galaxy-chart-schema.json"))
    uni_v = Draft202012Validator(_schema(cfg, "scenario-uniforms-schema.json"))
    vk = vanilla_keys(cfg.game_dir)

    meta_p = mod_dir / ".mod_meta_data"
    try:
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        if meta.get("compatibility_version") != 2:
            probs.append(Problem(".mod_meta_data", "compatibility_version", "must be 2"))
    except (OSError, ValueError) as exc:
        probs.append(Problem(".mod_meta_data", "", f"unreadable: {exc}"))

    uni_p = mod_dir / "uniforms" / "scenario.uniforms"
    uniforms = json.loads(uni_p.read_text(encoding="utf-8"))
    probs += _errors(uni_v, uniforms, "uniforms/scenario.uniforms")

    try:
        json.loads((mod_dir / "localized_text" / "en.localized_text").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        probs.append(Problem("localized_text/en.localized_text", "", f"not flat JSON: {exc}"))

    scenarios = sorted((mod_dir / "scenarios").glob("*.scenario"))
    listed = set(uniforms.get("scenarios", []))
    for s in scenarios:
        rel = f"scenarios/{s.name}"
        if s.stem not in listed:
            probs.append(Problem("uniforms/scenario.uniforms", "scenarios", f"{s.stem} not listed"))
        probs += check_scenario_members(read_scenario(s), rel, chart_v, vk)
    for name in listed - {s.stem for s in scenarios}:
        probs.append(Problem("uniforms/scenario.uniforms", "scenarios", f"{name} listed but no .scenario file"))
    return probs
