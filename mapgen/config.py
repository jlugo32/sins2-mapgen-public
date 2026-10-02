"""config.toml loader. Limits live here, never in code (BRIEF §0 Limits)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import ROOT


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Limits:
    warn_bodies_per_star: int
    max_bodies_per_star: int
    max_stars: int
    max_region_hop_spread: int = 2


@dataclass(frozen=True)
class Config:
    game_dir: Path
    schema_dir: Path
    mods_dir: Path
    limits: Limits


def load_config(path: Path | None = None) -> Config:
    path = path or ROOT / "config.toml"
    if not path.exists():
        raise ConfigError(f"{path} not found. Copy config.example.toml to config.toml and edit the paths.")
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    try:
        lim = raw["limits"]
        limits = Limits(int(lim["warn_bodies_per_star"]), int(lim["max_bodies_per_star"]),
                        int(lim["max_stars"]),
                        # optional: config.toml files written before 2026-09-24 do not have it
                        int(lim.get("max_region_hop_spread", 2)))
        return Config(
            game_dir=Path(raw["game_dir"]),
            schema_dir=Path(raw["schema_dir"]),
            mods_dir=Path(os.path.expandvars(raw["mods_dir"])),
            limits=limits,
        )
    except KeyError as exc:
        raise ConfigError(f"{path}: missing key {exc}. Compare with config.example.toml.") from exc
