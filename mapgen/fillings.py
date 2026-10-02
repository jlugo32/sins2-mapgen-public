"""(tier, bias, role) → verified filling_name, from data/fillings.json (built by tools/build_fillings.py)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from . import ROOT

FILLINGS_PATH = ROOT / "data" / "fillings.json"


class FillingError(Exception):
    pass


@dataclass(frozen=True)
class Resolved:
    filling_name: str
    tier: str | None = None
    bias: str | None = None
    planet_type: str | None = None
    research_gated: bool = False
    metal: tuple[int, int] = (0, 0)
    crystal: tuple[int, int] = (0, 0)
    # Probability-weighted means. They differ from the midpoint of the range only when the filling
    # is a weighted roll the game performs at load - player_home_planet is random_fair_planet, four
    # outcomes at 15/25/30/30%, so its range is [0, 8] but its mean is 3.5, not 4.
    expected_metal: float | None = None
    expected_crystal: float | None = None
    ownership: tuple[tuple[str, str], ...] = ()   # role-level ownership (pirate)


@lru_cache(maxsize=1)
def table() -> dict:
    if not FILLINGS_PATH.exists():
        raise FillingError(f"{FILLINGS_PATH} missing. Run tools/build_fillings.py.")
    return json.loads(FILLINGS_PATH.read_text(encoding="utf-8"))


def verified_names() -> set[str]:
    return set(table()["verified_filling_names"])


def star_fillings() -> set[str]:
    return {n for n in verified_names() if n.endswith("_star") or n == "random_star"}


def role(name: str) -> Resolved:
    r = table()["roles"][name]
    own = tuple(sorted((r.get("ownership") or {}).items()))
    return Resolved(filling_name=r["filling_name"], ownership=own,
                    planet_type=r.get("planet_type"),
                    research_gated=bool(r.get("research_gated")),
                    metal=tuple(r.get("metal", (0, 0))), crystal=tuple(r.get("crystal", (0, 0))),
                    expected_metal=r.get("expected_metal"), expected_crystal=r.get("expected_crystal"))


def planet(tier: str, bias: str) -> Resolved:
    try:
        e = table()["tiers"][tier][bias]
    except KeyError:
        raise FillingError(f"no filling for tier {tier!r} bias {bias!r}") from None
    return Resolved(filling_name=e["filling_name"], tier=tier, bias=bias, planet_type=e["planet_type"],
                    research_gated=e["research_gated"], metal=tuple(e["metal"]), crystal=tuple(e["crystal"]))


def zone_planet(kind: str, zone_bias: str, tier: str, slot: int, slot_bias: str | None = None) -> Resolved:
    """Filling for non-home planet `slot` of a zone. Home zones with 'metal' bias are metal-leaning."""
    if slot_bias:
        return planet(tier, slot_bias)
    if zone_bias == "none":
        raise FillingError(f"{kind} zone: resource_bias 'none' has no planet filling")
    bias = zone_bias
    if kind == "home" and zone_bias == "metal":
        pattern = table()["home_bias_pattern"]["pattern"]
        bias = pattern[slot % len(pattern)]
    return planet(tier, bias)


def is_gas_giant(filling_name: str) -> bool:
    return filling_name == table()["tiers"]["XL"]["balanced"]["filling_name"]


def research_gated_names() -> set[str]:
    return {e["filling_name"] for row in table()["tiers"].values() for e in row.values() if e["research_gated"]}


def metal_bias_names() -> set[str]:
    return {row["metal"]["filling_name"] for row in table()["tiers"].values()}
