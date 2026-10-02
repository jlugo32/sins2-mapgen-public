"""MapParams: every template knob. Nothing design-related is hardcoded elsewhere.

Defaults are BRIEF.md §0 decisions (Q2–Q9) and vanilla-derived geometry (FINDINGS §7).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class Geometry:
    """Vanilla units. Ranges checked against vanilla single-star maps (FINDINGS §7)."""
    ring_radius: float = 2200.0          # home cluster centres
    cluster_radius: float = 330.0        # non-home planets around the home planet
    min_spacing: float = 160.0           # vanilla nearest-neighbour min 54–194
    core_radius: float = 320.0           # inner core planets
    chokepoint_radius: float = 700.0
    spoke_exit_radius: float = 1000.0    # wormhole fixture next to each chokepoint
    spoke_entry_offset: float = 230.0    # wormhole fixture inside each access region, toward the star
    convoy_contested_offset: float = 260.0   # outside the ring, beyond the cluster edge
    convoy_fixture_offset: float = 520.0
    border_major_split: float = 170.0    # radial split of the 2 planets in a major field
    filler_inner: float = 1150.0         # filler annulus (ring layout)
    filler_outer: float = 1700.0
    # clusters layout
    theater_radius: float = 3400.0       # distance of each theater centre from the map centre
    theater_spread: float = 1150.0       # a power's offset from its theater centre
    gated_offset: float = 1000.0         # how far a gated zone sits off the line between its anchors
    gap_clearance: float = 1.6           # multiples of min_spacing kept around gap-placed planets
    gap_reach: float = 2200.0            # a gap planet must stay within this of some existing planet


@dataclass
class MapParams:
    # meta
    name: str = "ww2_rimward_front"
    display_name: str = "WW2: Rimward Front"
    description: str = "Ten empires on a ring. Wormhole convoys, a gated core, pirates in the gaps."
    display_version: str = "1.0.0"
    seed: int = 42
    inline_names: bool = False            # Q10
    resources_label: str = "scenario_options_view_resources_medium"
    # counts
    players: int = 10
    planets: int = 100                    # Q2: planets only; fixtures counted separately
    # homes (Q6)
    # post-gate theme: ferrous, desert, volcanic (R), ferrous, ship graveyard -> metal 34.5 / crystal 6.5
    home_slot_tiers: list[str] = field(default_factory=lambda: ["L", "M", "M", "L", "S"])
    home_slot_biases: list[str] | None = field(
        default_factory=lambda: ["metal", "balanced", "metal", "metal", "metal"])
    home_bias: str = "metal"              # fallback when home_slot_biases is None (metal-leaning pattern)
    home_links: str = "loop"              # spanning tree + 1–2 loop edges (BRIEF §1)
    # borders (Q8, revised after the load test: majors sit between regions without core access)
    major_borders: list[int] = field(default_factory=lambda: [1, 4, 5, 8])
    minor_border_tier: str = "M"
    major_border_tier: str = "L"
    border_bias_cycle: list[str] = field(default_factory=lambda: ["crystal", "balanced"])
    # convoys (Q3/Q4)
    convoy_skip: int = 3
    contested_tier: str = "S"
    contested_bias: str = "balanced"
    # core (Q7)
    core_access: list[int] = field(default_factory=lambda: [0, 3, 7])
    core_inner_tiers: list[str] = field(default_factory=lambda: ["XL", "L", "L"])
    # post-gate theme option B: one balanced XL (gas giant) + crystalline L planets
    core_inner_biases: list[str] = field(default_factory=lambda: ["balanced", "crystal", "crystal"])
    core_chokepoint_tier: str = "L"
    core_chokepoint_bias: str = "crystal"
    core_bias: str = "balanced"
    # filler (Q9)
    pirates: int = 3
    filler_tier_cycle: list[str] = field(default_factory=lambda: ["S", "M"])
    filler_bias: str = "balanced"
    geometry: Geometry = field(default_factory=Geometry)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MapParams":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown MapParams keys: {sorted(unknown)}")
        data = dict(data)
        if "geometry" in data:
            data["geometry"] = Geometry(**data["geometry"])
        return cls(**data)

    @classmethod
    def from_file(cls, path: Path) -> "MapParams":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
