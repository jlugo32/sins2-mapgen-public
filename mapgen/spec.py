"""MapSpec: our JSON IR (dataclasses + strict JSON Schema at schemas/mapspec.schema.json)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator

from . import ROOT

SCHEMA_PATH = ROOT / "schemas" / "mapspec.schema.json"


class SpecError(Exception):
    pass


@dataclass
class Placement:
    kind: str
    slot: int | None = None
    zones: list[str] | None = None
    cluster: str | None = None
    band: int | None = None


@dataclass
class Zone:
    id: str
    kind: str
    planet_count: int
    size_tiers: list[str]
    resource_bias: str
    internal_links: str
    placement: Placement
    gated: bool = False
    chokepoints: int = 0
    loot: str = "none"
    npc: str = "none"
    owner_player: int | None = None
    slot_biases: list[str] | None = None
    chokepoint_role: str | None = None


@dataclass
class Link:
    from_zone: str
    to_zone: str
    lane: str
    via_contested_planets: int = 0
    chokepoint: bool = False


@dataclass
class Meta:
    name: str
    display_name: str
    description: str
    players: int
    teams: int
    seed: int


@dataclass
class Layout:
    shape: str
    radius_scale: float = 1.0
    band_radii: list[float] | None = None
    band_offsets: list[float] | None = None


@dataclass
class Constraints:
    total_planets: int
    max_bodies_per_star: int
    symmetric: bool = True
    notes: list[str] = field(default_factory=list)


@dataclass
class MapSpec:
    meta: Meta
    layout: Layout
    zones: list[Zone]
    links: list[Link]
    constraints: Constraints
    features: dict | None = None

    def zone(self, zone_id: str) -> Zone:
        for z in self.zones:
            if z.id == zone_id:
                return z
        raise KeyError(zone_id)

    def to_dict(self) -> dict:
        return _strip_none(asdict(self))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _strip_none(obj):
    if isinstance(obj, dict):
        return {k: _strip_none(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_none(v) for v in obj]
    return obj


def schema_errors(data: dict) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    v = Draft202012Validator(schema)
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in sorted(v.iter_errors(data), key=lambda e: list(e.absolute_path))]


def semantic_errors(spec: MapSpec) -> list[str]:
    """Cross-field checks the JSON Schema cannot express."""
    errs: list[str] = []
    ids = [z.id for z in spec.zones]
    if len(ids) != len(set(ids)):
        errs.append("zones: duplicate zone ids")
    for z in spec.zones:
        want = z.planet_count - 1 if z.kind == "home" else z.planet_count
        if z.kind != "pirate" and len(z.size_tiers) != want:
            errs.append(f"zone {z.id}: size_tiers has {len(z.size_tiers)} entries, expected {want}")
        if z.slot_biases is not None and len(z.slot_biases) != len(z.size_tiers):
            errs.append(f"zone {z.id}: slot_biases has {len(z.slot_biases)} entries, "
                        f"expected one per size_tiers entry ({len(z.size_tiers)})")
        if z.kind == "home" and z.owner_player is None:
            errs.append(f"zone {z.id}: home zone needs owner_player")
        if z.kind != "home" and z.owner_player is not None:
            errs.append(f"zone {z.id}: owner_player is only for home zones")
        if z.gated and z.chokepoints < 1:
            errs.append(f"zone {z.id}: gated zone needs chokepoints >= 1")
        if z.placement.kind == "between":
            for other in z.placement.zones or []:
                if other not in ids:
                    errs.append(f"zone {z.id}: placement.between names unknown zone {other}")
        if z.placement.kind == "ring_slot" and z.placement.slot is None:
            errs.append(f"zone {z.id}: ring_slot placement needs slot")
        if z.placement.kind == "cluster" and (z.placement.cluster is None or z.placement.slot is None):
            errs.append(f"zone {z.id}: cluster placement needs both 'cluster' and 'slot'")
        if z.placement.kind == "ring_slot" and spec.layout.shape != "ring":
            errs.append(f"zone {z.id}: ring_slot placement needs layout.shape 'ring'")
        if z.placement.kind == "cluster" and z.kind in ("border", "contested", "core"):
            errs.append(f"zone {z.id}: cluster placement is for home zones, or for filler/pirate zones "
                        f"anchored to a theater; use 'between' or 'center' for {z.kind}")
        if z.placement.kind == "cluster" and spec.layout.shape != "clusters":
            errs.append(f"zone {z.id}: cluster placement needs layout.shape 'clusters'")
        if z.placement.kind == "band":
            if spec.layout.shape != "concentric":
                errs.append(f"zone {z.id}: band placement needs layout.shape 'concentric'")
            elif z.placement.band is None or z.placement.slot is None:
                errs.append(f"zone {z.id}: band placement needs both 'band' and 'slot'")
            elif z.placement.band >= len(spec.layout.band_radii or []):
                errs.append(f"zone {z.id}: band {z.placement.band} but layout.band_radii has "
                            f"{len(spec.layout.band_radii or [])} entries")
        if z.chokepoint_role and z.chokepoint_role != "default" and not z.gated:
            errs.append(f"zone {z.id}: chokepoint_role is only meaningful on a gated zone")
        if z.resource_bias == "none" and z.size_tiers:
            errs.append(f"zone {z.id}: resource_bias 'none' has no planet filling, so it is only valid for "
                        f"a zone with no size_tiers (a pirate zone)")
        if z.loot != "none":
            errs.append(f"zone {z.id}: loot '{z.loot}' not supported yet (loot fields unverified)")
    for i, l in enumerate(spec.links):
        for end in (l.from_zone, l.to_zone):
            if end not in ids:
                errs.append(f"links/{i}: unknown zone {end}")
    if spec.features and any(spec.features.values()):
        errs.append("features: rifts / wormhole_pairs need verified Harbinger names (not yet)")
    if spec.layout.shape == "concentric":
        if not spec.layout.band_radii:
            errs.append("concentric layout: layout.band_radii is required (outermost first)")
        elif any(r <= 0 for r in spec.layout.band_radii):
            errs.append("concentric layout: every band radius must be positive")
        if spec.layout.band_offsets is not None and                 len(spec.layout.band_offsets) != len(spec.layout.band_radii or []):
            errs.append("concentric layout: band_offsets must have one entry per band")
        banded = [z for z in spec.zones if z.placement.kind == "band"]
        if not banded:
            errs.append("concentric layout: no zone uses band placement")
    if spec.layout.shape == "clusters":
        homes = [z for z in spec.zones if z.kind == "home"]
        bad = [z.id for z in homes if z.placement.kind != "cluster"]
        if bad:
            errs.append(f"clusters layout: home zones must use 'cluster' placement; {bad} do not")
    return errs


def from_dict(data: dict) -> MapSpec:
    errs = schema_errors(data)
    if errs:
        raise SpecError("MapSpec schema errors:\n  " + "\n  ".join(errs))
    zones = [Zone(**{**z, "placement": Placement(**z["placement"])}) for z in data["zones"]]
    spec = MapSpec(
        meta=Meta(**data["meta"]),
        layout=Layout(**data["layout"]),
        zones=zones,
        links=[Link(**l) for l in data["links"]],
        constraints=Constraints(**data["constraints"]),
        features=data.get("features"),
    )
    errs = semantic_errors(spec)
    if errs:
        raise SpecError("MapSpec errors:\n  " + "\n  ".join(errs))
    return spec


def load(path: Path) -> MapSpec:
    return from_dict(json.loads(path.read_text(encoding="utf-8")))
