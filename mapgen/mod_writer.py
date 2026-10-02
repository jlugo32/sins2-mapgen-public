"""Write the mod folder (BRIEF §2) and install it into the game's mods folder."""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from .compiler import CompiledMap
from .params import MapParams
from .scenario_writer import dumps, scenario_members, text_keys, zip_bytes

TOOL_MARK = "sins2-mapgen"


def mod_files(m: CompiledMap, p: MapParams, picture_png: bytes) -> dict[str, bytes]:
    """Relative path → bytes for the whole mod. Status of .mod_meta_data: FINDINGS §3/§7 (unverified logos)."""
    name = m.spec.meta.name
    loc = {} if p.inline_names else dict(zip(text_keys(name), (m.spec.meta.display_name, m.spec.meta.description)))
    return {
        ".mod_meta_data": dumps({
            "compatibility_version": 2,
            "display_name": m.spec.meta.display_name,
            "display_version": p.display_version,
            "short_description": m.spec.meta.description,
            "logos": {"large_logo": "picture.png", "small_logo": "picture.png"},
        }),
        "picture.png": picture_png,
        f"scenarios/{name}.scenario": zip_bytes(scenario_members(m, p, picture_png)),
        "uniforms/scenario.uniforms": dumps({
            "dlc_multiplayer_scenarios": [],
            "dlc_scenarios": [],
            "fake_server_scenarios": [],
            "scenarios": [name],
        }),
        "localized_text/en.localized_text": dumps(loc),
    }


def write_tree(root: Path, files: dict[str, bytes]) -> None:
    if root.exists():
        shutil.rmtree(root)
    for rel, data in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)


# ----------------------------------------------------------------------------- install
def _registry_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / TOOL_MARK
    return base / "installed.json"


def _registry() -> dict:
    p = _registry_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


class InstallError(Exception):
    pass


def install(mod_dir: Path, mods_root: Path) -> Path:
    """Copy out/<mod> to <mods_root>/<mod>. Refuse to touch folders this tool did not create; back up ours.

    Ownership is tracked in %LOCALAPPDATA%/sins2-mapgen/installed.json, outside the game's folders, so no
    extra file is placed inside the mod.
    """
    target = mods_root / mod_dir.name
    reg = _registry()
    if target.exists():
        if str(target) not in reg:
            raise InstallError(f"{target} exists and was not created by {TOOL_MARK}; refusing to overwrite")
        backup = _registry_path().parent / "backups" / f"{mod_dir.name}-{time.strftime('%Y%m%d-%H%M%S')}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(backup))
        print(f"backed up previous install to {backup}")
    mods_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(mod_dir, target)
    reg[str(target)] = {"source": str(mod_dir), "installed": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _registry_path().parent.mkdir(parents=True, exist_ok=True)
    _registry_path().write_text(json.dumps(reg, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return target
