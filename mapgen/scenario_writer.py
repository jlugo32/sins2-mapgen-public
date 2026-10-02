"""CompiledMap → .scenario zip bytes (FINDINGS §6.1/§6.2/§7). Byte-deterministic."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from .compiler import CompiledMap, to_galaxy_chart
from .params import MapParams

ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def dumps(obj) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def text_keys(name: str) -> tuple[str, str]:
    return f"scenario.{name}.name", f"scenario.{name}.desc"


def scenario_info(m: CompiledMap, p: MapParams) -> dict:
    """Key set copied from vanilla hand-made maps (public_face_off, public_scorched_space)."""
    s = m.spec
    if p.inline_names:
        name, desc = ":" + s.meta.display_name, ":" + s.meta.description
    else:
        name, desc = text_keys(s.meta.name)
    planets = len(m.planets())
    return {
        "version": 1,
        "name": name,
        "description": desc,
        "desired_player_slots_configuration": {"player_count": s.meta.players, "team_count": s.meta.teams},
        "planet_counts": [planets, planets],
        "star_counts": [1, 1],
        "has_wormholes": bool(m.fixtures()),
        "has_npcs": any(n.role == "pirate" for n in m.nodes),
        "resources": p.resources_label,
        "map_type": "scenario_options_view_map_type_custom",
        "can_gravity_wells_move": False,
    }


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o644 << 16
            z.writestr(info, members[name], compresslevel=9)
    return buf.getvalue()


MEMBERS = ("galaxy_chart.json", "galaxy_chart_fillings.json", "scenario_info.json", "picture.png")


def unpack_scenario(scenario: Path, dest: Path) -> list[str]:
    """Extract a .scenario zip into a folder Solar Forge can open (File -> open scenario folder).

    Solar Forge has no zip handling - the folder path is the one its UI advertises (FINDINGS §9).
    """
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(scenario) as z:
        names = sorted(z.namelist())
        z.extractall(dest)
    return names


def pack_scenario(folder: Path, scenario: Path) -> list[str]:
    """Zip a scenario folder back into a .scenario, byte-for-byte deterministically.

    Member bytes are taken exactly as they sit on disk - whatever Solar Forge wrote is what the
    game gets - but the zip envelope uses this project's fixed timestamps and sorted order, so
    repacking the same folder twice gives the same bytes.
    """
    members = {f.name: f.read_bytes() for f in sorted(folder.iterdir()) if f.is_file()}
    missing = [n for n in ("galaxy_chart.json", "scenario_info.json") if n not in members]
    if missing:
        raise ScenarioError(f"{folder} is not a scenario folder: missing {', '.join(missing)}")
    scenario.parent.mkdir(parents=True, exist_ok=True)
    scenario.write_bytes(zip_bytes(members))
    return sorted(members)


class ScenarioError(Exception):
    pass


def scenario_members(m: CompiledMap, p: MapParams, picture_png: bytes) -> dict[str, bytes]:
    return {
        "scenario_info.json": dumps(scenario_info(m, p)),
        "galaxy_chart.json": dumps(to_galaxy_chart(m)),
        "galaxy_chart_fillings.json": dumps({"version": 1}),
        "picture.png": picture_png,
    }
