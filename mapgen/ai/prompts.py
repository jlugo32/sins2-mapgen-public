"""System prompt and few-shot examples for natural language -> MapSpec.

The rules below are the verified ones from FINDINGS.md. The model never sees filling names, node ids or
coordinates: it works in roles and tiers only, and the compiler resolves the rest.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .. import ROOT
from ..config import Limits
from .schemas import MAX_QUESTIONS

EXAMPLES_DIR = Path(__file__).resolve().parent / "examples"

SYSTEM = """\
You turn a description of a Sins of a Solar Empire II map into a MapSpec: our own JSON intermediate
representation. A deterministic compiler turns your MapSpec into the game files. You never write game
data yourself.

VOCABULARY. You only ever use abstract roles and tiers:
- zone kinds: home, border, contested, core, filler, pirate, custom
- size tiers: S, M, L, XL   - resource bias: metal, crystal, balanced, none
- lane types: normal, wormhole
NEVER write filling names (no "random_ferrous_planet"), node ids, or x/y coordinates. There is no field
for them and the schema will reject them.

VERIFIED ENGINE RULES (from the official schema and the vanilla game files; never work around these):
- One star per map in the ring layout. Every planet is a body under it.
- Bodies per star: above {warn} the build warns (the largest vanilla single-star map has {warn}); above
  {hard} it is refused. Count planets plus wormhole fixtures.
- Every body needs at least one lane. The graph must be fully connected.
- Wormhole lanes only ever join two wormhole fixtures. Star lanes only ever join two stars. A wormhole
  link between zones compiles to: planet - normal lane - fixture - wormhole lane - fixture - normal lane
  - planet. You only declare the link; the compiler builds the fixtures.
- Exactly one home planet per player, with player_index 0..players-1. Players are 2..10.
- There is NO planet-type ownership restriction: every faction can colonise every planet type, though
  some types need research first. Do not "reserve" planet types for anyone.
- The gas giant is the XL balanced planet and is core-only. Never put XL balanced in a home zone or in a
  metal-bias slot.
- At most one research-gated planet per home cluster. Research-gated tiers are: S crystal, M metal,
  M crystal, L crystal, L balanced, XL (all). Safe home picks are L metal, M balanced, S metal,
  S balanced.
- Safe home recipe: size_tiers ["L", "M", "M", "L", "S"] with
  slot_biases ["metal", "balanced", "metal", "metal", "metal"] gives exactly one research-gated planet
  and metal-leaning homes. Home zones never use XL or a crystal bias.
- A gated zone is reachable only through its chokepoints. Give it `gated: true`, a `chokepoints` count,
  and one `chokepoint: true` wormhole link per chokepoint. Never add another link into a gated zone: the
  compiler will report CHOKEPOINT_BYPASS and refuse to build.
- zone.size_tiers has one entry per planet, except for home zones where it covers the non-home planets
  (planet_count - 1) and pirate zones where it is empty. Optional zone.slot_biases gives one bias per
  size_tiers entry and overrides resource_bias, which is how a core mixes one balanced XL with crystal L
  planets.
- constraints.total_planets must equal the sum of every zone's planet_count. Wormhole fixtures are
  counted separately and are not planets.
- Only layout.shape "ring" is implemented. loot must be "none"; npc is "none" or "pirate". There is no
  militia option: every planet already comes with militia defenders sized by its type, so militia is not
  something a map places.

DESIGN GUIDANCE (not hard rules):
- Homes are metal-leaning so crystal is worth fighting for; border and contested zones are where the
  crystal sits.
- One convoy per region, joining regions that are not ring neighbours, reads as a supply line.
- Put major (2-planet) border fields between regions that have no core access, so advantages do not
  stack on the same players.
- Border fields may vary in size for texture (minor = 1 planet, major = 2), chosen to fit the request.
- Keep the map symmetric unless the user asks otherwise: same cluster size and shape for every player.

ANSWER WITH EXACTLY ONE BRANCH:
- "spec" (plus optional "assumptions") to build. Put every interpretive or flavour call in assumptions:
  theme, naming, tier and bias choices, how you read a vague adjective. Assumptions are shown to the
  user after the build.
- "clarifying_questions" ONLY when the answer changes what gets built and only the user can supply it:
  a player count outside 2..10, constraints that contradict each other, or planet arithmetic that cannot
  close. At most {max_q} questions. Never ask about flavour, naming or aesthetics - decide, and record it
  as an assumption. If you can build something reasonable, build it.
"""


def system_prompt(limits: Limits) -> str:
    return SYSTEM.format(warn=limits.warn_bodies_per_star, hard=limits.max_bodies_per_star,
                         max_q=MAX_QUESTIONS)


EXAMPLE_REQUESTS = {
    "ww2_rimward_front": (
        "Ten players on a ring, about 100 planets. Each empire gets its own cluster. Wormhole convoys "
        "between empires that are not neighbours, and a rich core in the middle that can only be reached "
        "through a few chokepoints. Put some pirates in the gaps. Call it WW2: Rimward Front."),
    "duel_4p": (
        "Small fast four player free-for-all, around 30 planets, no wormholes and no protected middle. "
        "I want fighting early."),
    "oil_chokepoint_6p": (
        "Six players. The middle is an oil basin: the only really metal-rich ground on the map, and it "
        "should only be reachable through two chokepoints. Give everyone one convoy wormhole to a "
        "non-neighbour, and put the big border fields where they do not stack with the oil access."),
}

EXAMPLE_ASSUMPTIONS = {
    "ww2_rimward_front": ["Read 'rich core' as one gas giant plus crystalline planets, so the core is the "
                          "crystal prize and homes stay metal-leaning.",
                          "Three chokepoints, from the regions spaced around the ring."],
    "duel_4p": ["No gated zone and no wormholes, so every fight is on the ring.",
                "Crystal on the four border fields, since the home clusters are metal-leaning.",
                "One pirate planet only, to keep the early game fast."],
    "oil_chokepoint_6p": ["Oil = metal: the gated zone is metal-bias, with one balanced XL as its prize.",
                          "Major fields on borders 1 and 4, the only borders touching no core-access region."],
}


@lru_cache(maxsize=4)
def examples(only: tuple[str, ...] | None = None) -> list[tuple[str, dict]]:
    """(user request, assistant response) pairs. Every spec here is checked by the offline example test."""
    out = []
    for name, request in EXAMPLE_REQUESTS.items():
        if only is not None and name not in only:
            continue
        path = EXAMPLES_DIR / f"{name}.mapspec.json"
        if not path.exists():
            path = ROOT / "specs" / f"{name}.mapspec.json"
        answer = {"spec": json.loads(path.read_text(encoding="utf-8"))}
        if EXAMPLE_ASSUMPTIONS.get(name):
            answer["assumptions"] = EXAMPLE_ASSUMPTIONS[name]
        out.append((request, answer))
    return out


def messages(request: str, seed: int | None = None, only: tuple[str, ...] | None = None) -> list[dict]:
    msgs: list[dict] = []
    for user_text, answer in examples(only):
        msgs.append({"role": "user", "content": user_text})
        msgs.append({"role": "assistant", "content": json.dumps(answer, sort_keys=True)})
    ask = request if seed is None else f"{request}\n\n(Use seed {seed}.)"
    msgs.append({"role": "user", "content": ask})
    return msgs


def repair_message(violations: list[str]) -> str:
    """Used by repair.py (step 3.3): feed violation codes and hints back for a revised spec."""
    joined = "\n".join(f"- {v}" for v in violations)
    return ("Your MapSpec was compiled and checked. It failed these rules:\n"
            f"{joined}\n\n"
            "Return a corrected MapSpec in the same format. Fix the spec, never weaken a rule: the engine "
            "rules above are fixed. If the request cannot be satisfied within them, answer with "
            "clarifying_questions instead.")
