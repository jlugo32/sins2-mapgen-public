# BRIEF.md — sins2-mapgen (source of truth for every session)

Keep this file in the repo root and committed. If anything in code or FINDINGS.md conflicts with this
brief, stop and ask. Section 0 records decisions already made; later sections are the build spec.

## Project

A local Windows Python tool that generates Sins of a Solar Empire II scenarios (maps) plus a complete,
loadable mod folder. There are two ways to drive it:

1. **Templates or specs.** Deterministic and scriptable.
2. **Natural language.** I describe a map and the tool builds it.

This is **not** a web app: no VPS, no deploy, no auth, no SEO. Python 3.12.

### Prime directives

1. **Never guess.** Every value written to an output file must trace to one of: the official schema, a
   vanilla file from my install, or my explicit answer. Keep provenance in FINDINGS.md. If a value can't
   be verified, stop and ask.
2. **The AI layer never writes game files.** The LLM only produces a MapSpec, our own JSON IR, using
   abstract roles and tiers. The deterministic compiler does everything else:
   - maps roles to verified `filling_name`s,
   - builds nodes and lanes,
   - runs the rule checks and schema validation.

---

## 0. Resolved decisions (Step 1 complete)

### Environment

- **Game:** `D:\Games\Sins of a Solar Empire II` (Stardock build, Sept 2026, 93 scenarios). Ignore the
  Epic copy on F:.
- **Schemas:** `schema_dir = C:\dev\refs\sins2modtools\json_schemas`, a sparse clone at commit 8e061033
  ("Update to 1.61.3", 2026-07-07). Never use the F: copy. The schemas are proprietary, so reference them
  by path only. Never copy them into the repo or the mod, and never send them to the LLM.
- **Third-party reference:** BVisagie/sins2-mapmaker is hints only. It's AGPL, so don't copy its code.
  Several of its rules were proven wrong against vanilla files.

### File format (verified against vanilla)

- A `.scenario` file is a zip containing:
  - `scenario_info.json`
  - `galaxy_chart.json`
  - `galaxy_chart_fillings.json`
  - `picture.png` (512×512, measured across all 90 vanilla pictures)
- `scenario_info` keys, wormhole wiring, and star-lane wiring are all verified against vanilla. Copy their
  structure from the vanilla references; don't invent it.
- `player_index` starts at 0.
- `localized_text/en.localized_text` is flat JSON.
- `uniforms/scenario.uniforms` must include all four required arrays:
  - `dlc_multiplayer_scenarios`
  - `dlc_scenarios`
  - `fake_server_scenarios`
  - `scenarios`
- `.mod_meta_data` contains `compatibility_version: 2`, `display_name`, `display_version`,
  `short_description`, and `logos {large_logo, small_logo}`. Status: "official doc + community-verified,
  not verified against an installed mod." Diff it against a real mod.io mod later.
- **Install path:** `%LOCALAPPDATA%\sins2\mods\<mod_name>\`
- **Quick test without a mod:** `%LOCALAPPDATA%\sins2\drop_in_scenarios\`

### Limits (Q1)

- Warn above 102 bodies per star, which is the largest vanilla single-star map.
- Hard stop above 150 bodies per star.
- At most 10 stars.
- These live in the `[limits]` block of config.toml, not in code.
- **Gate:** build the default ~116-body ring map, and I load-test it in game **before any AI-layer work**.

### Ownership and colonization

- Every faction can colonize every planet type (source: the `.player` files). There is **no**
  planet-type ownership restriction.
- Rule: exactly one `player_home_planet` per player, with `player_index` in `0..players-1`.
- Pirates use the vanilla pattern: `player_home_planet` with `ownership.npc_filling_name: "pirate"`
  (used 34× in vanilla).

### Resources (Q5)

- Metal and crystal values live in the planet `.unit` files: `planet.non_random_*` + `planet.random_*`.
- A tier is defined by the amount of the biased resource. "(R)" means most factions need research to
  colonize that planet.

| tier | metal bias | crystal bias | balanced |
|---|---|---|---|
| S | random_ship_graveyard_planet 3–4 / 1–2 | random_oceanic_planet 1–2 / 4–6 (R) | random_barren_planet 3–4 / 3–4 |
| M | random_volcanic_planet 6–8 / 0 (R) | random_ice_planet 0 / 6–8 (R) | random_desert_planet 4–6 / 4–6 |
| L | random_ferrous_planet 9–10 / 0 | random_crystalline_planet 0 / 9–10 (R) | random_irradiated_planet 6–8 / 6–8 (R) |
| XL | = L (ferrous) | = L (crystalline) | random_gas_giant_planet 8–10 / 8–10 (R) |

- **XL rule.** XL metal and XL crystal reuse the L planets. "Bigger" means more planets in the field (a
  major field is 2 planets; the core uses several). Gas giant appears **only** in XL balanced, used for the
  core's richest planet(s), and never in home or metal-bias slots.
- **Optional XL boost.** `chance_of_first_planet_bonus` / `chance_of_second_planet_bonus` may be used for
  XL only if the `.unit` files prove a bonus adds resources. Otherwise it stays off.
- **Home fairness.** Each home cluster contains at most one (R) planet. Its non-home planets come from the
  metal-bias and balanced S/M/L tiers.
- `data/fillings.json` stores this table, with the source `.unit` file and values for each entry.

### Other questions (defaults adopted)

- **Q2 (planet count).** The chokepoints are counted inside the 6 core planets. Total planets: 60 home +
  14 border + 5 convoy + 6 core + 15 filler = 100. Wormhole fixtures are counted separately; there are 16.
- **Q3 (convoys).** Skip-two chords (i↔i+3) form a perfect matching: 0–3, 2–5, 4–7, 6–9, 8–1. Every
  region gets exactly one convoy. The skip distance is configurable with `--convoy-skip`.
- **Q4 (convoy wiring).** Each convoy runs homeA_edge, then a normal lane to a wormhole fixture, a
  wormhole lane to a second fixture, a normal lane to the contested planet, and a normal lane to
  homeB_edge. Confirm this matches vanilla wormhole wiring.
- **Q6 (homes).** Each home cluster has 6 planets: 1 `player_home_planet` plus 5 unowned planets, which
  are metal-leaning per the resource rules above.
- **Q7 (core access).** Regions 0, 3, and 7 have core access. Configurable with `--core-access`.
- **Q8 (major fields).** The major fields sit on borders **1, 4, 5 and 8** (revised 2026-09-22 after the
  load test, see §5.2; was 0, 2, 5, 7, which stacked majors onto the core-access regions). With core access
  at regions 0, 3 and 7, these are the only four borders that touch no core-access region, so home_5
  unavoidably touches two majors (borders 4 and 5).
- **Q9 (filler).** Of the 15 filler planets, 3 are pirate and 12 are neutral.
- **Q10 (names).** Use localized keys plus `en.localized_text`, with an `--inline-names` fallback that uses
  the `:` literal prefix.
- **Q11 (AI model).** Default model `claude-sonnet-5`, configurable via `MAPGEN_MODEL`. Use structured
  outputs, and check https://docs.claude.com before implementing.

---

## 1. Step 2: deterministic core (build now; no AI layer yet)

### File structure

```
sins2-mapgen/
  BRIEF.md
  CLAUDE.md
  FINDINGS.md
  requirements.txt      (jsonschema>=4.18, referencing, Pillow, pytest, anthropic, python-dotenv, rich)
  config.toml           (gitignored)
  config.example.toml
  .env.example
  .gitignore
  generate_map.py       CLI: build | ai | validate | install | inspect
  mapgen/
    params.py           @dataclass MapParams (template knobs; nothing hardcoded elsewhere)
    spec.py             MapSpec dataclasses + load/save; JSON Schema at schemas/mapspec.schema.json
    templates/ring.py   MapParams → MapSpec
    templates/__init__.py
    fillings.py         (tier, bias, role) → verified filling_name from data/fillings.json
    compiler.py         MapSpec → nodes, lanes, positions
    rules.py            checks → list[Violation{code, message, node_ids, hint}]
    scenario_writer.py
    mod_writer.py
    validate.py
    preview.py
    ai/                 Step 3 only: client.py, prompts.py, translate.py, repair.py, chat.py, describe.py
  .claude/skills/sins2-map/SKILL.md   Step 3 only
  data/
    fillings.json
    reference/          gitignored
  specs/
  out/                  gitignored
  tools/inspect_vanilla.py
  tests/
    test_rules.py
    test_validation.py
    test_determinism.py
    test_spec.py
    test_ai_offline.py  Step 3
```

### Default ring template

All values below are MapParams and can be overridden.

- **Shape.** 10 players and 100 planets around a single central star, with a seed for reproducibility.
- **Home regions.** Ten clusters of 6 planets on a ring. Each cluster is internally laned with a spanning
  tree plus 1–2 loop edges.
- **Border fields.**
  - There is one border field between every ring-adjacent pair of regions.
  - The fields on borders 0, 2, 5, and 7 are 2-planet majors, using the larger tier.
- **Convoys.** Wired per Q3/Q4. Each convoy has 1 S-tier contested planet.
- **Core.**
  - 6 rich planets near the star: gas giant(s) plus L-tier planets.
  - Reachable **only** through 3 wormhole spokes, from regions 0, 3, and 7.
  - Each spoke ends at a chokepoint planet. The chokepoint is a starbase site with a single lane in and
    no bypass.
- **Filler.** 15 planets (3 pirate) placed in the gaps. Each is laned to its nearest planet, excluding
  core planets and chokepoints.

### Compiler

- One star at the center as the root node. All bodies are its `child_nodes`.
- Unique integer ids for all nodes and all lanes.
- Positions use vanilla units, with minimum-distance spacing, and are locked so orbits can't rewire lanes
  (follow vanilla's `scenario_info` / orbit fields).

### Rule checks

Any violation means no output. Every violation carries a machine code and a human hint.

**Engine rules:**
- Every body has at least 1 lane.
- Every body has exactly one parent star.
- `star` lanes connect star to star only.
- `wormhole` lanes connect wormhole fixture to wormhole fixture only.
- No self-loops and no duplicate lanes.
- Exactly one `player_home_planet` per player, with `player_index` in range.
- Bodies per star follow the configured limits (warn above 102, error above 150).
- Every `filling_name` is verified in `fillings.json`.

**Design rules:**
- The graph is fully connected.
- Counts match the spec: players, planets, convoys per region, major fields, pirates.
- **Chokepoint proof:** removing the declared chokepoints disconnects each gated zone from every home
  planet, and each chokepoint is a cut vertex for its spoke.
- No gas giant appears in home or metal-bias slots.
- At most one (R) planet per home cluster.
- The planet total matches the spec. Fixtures are reported separately.

**Output:** print a summary table per region with its planets, lanes, convoy partner, border fields, and
core access.

### CLI

```
python generate_map.py build --template ring --players 10 --planets 100 --seed 42 --name ww2_rimward_front --display-name "WW2: Rimward Front"
python generate_map.py build --spec specs/foo.mapspec.json
```

Flags: `--install`, `--preview-only`, `--params file.json`.

Changing the player or planet counts must rescale the design, with filler absorbing the remainder. If the
counts can't be satisfied, fail with an error that names the constraint that broke.

---

## 2. Output and validation

- Build `out/<mod_name>/` with this layout:
  - `.mod_meta_data`
  - `picture.png` (512×512)
  - `scenarios/<name>.scenario`
  - `uniforms/scenario.uniforms`
  - `localized_text/en.localized_text`
- Validate with `jsonschema.Draft202012Validator` explicitly. The official schemas declare draft-07 but
  use `unevaluatedProperties`, which draft-07 validators ignore.
- **Validator self-test on every run:** validate a copy with `"bogus_field": 1` injected on a node and on
  a lane. Validation must fail; if it passes, abort.
- Validate `galaxy_chart.json` and `scenario.uniforms` against the schemas. Diff the key sets of
  `scenario_info.json` and `galaxy_chart_fillings.json` against vanilla.
- Report errors as file → JSON path → message, and exit non-zero on any failure.
- **Deterministic output:** the same spec and seed must produce byte-identical files (sorted keys, stable
  ids, fixed zip timestamps).
- `--install` copies to `%LOCALAPPDATA%\sins2\mods\<mod_name>\`. Refuse to overwrite a folder this tool
  didn't create; otherwise back it up first.

**⛔ GATE: stop here after building the default map.** I load-test it in game: it loads, player slots
work, convoy wormholes are usable, and the core is reachable only through the chokepoints. Report the
results before starting Step 3.

---

## 3. Step 3: AI layer (only after the gate passes)

### MapSpec IR

Defined in `schemas/mapspec.schema.json`, strict, with no extra properties allowed. It contains **no**
`filling_name`s, ids, or coordinates.

- **meta:** name (slug), display_name, description, players (2–10), teams, seed
- **layout:** `shape` (ring | line | grid | clusters | twin), `radius_scale` (0.5–2.0)
- **zones[]:**
  - `id`
  - `kind`: home | border | contested | core | filler | pirate | custom
  - `owner_player` (homes only)
  - `planet_count`
  - `size_tiers[]`: S | M | L | XL
  - `resource_bias`: metal | crystal | balanced | none
  - `internal_links`: tree | loop | dense
  - `placement`: ring_slot | center | between[zoneA, zoneB] | gap
  - `gated` (bool), `chokepoints` (int)
  - `loot`: none | small | large
  - `npc`: none | militia | pirate
- **links[]:** `from_zone`, `to_zone`, `lane` (normal | wormhole), `via_contested_planets` (int),
  `chokepoint` (bool)
- **constraints:** total_planets, max_bodies_per_star, symmetric, notes[]
- **features (optional):** `rifts`, `wormhole_pairs`. Use these only once the Harbinger rift fixture names
  are verified in my install.

The ring template also compiles through MapSpec, so the template and AI paths share one pipeline.

### ai/translate.py (natural language → MapSpec)

- Uses the Anthropic API with structured outputs. The output shape is the MapSpec schema plus the
  verified role/tier vocabulary.
- Includes few-shot examples: the default ring map, a 4-player duel, and a WW2 "oil chokepoint" map.
- The system prompt includes the engine rules and limits.
- When a request is ambiguous or breaks a limit, the model returns `clarifying_questions[]` instead of
  guessing.
- Validate the returned spec locally. On failure, re-ask once with the errors; if it fails again, stop
  with a clear error.
- Read the key from `ANTHROPIC_API_KEY` in `.env` (gitignored). Never hardcode it or log it.

### ai/repair.py (repair loop)

- **Loop:** compile, run the rule checks, and on any violation send the violation codes and hints back to
  the model for a revised spec. Maximum 3 rounds.
- **If it still fails:** show me the violations, the closest spec, and 2–3 concrete options.
- **Never loosen an engine rule** to make a map pass.

### ai/describe.py

Writes a plain-English summary of what was **actually** built, computed from the compiled graph (not from
the model's claims). It also reports any differences between my request and the result.

### CLI

```
python generate_map.py ai "<description>" [--seed N] [--dry-run]
python generate_map.py ai --chat
```

Chat mode is a REPL that edits the current spec. Commands:

| Command | Purpose |
|---|---|
| `/preview` | Render the current map |
| `/summary` | Plain-English summary of what's built |
| `/undo` | Revert the last change |
| `/diff` | Show changes since the last save |
| `/save` | Save the spec |
| `/build` | Build the mod |
| `/install` | Install into the game's mods folder |
| `/seed N` | Change the seed |
| `/quit` | Exit |

Log each AI call's model, token counts, and estimated cost to `out/ai_log.jsonl`.

### Claude Code skill (no API key needed)

`.claude/skills/sins2-map/SKILL.md` handles plain-English map requests inside Claude Code:

1. Read BRIEF.md, FINDINGS.md, `mapspec.schema.json`, and the roles in `fillings.json`.
2. Write a spec to `specs/`.
3. Run `build --spec`.
4. On violations, fix the spec using the same rules as the repair loop.
5. Show the summary and the preview path.
6. Ask me before running `--install`.

Never hand-edit anything under `out/`.

### Offline tests

Mock the client for these cases:

- A valid spec builds.
- A schema-invalid spec triggers one re-ask, then fails.
- `CHOKEPOINT_BYPASS` is repaired by the loop.
- An unresolvable spec stops after 3 rounds and presents options.
- An ambiguous request surfaces clarifying questions and builds nothing.

Plus one opt-in live test, run with `pytest -m live`.

---

## 4. CLAUDE.md (project root)

- What the tool does, the two driving modes, and the rule that the AI writes specs while the compiler
  writes game files.
- Setup: venv, requirements, config.toml, and `.env` (only needed for the `ai` subcommand).
- Sources: official schemas (commit hash), vanilla install files, and the third-party editor (hints only).
- Examples for every mode.
- Loading in game: copy the mod to `%LOCALAPPDATA%\sins2\mods\`, then Modding → Local → Enable → Manage →
  Apply Changes, then pick the map in skirmish. To reload during iteration: disable → apply → enable →
  apply.
- After any game patch: re-run `tools/inspect_vanilla.py`, `git pull` the schemas, and re-run the tests.
- Troubleshooting:
  - "Mod Compatibility Version: 0" means a bad `.mod_meta_data`.
  - Stray lanes in game mean an unlinked planet or orbit drift.
  - A map missing from the list means the name in `scenario.uniforms` doesn't match the `.scenario`
    filename.

---

## 5. Post-gate queue

**GATE PASSED 2026-09-22.** Step 2 is tagged `v0.2.0` (commit `8bcb242`): the map loads, all 10 slots
fill, the 10 home clusters and the core render correctly, wormhole fixtures are present, and performance
is fine at 116 bodies after 2+ hours of play.

1. ~~**Tag** the Step 2 commit.~~ DONE: `v0.2.0`.
2. ~~**Balance fix.**~~ DONE 2026-09-22: `REGION_ADVANTAGE_STACK` (warning) plus a per-region "Region
   advantages" table, and the majors moved to borders 1, 4, 5, 8.
   **home_5's double major is unavoidable; do not revisit.** With 3 spokes, 6 borders touch a core-access
   region, leaving 4 free borders = 8 endpoints for 7 non-core homes, so one home always doubles up. The
   alternatives are fewer majors, more spokes, or a different spoke spacing — all bigger changes.
3. ~~**Optional theme.**~~ APPLIED 2026-09-22 (option B + the home swap):
   - MapSpec zones gained optional `slot_biases[]` (one bias per `size_tiers` entry, overriding
     `resource_bias`), so one zone can mix biases.
   - Core: gas giant + 5 crystalline (`core_inner_biases`, `core_chokepoint_bias`). Metal 44 → 9,
     crystal 44 → 56.5. Option A (all-crystalline, no gas giant) was rejected.
   - Homes: ferrous, desert, volcanic (R), **ferrous**, ship graveyard. Metal 28.5 → 34.5,
     crystal 10.0 → 6.5. Still one (R) per cluster.
   - Crystal reachable without entering the core (own cluster + borders touched + convoy planet):
     22 for the three spoke regions, 31–43 for the rest, against a 15 floor. Nothing is starved; the
     spoke regions are lowest outside the core and have 56.5 crystal behind their own chokepoint.
   - Open, not acted on: in-cluster crystal before taking any border fell 10.0 → 6.5, which tightens the
     opening. If that bites in play, swap the home volcanic (M metal, R) for ice (M crystal, R) — metal
     27.5 / crystal 13.5, still one (R).
