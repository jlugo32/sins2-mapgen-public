---
name: sins2-map
description: Use when the user asks for a Sins of a Solar Empire II map in this repo - "build me a map", "make a 6-player ring with a gated core", "change the map so ...", or any request to create, edit or rebuild a .scenario/mod from a description. Writes a MapSpec, builds it with generate_map.py, and repairs rule violations. No API key needed.
---

# sins2-map

Turn a plain-English map request into a validated Sins II mod, using this repo's deterministic compiler.
You do the translating that `mapgen/ai/translate.py` would do with the API; the compiler, the rules and
the validator are the same either way.

## Ground rules

- **BRIEF.md is the source of truth.** If anything here conflicts with it, stop and ask.
- You write a **MapSpec** only: abstract roles and tiers. Never write `filling_name`s, node ids or
  coordinates - the compiler resolves those. The schema rejects them.
- **Never hand-edit anything under `out/`.** Change the spec and rebuild.
- **Never loosen a rule** to make a map pass. Engine rules come from verified game files. If a request
  cannot be satisfied within them, say so and offer options.
- Ask before running `--install`.

## Steps

1. **Read first** (skip what you already have in context):
   - `BRIEF.md` S0 (decisions) and S1 (ring design)
   - `schemas/mapspec.schema.json` - the strict shape you must produce
   - `data/fillings.json` - the tier x bias table and which tiers are research-gated (`research_gated`)
   - `FINDINGS.md` S6-S7 if you need the vanilla facts behind a rule
   - `specs/ww2_rimward_front.mapspec.json` as the worked example, and
     `mapgen/ai/examples/*.mapspec.json` for a small map and a gated-core map
2. **Write the spec** to `specs/<name>.mapspec.json`. Keep `constraints.total_planets` equal to the sum
   of every zone's `planet_count`; wormhole fixtures are not planets.
3. **Build it:**
   ```
   .venv\Scripts\python generate_map.py build --spec specs\<name>.mapspec.json
   ```
4. **On violations,** fix the spec and rebuild. Same discipline as the repair loop: at most three
   attempts, then stop and show the user the closest spec, the outstanding violations and 2-3 options.
5. **Show** the per-region summary, the region-advantage and reachability tables that the build prints,
   plus the preview path (`out/<name>_preview.png`). Say what was actually built, from the build output,
   not from your own intent.
6. **Ask** before `generate_map.py install out\<name>`.

## Rules that bite most often

- `size_tiers` has one entry per planet - except **home** zones, where it covers the non-home planets
  (`planet_count - 1`), and **pirate** zones, where it is empty.
- Home clusters: at most **one research-gated planet**, tiers S/M/L only, bias metal or balanced.
  A safe set is `["L", "M", "M", "L", "S"]` with
  `slot_biases: ["metal", "balanced", "metal", "metal", "metal"]`.
- The **gas giant is XL balanced and core-only**. Never in a home zone or a metal-bias slot.
- A **gated** zone needs `gated: true`, `chokepoints: N`, and exactly N `chokepoint: true` wormhole
  links. Any other link into it is `CHOKEPOINT_BYPASS` and the build is refused.
- **Contested is not gated.** A contested zone is just fought over; only gate when the user asks for
  something that can only be reached a limited number of ways.
- Wormhole lanes join two wormhole fixtures; you declare the link and the compiler builds the fixtures.
- Bodies per star: warn above 102, refused above 150 (`[limits]` in config.toml).
- Only `layout.shape: "ring"` is implemented. `loot` must be `"none"`; `npc` is `"none"` or `"pirate"`.

## When to ask instead of guessing

Ask only when the answer changes the build and only the user can give it: a player count outside 2-10,
contradictory constraints, or planet arithmetic that cannot close. At most 3 questions. Flavour, naming
and tier choices are yours to make - state them as assumptions in your reply.
