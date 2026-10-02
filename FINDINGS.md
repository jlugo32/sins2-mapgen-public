# FINDINGS — sins2-mapgen ground truth (STEP 1)

Status: **PART 2 of 2 DONE (2026-09-22).** Vanilla install inspected with `tools/inspect_vanilla.py`;
raw report at `data/reference/inspect_report.md` (gitignored). Vanilla facts are in §6, Step 2 facts in §7.
Remaining gaps are in §5. Step 2 (deterministic core) built 2026-09-22; waiting on the in-game load-test gate.

Conflict rule: **official schema > vanilla install > third-party**.

## 0. Sources checked

| Source | Where | Version / date checked |
|---|---|---|
| Official schemas + docs (StardockCorp/sins2modtools) | sparse clone at `C:\dev\refs\sins2modtools` (`json_schemas`, `docs`) = `SCHEMA_DIR`, not copied into this project | commit `8e061033afe53b1393eaefd56617a3fd041eeb5f` ("Update to 1.61.3", 2026-07-07); fresh clone + `git pull` 2026-09-22, already up to date. The zip copy on F: is **not used**. |
| Third-party editor (BVisagie/sins2-mapmaker, AGPL, hints only, no code copied) | local clone | commit `d7f4b5b`, 2026-04-09; checked 2026-09-22 |
| Wiki "Map Creator Guide – Solar Forge" | web | **SKIPPED** (decision 2026-09-22: not load-bearing). All wiki claims UNVERIFIED. |
| Vanilla install | `D:\Games\Sins of a Solar Empire II\` (Stardock build, exes dated 2026-09-03, 93 `.scenario` files) | inspected 2026-09-22 |
| (not used) older Epic install | `F:\Program Files\Epic Games\SinsII\` | exes dated 2025-04-25, 79 scenarios — stale, ignored |

## 1. Official schema facts (VERIFIED — source: sins2modtools `json_schemas/`)

All four schema files declare `$schema: draft-07` but use `unevaluatedProperties: false`.
A draft-07 validator ignores that keyword → validate with `Draft202012Validator` (as planned).

### galaxy-chart-schema.json — CONFIRMED exactly as the brief lists
- Top: `phase_lanes[]`, `root_nodes[]`, `skybox` (required); `version`, `recommended_team_count` (optional).
- Node: `id` (int), `filling_name` (str) required. Optional: `position` (array of numbers, **no length limit
  in schema**), `child_nodes[]`, `ownership`, `chance_of_loot`, `loot_level` (int), `has_artifact`,
  `artifact_name`, `rotation`, `orbit_speed_scalar`, `original_parent_id`, `sync_orbit_to_parent`,
  `ignore_orbit_overlap_checks`, `inherit_original_parent_orbit_direction`, `chance_of_retrograde_orbit`,
  `chance_of_first_planet_bonus`, `chance_of_second_planet_bonus`, `design_name`, `primary_fixture_override_name`.
- Ownership: `player_index` (int), `npc_filling_type` enum [militia, guardian, enemy_faction, friendly_faction],
  `npc_filling_name` (str), `are_secondary_fixtures_owned` (bool).
- Lane: `id`, `node_a`, `node_b` required; `type` enum [normal, star, wormhole].
- The schema has **no** numeric caps (no max nodes, no max players, no range on chances).

### scenario-uniforms-schema.json — CONFIRMED, plus 3 fields the brief did not list
- Required: `dlc_multiplayer_scenarios`, `dlc_scenarios`, `fake_server_scenarios`, `scenarios`.
- Also allowed: `version`, `overwrite_scenarios`, `overwrite_fake_server_scenarios`,
  `overwrite_fake_dlc_multiplayer_scenarios` (bools).
- ⚠ The official tutorial shows only `scenarios` + `fake_server_scenarios`. That fails the schema.
  We follow the schema (all 4 required arrays). We never set `overwrite_scenarios` (that would hide vanilla maps).

### galaxy-generator-uniforms-schema.json — what drives resources (important for Q5)
- Filling system (in `base_fillings` / `combined_fillings`): `node_fillings`, `random_fixture_fillings`,
  `fixture_fillings`, `moon_fillings`, `gravity_well_fillings`, `npc_fillings`, `wormhole_fillings`,
  `random_skybox_fillings`, `artifacts`, each with `overwrite_*` flags.
- `node_fillings[].filling`: `primary_random_fixture_filling_name`, `primary_random_fixture_with_moon_filling_name`,
  `secondary_random_fixture_filling_name`, `is_primary_fixture_player_home_planet`, `gravity_wells`,
  `display_name`, `override_militia_supply`, `is_existence_known_to_all`.
- `fixture_fillings[].filling`: `entity_definition`, `random_metal_asteroids.tiers[{tier, count[min,max]}]`,
  `random_crystal_asteroids.tiers[...]`, `required_planet_bonuses[]`, `militia_supply`, `spawn_unit_definitions`, …
- `npc_fillings[].filling`: `npc_filling_type` (same 4-value enum), `npc_id`, `player_definition`.
- **Meaning:** a node's `filling_name` names a *node filling*. "Richness = filling choice" (brief Q5) is correct.
  ⚠ Corrected by vanilla (§6.4): for planets the asteroid counts live in the entity `.unit` file, not the
  fixture filling. Fixture-filling asteroid tiers only apply to non-planet fixtures (clouds, debris, storms).
- ⚠ Vanilla `galaxy_generator.uniforms` uses a single top-level `fillings` object, not `base_fillings` /
  `combined_fillings`. We only *read* this file, never emit it, so this does not affect output.
- Top-level: `max_ancient_starbases`, `max_capturable_units`, `min_jumps_to_any_home_planet_for_loot_level[]`,
  `player_phase_resonance_points[]`, gravity-well spacing arrays. No body cap here either.

### random-map-generator-uniforms-schema.json
- Has `player_count`, `planet_count`, `solar_system_count`, `team_count`, `wormholes`, `pirate_npcs`, … as
  UI range objects. **No schema-level caps.** The real min/max values live in the vanilla
  `random_map_generator.uniforms` → OPEN (inspector dumps it).

### docs/making_a_custom_scenario.md
- Mod layout: `<mod>/.mod_meta_data` with `{"compatibility_version": 2}`, `<mod>/scenarios/<name>.scenario`,
  `<mod>/uniforms/scenario.uniforms`. Install path `%localappdata%/sins2/mods/`. Quick test path
  `%localappdata%/sins2/drop_in_scenarios/`. → matches brief 1.5 (localized_text/picture.png not in the doc).
- Name/description with `:` prefix = literal (not localized) string. VERIFIED.
- Skybox is required; doc recommends `skybox_random`.
- Doc does **not** mention `can_gravity_wells_move`, body caps, or lane auto-connect.
- The official example mod ships `en.localized_text_csv` (a CSV variant), not `en.localized_text`. → OPEN (d).

## 2. Third-party (sins2-mapmaker) vs official — diff

| Item | Third-party | Official | Verdict |
|---|---|---|---|
| node `parent_star_id` | in its schema | **not allowed** (unevaluatedProperties false) | its export drops it; we never emit it |
| node `design_name` | missing | allowed | official wins |
| node `position` | required, exactly 2 items | optional, any length | vanilla: every node has `[x, y]` → we always emit `[x, y]` |
| chance fields | 0..1 ranges | no range | keep 0..1 as design rule only |
| scenario.uniforms | 4 arrays + `version: 1` | same 4 required + `overwrite_*` | agree |
| `.scenario` contents | scenario_info.json, galaxy_chart.json, galaxy_chart_fillings.json (`{"version":1}`), picture.png | not documented | **CONFIRMED** by vanilla (33 hand-made maps use exactly these 4) |
| home planets | filling `player_home_planet` + `ownership.player_index` | not documented | **CONFIRMED** by vanilla |
| ownable types | Terran/Desert/Ferrous/City only | not documented | **WRONG.** Every planet type is colonizable by some faction (§6.5) |
| caps | ≤15 stars, ≤100 bodies/star | none in schema | **WRONG as a hard cap.** Vanilla `public_ashred` has 102 bodies under one star |
| wormholes | `wormhole_fixture` nodes, wormhole lane must join two fixtures | enum only | **CONFIRMED** by vanilla (all 62 wormhole lanes are fixture↔fixture) |
| localized_text | flat JSON `{key: text}` at `localized_text/en.localized_text` | not documented | **CONFIRMED** format (vanilla file is flat JSON, no BOM) |
| scenario_info keys | version, name, description, desired_player_slots_configuration{player_count, team_count}, can_gravity_wells_move (false), are_player_slots_randomized, planet_counts[a,b], star_counts[a,b], has_wormholes, has_npcs, resources, map_type | not documented | **CONFIRMED** — all seen in vanilla (§6.2) |
| `.mod_meta_data` | compatibility_version 2, display_version, display_name, short_description, author, logos{large_logo, small_logo} | only compatibility_version 2 | still UNVERIFIED — no mods installed on this PC |
| "Pirate Base" mapping | `player_home_planet` with `npc_filling_name: "pirate"` | — | **CORRECT after all** — vanilla does exactly this 34 times (§6.3) |

Third-party filling names (superseded by the vanilla list in §6.4 — use that one): `random_star`, `random_{yellow,orange,red,white,neutron,blue,binary,black_hole}_star`,
`random_{terran,desert,ferrous,city,barren,volcanic,ice,swamp,crystalline,oceanic,magnetic,greenhouse,gas_giant,ship_graveyard,brown_dwarf,irradiated,shattered,uncolonizable,ice_moon,volcanic_moon,moon}_planet`,
`random_moon_planet_weighted`, `random_asteroid`, `random_dead_asteroid`, `random_asteroid_line_cluster`, `hive_asteroid`,
`wormhole_fixture`, `random_black_hole_fixture`, `random_radiation_storm_fixture`, `random_antimatter_fountain_fixture`, `player_home_planet`.

## 3. Provenance table (starts here, grows with every field we emit)

| Output item | Value | Source | Status |
|---|---|---|---|
| galaxy_chart keys | see §1 | official schema | VERIFIED |
| scenario.uniforms keys | 4 required arrays | official schema | VERIFIED |
| `.mod_meta_data.compatibility_version` | 2 | official doc | VERIFIED (doc); confirm vs installed mod |
| `:` literal-name prefix | `:My Map` | official doc | VERIFIED |
| skybox | `skybox_random` | official doc | VERIFIED (doc) |
| install / drop-in paths | `%LOCALAPPDATA%\sins2\mods\`, `...\drop_in_scenarios\` | official doc | VERIFIED |
| every filling_name | 65 node fillings (§6.4) | vanilla `galaxy_generator.uniforms` | VERIFIED |
| scenario_info.json keys | §6.2 | vanilla scenarios | VERIFIED |
| galaxy_chart_fillings.json | `{"version": 1}` | vanilla (60 of 93) | VERIFIED |
| localized_text format | flat JSON object, UTF-8, no BOM | vanilla `en.localized_text` | VERIFIED |
| npc_filling_name values | §6.3 | vanilla `npc_fillings` | VERIFIED |
| home planet node | `player_home_planet` + `ownership.player_index` (0-based) | vanilla | VERIFIED |
| wormhole shape | `wormhole_fixture` child of star, lane `type: "wormhole"` fixture↔fixture | vanilla | VERIFIED |
| star lane shape | `type: "star"` root↔root | vanilla (32/32) | VERIFIED |
| body limits | warn > 102 bodies/star, hard stop > 150, ≤ 10 stars (`[limits]` in config.toml) | vanilla max 102 + user decision | DECIDED |
| `.mod_meta_data` | `compatibility_version: 2`, `display_name`, `display_version`, `short_description`, `logos{large_logo, small_logo}` | official doc + community (third-party editor) | **official doc + community-verified, not verified against an installed mod.** Diff later against a mod.io mod. |
| picture.png | 512 × 512 PNG | vanilla (all 90 pictures in the 93 scenarios) | VERIFIED |
| pirate base node | `player_home_planet` + `ownership: {"npc_filling_name": "pirate"}` | vanilla (34 uses) | VERIFIED, DECIDED |
| ownership rule | exactly one `player_home_planet` per player, `player_index` 0..players-1; **no** planet-type restriction | vanilla `.player` files (§6.5) + user decision | DECIDED |

## 4. Checkpoint answers

- **Q11 AI model:** `claude-sonnet-5` is a current model id ($2 in / $10 out per million tokens).
  Current recommended way to get schema-bound JSON: **structured outputs** —
  `output_config: {format: ...}` (Python helper `client.messages.parse()`); tool use with `strict: true` also works.
  We use structured outputs. Model stays configurable (`MAPGEN_MODEL`).
- **Q1 (body cap):** no cap in any official schema or in vanilla. Vanilla's biggest single star holds 102 bodies
  (`public_ashred`), and `random_map_generator.uniforms` allows `planet_count` up to 500 (warning above 100).
  The "≤100 bodies/star, ≤15 stars" rule is the third-party editor's own.
  **DECIDED (2026-09-22):** warn above **102** bodies/star (proven-safe vanilla size), hard stop above **150**,
  up to **10** stars. All three are config values (`[limits]`). Our default ring design (~116 bodies) is above the
  proven-safe size, so an **in-game load test of the default map is a hard gate before any AI-layer work.**
- **Q5 (richness):** confirmed. A planet's metal/crystal comes from its entity `.unit` file (§6.4 table).
  "Rich" / "poor" / "fair" fillings are pools of planet types, so richness = which filling we pick.

### Adopted defaults (BRIEF.md §0 "Other questions", adopted 2026-09-22)
- **Q2 planet count:** 60 home + 14 border + 5 convoy + 6 core (chokepoints counted inside) + 15 filler = 100
  planets. Wormhole fixtures counted separately: 16 (5 convoys × 2 + 3 core spokes × 2).
- **Q3 convoys:** skip-3 chords as a perfect matching 0–3, 2–5, 4–7, 6–9, 8–1; one convoy per region; `--convoy-skip`.
- **Q4 convoy wiring:** homeA_edge –normal– wormhole fixture –wormhole– wormhole fixture –normal– contested planet
  –normal– homeB_edge. **Matches vanilla** (§6.3: wormhole lanes only fixture↔fixture; fixtures also carry
  normal lanes to planets, e.g. `public_agamemnons_bounty` nodes 45/46).
- **Q6 homes:** 6 planets per cluster: 1 `player_home_planet` + 5 unowned, metal-leaning.
- **Q7 core access:** regions 0, 3, 7; `--core-access`.
- **Q8 major fields:** borders 1, 4, 5, 8 (revised 2026-09-22 post-gate; was 0, 2, 5, 7).
- **Q9 filler:** 15 = 3 pirate + 12 neutral.
- **Q10 names:** localized keys + mod `en.localized_text`; `--inline-names` uses the `:` literal prefix.
- **Q11 AI model:** `claude-sonnet-5`, `MAPGEN_MODEL`, structured outputs (Step 3).
- **Resources:** tier = amount of the biased resource; XL metal/crystal reuse L; gas giant only XL balanced (core);
  at most one (R) planet per home cluster. Table in `data/fillings.json` (generated by `tools/build_fillings.py`).
  Post-gate theme (2026-09-22, BRIEF §5.3): core = gas giant + 5 crystalline (56.5 crystal); homes =
  ferrous, desert, volcanic (R), ferrous, ship graveyard (34.5 metal / 6.5 crystal). MapSpec zones carry
  optional `slot_biases[]` so one zone can mix biases.

## 5. Still open after the vanilla run
1. `.mod_meta_data`: we write the 5 keys in §3; **not verified against an installed mod**. User will install a
   mod.io mod later and we diff.
2. Fillings table (size tier × bias → filling_name): drafted, **awaiting user review** before it goes into the compiler.
   XL metal / XL crystal have no single-type vanilla planet (see draft).
- Closed: picture.png (512×512), wiki (skipped), schema source (fresh clone at `8e06103`).

## 6. Vanilla install facts (VERIFIED — source: `D:\Games\Sins of a Solar Empire II`, 2026-09-22)

### 6.1 Scenario files
- All in `<game>\scenarios\*.scenario`. Each is a plain zip.
- Hand-made maps (33) contain exactly: `galaxy_chart.json`, `galaxy_chart_fillings.json`, `picture.png`,
  `scenario_info.json`. Random maps (29) use `galaxy_chart_generator_params.json` instead of a chart.
  Tutorials add `.tutorial`; DLC story maps add `.unique_scenario` and sometimes `scenario.lua`. We emit the 4-file form.
- Vanilla `scenario.uniforms` lists 62 maps in `scenarios`, 3 in `fake_server_scenarios`, and DLC maps under
  `dlc_scenarios` / `dlc_multiplayer_scenarios` as `{product_id, scenarios[]}`.

### 6.2 scenario_info.json
Keys seen: `version` (1), `name`, `description`, `desired_player_slots_configuration{player_count, team_count}`,
`planet_counts[min,max]`, `star_counts[min,max]`, `has_wormholes`, `has_npcs`, `resources`, `map_type`,
`can_gravity_wells_move`, `are_player_slots_randomized`, `uppercase_name`, `does_scenario_track_leaderboards`.
- `resources`: `scenario_options_view_resources_{low,medium,high}`.
- `map_type`: `scenario_options_view_map_type_custom` (hand-made) or `..._generated`.
- `team_count` is 0 in every vanilla map.
- Hand-made maps use `[n, n]` for planet/star counts; `planet_counts` = non-star nodes (e.g. `face_off`: 14 nodes, 1 star → `[13, 13]`).
- Our template (from `public_face_off`):
  ```json
  {"version": 1, "name": ":My Map", "description": ":...",
   "desired_player_slots_configuration": {"player_count": 2, "team_count": 0},
   "planet_counts": [13, 13], "star_counts": [1, 1], "has_wormholes": false, "has_npcs": false,
   "resources": "scenario_options_view_resources_medium",
   "map_type": "scenario_options_view_map_type_custom"}
  ```

### 6.3 galaxy_chart.json shape
- Top: `version: 1`, `skybox` (almost always `skybox_random`), `recommended_team_count` (1), `root_nodes`, `phase_lanes`.
- Every node has `id`, `filling_name`, `position: [x, y]`. Common optional: `chance_of_loot`, `orbit_speed_scalar`,
  `rotation`, `ownership`, `loot_level`, `chance_of_{first,second}_planet_bonus`. Never seen: `design_name`.
- Hierarchy: root = star, children = planets/fixtures, depth 2 = moons. Max depth 2.
- **Home planets:** `filling_name: "player_home_planet"`, `ownership: {"player_index": N}`, N is **0-based**.
  Almost always a direct child of a star (285 of 300). One player can own several planets (same index repeated).
- **NPC planets** also use `player_home_planet`, with `ownership.npc_filling_name` (and optional `npc_filling_type`).
  Pirate base = `{"npc_filling_name": "pirate"}`.
  Valid `npc_filling_name`s (vanilla `npc_fillings`): `pirate`, `militia`, `guardian`, `alutar_sect`,
  `aluxian_resurgence`, `cot_aluxian_resurgence`, `eivonns_frigates`, `jiskun_force`, `nilari_cult`,
  `pranast_united`, `viturak_cabal`.
- **Lanes:** `{id, node_a, node_b}`; `type` omitted = normal (3,434 of 3,528). `type: "star"` only joins two
  root stars (32/32). `type: "wormhole"` only joins two `wormhole_fixture` nodes (62/62). Normal lanes may
  touch a star node directly (339 cases), but most join planets.
- **Wormholes:** `wormhole_fixture` nodes, children of a star (117) or deeper (8).
- **Coordinates:** single-star maps span roughly ±400 to ±2,200; largest map reaches ~±10,000.
  `random_map_generator` default `system_radius` = 500 (range 45–7,500).

### 6.4 Fillings and resources
65 node fillings in vanilla `galaxy_generator.uniforms`; 61 appear in vanilla maps (list: `data/fillings_seen.txt`).
Not used in any map but valid: `random_impassable_well_fixture`, `random_planet_weighted_no_city`,
`random_poor_planet_no_hive`, `random_super_rich_planet`.

Average asteroids per planet type (entity `.unit` `planet.non_random_* + random_*` midpoints):

| planet type | metal | crystal | | planet type | metal | crystal |
|---|---|---|---|---|---|---|
| ferrous | 9.5 | 0 | | swamp | 3.5 | 3.5 |
| gas_giant | 9 | 9 | | barren | 3.5 | 3.5 |
| irradiated | 7 | 7 | | ship_graveyard | 3.5 | 1.5 |
| volcanic | 7 | 0 | | terran | 3 | 2 |
| magnetic | 5.5 | 6.5 | | oceanic | 1.5 | 5 |
| asteroid / hive_asteroid | 5.5 | 3.5 | | ice_asteroid | 1.5 | 5.5 |
| desert | 5 | 5 | | city, moons, stars | 0 | 0 |
| crystalline | 0 | 9.5 | | ice | 0 | 7 |

Non-planet fixtures (clouds, storms, debris, dead asteroids) get 0.5–2 asteroids from their fixture filling.

Pools that matter for balance:
- `player_home_planet` → `random_fair_planet` = swamp / barren / ice / volcanic.
- `random_rich_planet` = irradiated, terran, desert, oceanic, crystalline, ferrous, …
- `random_super_rich_planet` = city / gas_giant / magnetic.
- `random_poor_planet` = asteroid / hive_asteroid / ice_asteroid.
- `*_near_home_planet` variants exist for rich/fair/weighted pools.

### 6.5 Who can colonize what (entity `.player` files)
Source: `<game>\entities\*.player` — for the 8 playable factions, `planet_types[]` entries with
`can_ever_be_colonized` and `colonization_research_prerequisites`; for NPCs, `simple_can_ever_be_colonized_planet_types`.
**Correction:** the third-party "only Terran/Desert/Ferrous/City can be owned" rule is wrong and is dropped from
our rules. No faction has any `can_ever_be_colonized: false` entry.
Every playable faction can colonize every planet type; some need research first.
- Free for all 4 empires (TEC/Advent/Vasari/Herald, loyalist and rebel): asteroid, ice_asteroid, hive_asteroid,
  barren, city, moon, pirate_base, ship_graveyard. Terran is free for TEC and Advent; ferrous is free for Vasari;
  desert is free for Advent; magnetic is free for Herald.
- Research-gated for most: crystalline, gas_giant, ice, irradiated, oceanic, swamp, volcanic (+ the others above).

### 6.6 Misc
- `en.localized_text`: one flat JSON object `{key: text}`, UTF-8, no BOM. Scenario UI strings
  (`scenario_options_view_resources_*`, `..._map_type_*`) live there.
- Harbinger/"rift": only `dlc3_portal_fixture` (a random fixture filling, not a node filling). No map places it.
  We do not emit it.
- `galaxy_generator.uniforms`: `max_capturable_units` 2, `min_jumps_to_any_home_planet_for_loot_level` [1, 3, 4],
  `player_phase_resonance_points` [4, 3, 2, 1].
- `random_map_generator.uniforms` ranges: players 1–10, solar systems 1–10, planets 10–500 (warn > 100),
  wormholes 0–3, pirate/guardian/enemy NPCs 0–10, moons 0–3.
- Drop-in folder exists: `%LOCALAPPDATA%\sins2\drop_in_scenarios`. Mods folder exists, empty.

## 7. Facts checked for Step 2 (VERIFIED — vanilla install, 2026-09-22)

- **Orbit lock.** Vanilla locks bodies with `orbit_speed_scalar: 0.0` (e.g. 70 of 86 in `public_buzzsaw`), and
  `public_scorched_space` (125 bodies, wormholes) adds `can_gravity_wells_move: false` in scenario_info.
  We do both, on every body.
- **Node field patterns we copy** (most common vanilla shape per node type, `public_*` maps):
  - star: `{filling_name: "random_star", chance_of_loot: 0.0}` (19)
  - player home: `chance_of_loot 0.0`, `chance_of_first_planet_bonus 0.0`, `chance_of_second_planet_bonus 0.0`,
    `ignore_orbit_overlap_checks true`, `orbit_speed_scalar 0.0` (39)
  - wormhole fixture: `ignore_orbit_overlap_checks true`, `orbit_speed_scalar 0.0` (20)
  - pirate: `ownership {npc_filling_name: "pirate"}`, `chance_of_loot 0.0` (public_agamemnons_bounty node 27)
- **`planet_counts`** is a UI label that excludes stars and wormhole fixtures
  (`public_agamemnons_bounty`: 28 nodes − 3 stars − 2 wormholes = `[23, 23]`). We write `[planets, planets]`.
- **Spacing (vanilla, single-star maps with 50+ bodies):** nearest neighbour min 54–194, median 133–293;
  normal lane length median 170–361, max 518–1612. Our geometry defaults sit inside these ranges.
- **Planet bonuses are not a resource boost.** `chance_of_{first,second}_planet_bonus` roll from a shared pool
  of 56 bonuses (`planet.uniforms.random_planet_bonuses`), many with no resource effect (acid_atmosphere,
  chaotic_weather, death_world, …). Per BRIEF §0 they stay off for XL. Game defaults when the field is
  omitted: 0.5 / 0.2 (`planet.uniforms`). We omit them on non-home planets (as most vanilla nodes do) and
  set 0.0 on homes (vanilla home pattern).
- **`.mod_meta_data.logos` values:** not documented anywhere official. We write `"picture.png"` (the mod-root
  512×512 image) for both. **Community-verified (published mods use it)** — per user, 2026-09-22; not yet
  diffed against an installed mod (see §5.1).
- Official schemas use only internal `$ref`s (`#/$defs/...`), so no cross-file resolver is needed.
- **Laneless central star.** 2 vanilla single-star maps (`public_balance_of_power`, `public_clash_of_the_titans`)
  give the star 0 lanes; the other 27 give it 2–14. Our star has no lanes (a star lane would bypass the core
  chokepoints). "Every body has ≥ 1 lane" therefore applies to child bodies, not the root star.

## 8. AI layer facts (VERIFIED — Anthropic API + docs.claude.com, 2026-09-22)

- **Structured outputs shape.** `output_config={"format": {"type": "json_schema", "schema": ...}}` on
  `client.messages.create` (GA). The older `output_format` parameter and the `structured-outputs-2025-11-13`
  beta header are superseded; the Python SDK raises `TypeError` for `output_format` on
  `beta.messages.create`. Source: docs.claude.com/en/docs/build-with-claude/structured-outputs.
- **`anyOf` allows no sibling keys.** A wire schema with `anyOf` beside `type` / `$defs` /
  `additionalProperties` at the root is rejected:
  > `400 invalid_request_error: output_config.format.schema: For 'anyOf', '$defs, additionalProperties, type' is not supported`

  So the wire root is a **bare `anyOf`** and every internal `$ref` is inlined (MapSpec is not recursive, so
  inlining terminates). Cost of learning this: one rejected request — the rejection happens **before
  inference, so it was free** (no tokens billed, `request_id` only).
- **`oneOf` is not listed as supported** (only `anyOf` / `allOf`), so `oneOf` is used for local validation
  only. Branch exclusivity survives on the wire because each branch requires its own key with
  `additionalProperties: false`.
- **Unsupported keywords** (400 if sent): `minimum`, `maximum`, `multipleOf`, `minLength`, `maxLength`,
  array constraints beyond `minItems` of 0 or 1, `additionalProperties` other than `false`, recursive
  schemas, external `$ref`. `pattern` IS supported for simple regexes. We strip the unsupported ones into
  `description` text and enforce the real constraints locally (`mapgen/ai/schemas.py:strict_schema`).
- **`anthropic.transform_schema` (SDK 1.8.0) cannot process our schema**: it raises
  `ValueError: Schema must have a 'type', 'anyOf', 'oneOf', or 'allOf' field` on `$ref` nodes. We try it
  first and fall back to our own stripper; which path ran is logged per call in `out/ai_log.jsonl` as
  `wire_schema_source`.
- **Documented limits** (combined across all strict schemas in a request): 20 strict tools, 24 optional
  parameters, 16 union-typed parameters. Our wrapper is well inside these; a test asserts it.
- **Invalid-output cases to handle:** `stop_reason: "refusal"` and `stop_reason: "max_tokens"` may both
  return output that does not match the schema (200 OK, billed). `client.py` raises on both.
- **First live call** (2026-09-22, `claude-sonnet-5`): 11,985 in + 3,398 out = $0.058, 34s, branch A.
  It exposed two bugs of ours, not the model's: `place_core` crashed on an ungated centre zone with no
  chokepoint links, and `COUNT_CONVOYS` assumed the ring template's "one convoy per region" for every
  spec. Both fixed; `specs/six_ring_center.mapspec.json` pins that exact shape as a test fixture.

### 8.1 Prompt trim experiment (2026-09-22, 7 live calls, $0.386)

**Question:** the ring few-shot is ~6,100 of the ~9,600 prompt tokens. Is it load-bearing, or is it just
cost? Ran 3 requests x 2 variants (A = all three few-shots, B = duel + oil, no ring), then one
verification call. Raw responses and specs: `out/prompt_experiment*.json`, `out/prompt_experiment/`.

| request | A: all three | B: no ring |
|---|---|---|
| gated core 8p/80 | 12,006 in / 5,687 out, $0.081, 17 rule errors | 5,907 in / 8,221 out, $0.094, clean |
| contested centre 6p/60 | 11,985 in / 3,228 out, $0.056, clean | **invalid MapSpec** (semantic) |
| convoys 10p/110 | 12,010 in / 5,629 out, $0.080, 10 rule errors | **invalid MapSpec** (semantic) |

**Result: the trim was wrong, and the instinct behind it (shorter prompt = cheaper) was wrong too.**
- Dropping the ring example saved ~6,100 input tokens but cost ~2,500 **more output** tokens: without a
  compact example to imitate, the model writes longer specs. Output is **5x** the price of input
  ($10 vs $2 per MTok), so the short prompt was **more expensive per call** ($0.094 vs $0.081/$0.056).
- B produced **structurally invalid MapSpecs on 2 of 3 requests** (failed semantic validation, e.g. the
  `size_tiers` length convention). A was always schema-valid.
- Keep all three few-shots. Prompt length is not the lever; output length is.

**What the experiment actually found:** A's failures were all home-cluster rules
(`HOME_RESEARCH_GATED`, `HOME_TIER_BIAS` on every home). The rules were stated but not concrete enough.
Adding one line - the safe home recipe `size_tiers ["L","M","M","L","S"]` with
`slot_biases ["metal","balanced","metal","metal","metal"]` - took the same 8p/80 gated request from
**17 rule errors to 0**, builds clean, and output tokens fell 5,687 -> 4,993 ($0.081 -> $0.074).

**Also settled:** gating was never missed. Both variants gated correctly when asked (3 chokepoints, 3
chokepoint links) and correctly left a "contested centre" ungated. The earlier suspicion came from a
`describe.py` demo run with a different request string, plus mocked fixtures in `ai_log.jsonl` - only
one real call had been made at that point.

### 8.2 Real session economics (2026-09-22, claude-sonnet-5, $2 in / $10 out per MTok)

First live chat session: **6 calls, $0.6301**, 3 requests each needing one repair round, mod built at
`out/eastern_front_2024`.

| call | in | out | cost |
|---|---|---|---|
| request 1 | 11,987 | 6,669 | $0.091 |
| repair 1 | 16,290 | 7,641 | $0.109 |
| request 2 | 12,023 | 9,816 | $0.122 |
| repair 2 | 16,533 | 5,130 | $0.084 |
| request 3 | 12,033 | 8,415 | $0.108 |
| repair 3 | 12,224 | 9,123 | $0.116 |

- **$0.06-$0.12 per call**; a finished map with one repair is ~$0.10-0.25.
- **A repair round costs about as much as the first attempt.** The model rewrites the whole spec rather
  than a patch, and the previous spec is resent in the conversation, so input grows (12k -> 16.5k) while
  output stays large. Repairs are not a cheap tail.
- **Vague requests cost more.** A precise request ("6 players, 60 planets, ring, one contested center")
  cost $0.056 with 3,228 output tokens; open-ended chat requests ran 6,600-9,800 output tokens at
  $0.09-$0.12, because a full redesign rewrites every zone.
- **Caching covers only the ~4.4k-token system block.** The few-shots and the spec ride in `messages`
  and are resent every round, so cache savings are modest. Marking the last few-shot turn with
  `cache_control` would extend the cached prefix - untested, worth doing if volume grows.
- Cheapest lever found so far is not a shorter prompt (§8.1) but a spec that passes first time: the safe
  home recipe removed a whole repair round on the 8p/80 request.

### 8.3 Militia is not a map-placed NPC (VERIFIED)

`npc: militia` was removed from the MapSpec enum rather than implemented.
- **No vanilla map ever assigns militia ownership to a node.** Across all 93 scenarios, node
  `ownership` uses `npc_filling_name` pirate / jiskun_force / aluxian_resurgence / viturak_cabal /
  pranast_united / cot_aluxian_resurgence, or bare `npc_filling_type` friendly_faction / enemy_faction.
  Militia appears **0 times** (162 npc-owned nodes checked).
- Militia is a property of the **filling**, not of ownership: 36 `fixture_fillings` carry
  `militia_supply` (e.g. `irradiated_planet` [125, 135], `barren_planet` [80, 90]), so every planet
  already comes with militia defenders sized by its type. A `militia` entry exists in `npc_fillings` but
  no node filling references it.
- Implementing it would have meant inventing a node pattern vanilla never uses, against the "never
  guess" directive. If militia-owned planets are wanted later, it needs an in-game test first.

### 8.4 First-attempt correctness beats every cost optimisation tried

Three attempts to make the AI layer cheaper, in order of what actually worked:

| change | result |
|---|---|
| **Safe home recipe** (one line of concrete guidance) | 8p/80 gated request: **17 rule errors -> 0**, builds first time, output 5,687 -> 4,993 tokens, $0.081 -> $0.074. Removes a whole ~$0.08 repair round. |
| **Prompt trim** (drop the ring few-shot, ~6,100 input tokens) | **More expensive**: output grew ~2,500 tokens at 5x the price, and 2 of 3 requests produced structurally invalid specs (S8.1). |
| **Skill path** (no API at all) | 40-planet map written and built with no repair round, $0. |

The lever is **the right tokens, not fewer tokens**. A repair round costs about as much as the first
attempt (S8.2), so anything that makes the first attempt correct pays for itself immediately, while
shaving input tokens is second-order at best and backfired when it cost the model its worked example.

## 9. Solar Forge (Stardock's editor) — PARTIALLY VERIFIED

Source: `C:\dev\refs\sins2modtools\SolarForge\bin\` (sparse-checkout widened to include it, 45 MB),
plus `docs/solar_forge.md`. **Static inspection only — the GUI round-trip has NOT been run** (this
session cannot drive a Windows GUI; see the test plan below).

### What it is (VERIFIED by inspection)
- `SolarForge.exe` is a .NET WinForms front end over `Solar.dll`, the game's own C++ core (42 MB, contains
  `solar::galaxy_chart`, `solar::scenario_info`, `solar::galaxy_chart_node`, `map_preview_window::render_phase_lanes`).
  It reads and writes scenarios with the **same code the game uses**, which makes it the authority our
  validator only approximates.
- It has a real scenario editor: `scenarioEditorControl`, `galaxyChartEditorControl`, `galaxyChartTreeControl`
  (node tree), `scenarioViewportControl` (2D map view), `scenarioInfoPropertyGrid` / `scenarioPropertyGrid`
  (field editors), `galaxyChartGeneratorControl` (the random generator), `galaxyChartPosition`.
- Load/save exist in both shapes: `LoadScenarioFromFile` / `LoadScenarioFromFolder` and
  `SaveScenarioToFile` / `SaveScenarioToFolder` / `SaveScenarioToFolderAs`, with
  `BrowseToAndLoadScenarioFolder` and an `openScenarioFolderToolStripMenuItem` menu item.
- ⚠ **No zip-handling strings in the exe.** The folder path is the one the UI advertises, so the safe
  move is to open an *unpacked* scenario folder rather than our `.scenario` zip. An unpacked copy of the
  AI-generated map is ready at `out/solarforge_test/eastern_front_2024/`.
- `SolarForge/bin/NodeGraphics/*.png` holds an icon per filling name (`random_ferrous_planet.png`,
  `player_home_planet.png`, …) — useful reference art if our preview ever wants real icons.

### What it should let you edit (from the control names, UNVERIFIED)
Node tree and 2D viewport (so: select, move, add and delete nodes), per-node property grid (filling
name, ownership, chances, orbit fields), scenario_info fields, and phase lanes. Effectively everything
our compiler emits, at the *node* level rather than the zone level.

### Round-trip test plan (for a human, ~5 minutes)
1. Run `C:\dev\refs\sins2modtools\SolarForge\bin\SolarForge.exe`.
2. Point its data sources at the Sins2 install (`D:\Games\Sins of a Solar Empire II`) if it asks.
3. Open the scenario **folder** `C:\dev\sins2-mapgen\out\solarforge_test\eastern_front_2024\`
   (File → open scenario folder). If it also accepts the `.scenario` file directly, note that.
4. Move one planet, save to the same folder.
5. `generate_map.py validate out\solarforge_test\eastern_front_2024`
   (add `--loose-members` if Solar Forge leaves extra files behind).

**If it round-trips cleanly**, Solar Forge is a legitimate *final polish* step: generate with this tool,
nudge by hand in the editor, validate, ship. The cost is reproducibility — a hand-edited chart no longer
matches its MapSpec, so a rebuild from the spec discards the edits, and the spec stops being the source
of truth for that map. Treat it as a one-way finishing move on a finished map, never as a step in an
iteration loop, and keep the edited scenario under `out/` with its spec beside it.

### 9.1 Solar Forge cannot load this game build (BLOCKED 2026-09-23)

The round-trip test could not run. Solar Forge fails during core-engine setup before any scenario is
opened, with `json read errors in ...\uniforms\unit_tag.uniforms  unused keys : [ item_access_tags ]`
and two "Found errors while setting up the core engine" dialogs.

**Cause: the editor is older than the game.**

| | |
|---|---|
| installed game | `sins2.exe` dated **2026-09-03** |
| sins2modtools / Solar Forge | commit `8e06103`, **"Update to 1.61.3", 2026-07-07** |
| newer commit available? | **No** - `origin/main` is still `8e06103` |

`setupErrors.log` (3,467 lines) shows Solar Forge failed to fully parse **656 game files**. Its embedded
`Solar.dll` rejects keys it does not know, and the September game build added a whole Corruption feature
plus other fields the July toolchain has never seen:

| unknown key | occurrences |
|---|---|
| `corruption` (+ `corruption_add_value`, thresholds, modes, …) | 471 across all corruption keys |
| `shroud_restricted_max_track_levels` | 168 |
| `population`, `industry` | 115 |
| `required_item_access_tags` / `item_access_tags` | 59 |
| sunset/lightning render keys | ~270 |

**This is not caused by anything we emit** - it fails on Stardock's own `uniforms/*.uniforms` before any
scenario is loaded, so our `.scenario` files are not implicated.

**Options, in order:**
1. **Wait.** `git -C C:\dev\refs\sins2modtools pull` when a new Sins II patch lands; Stardock ships Solar
   Forge with the modtools. Nothing to do on our side.
2. **Point Solar Forge at the older Epic install** `F:\Program Files\Epic Games\SinsII` (2025-04-25).
   Verified: that build contains **none** of the three offending keys, and **all 11 node fillings our
   maps use** exist in it, so a chart round-trip would still be a valid test of read/write fidelity. It
   may instead complain about fields the newer editor expects and the old build lacks - untested.
3. **Skip it.** Our validator already checks the chart against the official schema, the vanilla key sets
   and the rule set, and the maps load in game. Solar Forge was only ever a "final polish" nicety.

Until it can load, the §9 claims about its editor (node tree, viewport, property grids, folder
load/save) remain **inspected-but-unverified**.

## 10. Opening-balance measurements (MEASURED — three_rings, 2026-09-24)

Source: `mapgen/compiler.py` + BFS over the compiled lane graph, core gates excluded. These are
measurements of our own output, not vanilla facts.

**The middle ring was never the problem.** All ten `mid_*` zones compile to exactly 12.0 crystal
(M/crystal = `random_ice_planet` 7.0 + S/crystal = `random_oceanic_planet` 5.0). An earlier report
blamed the 20.0-35.0 two-hop spread on randomised tier x bias fill inside those zones; that was
wrong. The real causes were **link ordering in `free_pair` and unsectored gap placement**.

**Why the wrong diagnosis was dangerous rather than merely wrong.** The proposed fix - pin the
tier/bias composition of every `mid_*` zone - would have *appeared* to work. It touches the same
two-hop window, so the printed numbers would have shifted, and pinning a composition that was
already uniform would have looked like a successful change. The 12.0 term was already flat, so the
real 1.5-6.5 and 0.0-10.0 terms would have survived untouched, and the map would have carried a
seed-dependent opening edge behind a fix that looked applied. This is the same failure as
REGION_ADVANTAGE_STACK returning clean on an empty input set: **check what the rule or the metric
is actually reading before changing what it reports.** Decompose the measurement by source first;
only then fix. Both incidents are why `BALANCE_RULE_BLIND` exists.

The spread decomposed as:

| term | before | cause |
|---|---|---|
| own zone | 6.5 everywhere | even already |
| middle ring | 12.0 everywhere | even already |
| neighbour home | 1.5 / 5.0 / 6.5 | `free_pair` takes the nearest still-free pair, so once earlier links consumed a zone's planets a later link landed on a different one - link **order**, not design |
| filler / pirate | 0.0 / 3.5 / 5.0 / 10.0 | `free_spot_clusters` scattered gap planets into any free spot; a seed could drop 10 crystal on one doorstep and none on six others |

Three fixes, all gated on `shape == "concentric"` so the frozen ring and the clusters maps cannot
move (re-verified byte-identical against `out/ring_baseline.json`):

1. `sector_plan` / `free_spot_in_sector` - every angular sector gets the same gap-planet count +/- 1,
   the remainder placed by `rng.sample` so it is never always sector 0. Which planet lands in which
   sector, and where inside it, stays random.
2. `attach_gaps` excludes home-zone planets from the anchor set on concentric: a drifter does not
   dock next to a capital.
3. `wire` uses a fixed slot (`eligible(...)[0]`) for home-to-home lanes on concentric.

**Result: 6.5 crystal at 1 hop and 18.5 at 2 hops, identical for all ten players, on every seed
tested (3, 11, 42, 7, 99).** Spread 0.0. Locked by `tests/test_concentric.py`. Divergence resumes at
3 hops (spread 17.0) and 4 hops (24.5), which is the contested midgame and is meant to vary.

Hops from each home to the nearest core chokepoint are **4-6** (`home_0/3/7` = 4, `home_5` = 6):
three gates on a ten-vertex ring at slots 0/3/7 leave gaps of 3, 4, 3, so slot 5 is two steps from
both. Kept deliberately - it is legible to a player, and evening it out would need a 9- or
12-vertex inner ring. `max_region_hop_spread = 2` in `config.toml` is set so this sits exactly at
tolerance and does not fire; `REGION_HOP_SPREAD` does fire on `ww2_rimward_front` (4-12) and
`ww2_global` (2-8), both pre-existing and previously unmeasured.

### 10.1 `--ungate-core` is known broken (MEASURED, 2026-09-24 — flag now refuses to run)

`tools/make_concentric.py --ungate-core` claimed "no gates: garrison planets and pirates defend the
core instead". It does neither. Measured on the map it generated:

| claim | reality |
|---|---|
| garrison planets defend the core | `random_city_planet` count on the whole map: **0**. The ungated branch emits `zone("core", "core", ["L"] * 5, B, ...)` and never adds garrison types. |
| pirates defend the core | the `core_pirates` zone uses `{"kind": "gap"}`, so it scatters map-wide like any other filler. Measured radii **806, 806, 2532, 3425** against a core at **432** and a map outer radius of 3434 - one pirate sat on the far rim at 100% of map radius. |

Net effect: five large `random_irradiated_planet` at the centre, 4-6 hops from every home, defended
by nothing but their own militia. Both `REGION_HOP_SPREAD` and `BALANCE_RULE_BLIND` correctly go
silent on it - there are no gated zones left to police - so nothing in the rule set flags it either.

**The flag now exits 1 with this explanation and writes no spec.** Same discipline as the dead enum
audit: a flag that silently does something other than what its help says is worse than one that
stops. Fixing it properly means giving the core zone explicit garrison planets and anchoring the
pirates to the centre instead of the gap pool; not done, not scheduled.

### 10.2 Inner-ring arcs (MEASURED, 2026-09-24 — `--inner-arcs 3` applied)

| | lateral inner lanes | arcs | core gates per arc | worst inner-to-inner trip | hops to gate |
|---|---|---|---|---|---|
| `--inner-arcs 1` (full ring) | 10 | one ring of 10 | [3] | 5 hops | 4-6 |
| `--inner-arcs 2` | 8 | [0,6,7,8,9] / [1,2,3,4,5] | [2, 1] | 8 hops | 4-6 |
| **`--inner-arcs 3`** (default) | 7 | [0,8,9] / [1,2,3] / [4,5,6,7] | **[1, 1, 1]** | 8 hops | 4-6 |

The gaps fall on the spoke vertices (0, 3, 7), so each arc is a wedge owning exactly one core
entrance. **Cutting the inner ring does not change core access**: the route to a gate is radial
(`home_i -> mid_i -> inner_i -> gate`) and never runs around the ring, so hops stay 4-6 in all three
settings, and 1- and 2-hop crystal stays 6.5 / 18.5. What it changes is the lateral traverse, 5 hops
to 8 - closing the "lap the inner ring and hit anyone's rear" route. `--inner-arcs 2` costs the same
traverse for a lopsided 2/1 gate split, so 3 is the default.

### 10.3 Role fillings carried no asteroids (FIXED 2026-09-25)

`data/fillings.json` recorded `metal`/`crystal` for every tier x bias entry but **nothing for the
roles**, and `fillings.role()` returned the `Resolved` defaults of `(0, 0)`. So the compiler stored
zero asteroids on every player home, every pirate planet and every garrison chokepoint, and every
"crystal reachable" table we have produced understated the map.

**`player_home_planet` is not one planet.** It resolves to `random_fair_planet`, a weighted roll the
**game** performs at load:

| outcome | probability | metal | crystal |
|---|---|---|---|
| `swamp_planet` | 15% | 3-4 | 3-4 |
| `barren_planet` | 25% | 3-4 | 3-4 |
| `ice_planet` | 30% | 0 | **6-8** |
| `volcanic_planet` | 30% | **6-8** | 0 |
| **range / mean** | | [0, 8] / 3.5 | [0, 8] / **3.5** |

An earlier note in this session claimed it resolved to `swamp_planet`; that was wrong - it read
`items[0]` of a four-item filling. The expected value happens to land on the same 3.5, but the
**variance is the finding**: 30% of homes roll `volcanic` and start with *zero* crystal asteroids
while another 30% roll `ice` and start with 6-8. That swing is decided by the game's RNG per node,
not by anything we emit, and it is larger than any imbalance the layout work removed.

Because the range's midpoint (4.0) is not the weighted mean (3.5), `Resolved` and `Node` now carry
`expected_metal` / `expected_crystal` beside the range, and every aggregate uses `Node.crystal_mean`
/ `metal_mean`. The range is still what the inspector shows per node, because "crystal 0-8" is the
truth for a home planet.

**What changed in the three_rings tables** (seed 3, the committed map):

| | 1 hop | 2 hops | 3 hops | 4 hops |
|---|---|---|---|---|
| crystal, old -> new | 6.5 -> **10.0** | 18.5 -> **22.0** | 46.5-63.5 -> 59.0-77.5 | 98.0-128.0 -> 119.0-159.5 |
| spread, old -> new | 0.0 -> **0.0** | 0.0 -> **0.0** | 17.0 -> 18.5 | 30.0 -> **40.5** |

Map total crystal 357.5 -> 445.0 (+35.0 across 10 homes, +52.5 across 15 pirates).

**The uniformity claim holds only where it was tested.** At 1 and 2 hops the error was exactly
uniform - every home gained 3.5 and the spread stayed 0.0 - so every region comparison made at
opening range remains valid. At 3 and 4 hops it was **not** uniform, because pirate planets also
carry 3.5 expected crystal each and they are scattered unevenly: the 4-hop spread was really 40.5,
not the 30.0 reported. Midgame comparisons made before today understated the imbalance.

Emitted mod bytes are unchanged for all six baseline maps - asteroid counts live in the game's
entity files, never in `galaxy_chart.json`, so this is an accounting fix only.

## 11. Crystal economy model (MEASURED — vanilla install, 2026-09-25)

### 11.0 READ THIS BEFORE QUOTING ANY HOP TABLE

**A player's home planet is a dice roll the engine makes at load, and it swings wider than anything
our layout controls.** `player_home_planet` resolves to `random_fair_planet`:

| outcome | probability | crystal asteroids |
|---|---|---|
| `ice_planet` | **30%** | **6-8** |
| `volcanic_planet` | **30%** | **0** |
| `barren_planet` | 25% | 3-4 |
| `swamp_planet` | 15% | 3-4 |

Two players in the same game, on identically-built home zones, can open with **0 and 8** crystal
asteroids. That is a swing of +-6 around the 3.5 mean, worth up to ~190 crystal/min once extractors
are up. Every spread our layout work removed is smaller than this.

**Therefore: no fairness claim derived from the hop tables can ever mean "every player has an equal
opening."** It means "every player has an equal *map*". The tables are correct and worth keeping -
they are the part we control - but they describe the board, not the game. We cannot fix this from a
MapSpec: the roll is performed by the game from a vanilla filling, and pinning a specific planet
would mean emitting a non-`player_home_planet` filling as a home, which is not a thing we do.

### 11.1 Rates (all per second; see the unit cross-check below)

| quantity | value | source |
|---|---|---|
| asteroid extraction | 0.40/s per asteroid (Advent crystal 0.48, Vasari metal 0.48) | `<player>.asteroid_extraction_rates` |
| home population | 500 | `normal_start_mode.home_planet_starting_population` |
| mining lvl 1, swamp/barren/terran/desert | 0.0015 crystal per population | `planet_types[].tracks.mining` |
| mining lvl 1, ice/crystalline | 0.0036 crystal per population | same |
| mining **lvl 0** | **empty block - no income at all** | same |
| civilian structure slots by logistics lvl | 0 / 4 / 7 / 9 | `planet_types[].tracks.logistics` |
| planet level upgrade prices (crystal) | 25, 50, 75, 100, 125, ... over 30 levels | `planet_levels[].upgrade_price` |
| starting bank (normal) | TEC 6500/1650/**850**, Advent 6000/1500/**1750**, Vasari **0**/4800/**6000** | `normal_start_mode` |

**Unit cross-check.** A home starts at commerce level 3: `credits_income_rate_per_population` 0.035
x 500 population = 17.5. If that is per second it is 1,050 credits/min, one 300-credit light frigate
every 17 seconds - the observed pace. If it were per minute it would be one frigate every 17
*minutes*, which no build order could sustain. The rates are per second.

### 11.2 A new colony produces nothing until you pay for it

Logistics level 0 grants **0 civilian structure slots**, so no extractor can be built, and mining
level 0 is an empty block, so there is no population income either. A colony costs the coloniser
(TEC 50 crystal) plus two planet levels (25 + 50) = **125 crystal before it yields a single unit**.
Expansion is crystal-negative first, then pays back.

### 11.3 Income and the 25-minute balance (TEC)

| configuration | crystal/min |
|---|---|
| home alone | **129** (45 from population, 84 from 3.5 asteroids) |
| home + 2 developed colonies | 407 |
| home + 4 developed colonies | 635 |

| | min 10 | min 15 | min 20 | min 25 | runs dry |
|---|---|---|---|---|---|
| home only | +1502 | +1634 | +1554 | +1349 | **never** |
| home + 2 | +2087 | +3611 | +4923 | +6110 | **never** |
| home + 4 | +2087 | +3714 | +5699 | +8026 | **never** |

Cumulative crystal spend on a full curve (8 labs, both tier-1 and tier-2 domains, 5 colonies, planet
levels, fleet) is **2,979** over 25 minutes, against 3,225 of home-only income plus the 850 bank.

**Robustness.** Colony population is engine-side and not in the JSON; it is modelled at 200. At
*zero* population income everywhere, home asteroids alone still give 2,100 over 25 minutes against
2,979 of spend - roughly break-even, not a stall. The conclusion does not rest on the assumption.

**Why.** Crystal spend is dominated by research, and research is **time-gated, not resource-gated**:
60s per subject, and tier acquire times of 15 / 75 / 150 / 300 / 600s. You cannot buy it fast enough
to drain the bank.

### 11.4 Per faction, and what actually binds

| faction | bank | crystal/min | 25-min crystal spend | balance |
|---|---|---|---|---|
| TEC | 850 | 357 | 2,979 | **+4,119** |
| Advent | 1,750 | 428 | 5,204 | **+4,043** |
| Vasari | 6,000 | 357 | 4,650 | **+7,598** |

Advent pay more for everything (labs 90, extractors 75 crystal *each*, tier-1 400) but extract 20%
faster and bank twice as much; it nets out level with TEC. **Vasari have no commerce track at all**
(one empty level - zero credit income, ever), which is why they bank 6,000.

**Crystal is not the constraint.** For TEC the binding resource is **credits**: 17,000 available
against 14,665 spent in the first ten minutes, 16% headroom, versus 111% headroom on crystal -
roughly seven times tighter. For Vasari it is **metal**: their 25-minute metal balance is the only
figure in the model that goes negative (-498).

### 11.5 Consequence for map design

Crystal placement is a weak lever; zero-crystal homes would change nothing that matters. The
resource that scales with map design is **population**, which comes from **planet count**, and
planet count feeds credits, metal and crystal alike. A map creates economic pressure by limiting how
many planets a player can safely hold - which is what the hop geometry already does - not by moving
crystal around.

## 12. What limits holding planets (MEASURED — vanilla install, 2026-09-25)

### 12.0 Expansion cannot be made self-limiting by the map

**`max_supply` is a flat research ladder that ignores planet count.** 100 -> 250 -> 500 -> 1000 ->
1500 -> 2000, gated on `trader_max_supply_0..4` (`<player>.max_supply.levels`). A player holding 20
planets has exactly the same fleet cap as one holding 3.

**There is no upkeep, maintenance or per-planet cost anywhere in the data.** Every `uniforms` file
and the player definition were searched for keys containing `planet_count`, `per_planet` and
`owned_planet`. The only hits are the colonisation victory condition
(`colonization_victory_planet_count_percentage`), AI heuristics, `artifact_to_planet_count_ratio`
and map generation. `maintenance_cost_rates` exists on every planet type and is `[]` for all 21.

**Planet levels escalate within a planet while a new planet starts cheap.** `planet_levels`
upgrade prices run 25, 50, 75, 100, 125 ... 350 crystal over 30 levels. Taking a fresh planet to
level 2 costs 75 crystal; taking an existing planet from level 9 to 10 costs 250. Going wide is
strictly cheaper per unit of return than going tall, and research tiers reinforce it - they need
1/3/6/10/15 research points, points come from labs, labs occupy per-planet civilian slots.

**So "more planets is always better" is baked in, and the map has no cost to attach to.** The only
thing the map controls is the ratio of **places to defend** against **one fixed-size fleet**.

The single brake in the data: a fresh colony is inert. Level 0 gives 0 civilian structure slots, 0
military structure slots, and mining level 0 is an empty block - no income, no buildings, no
defence until planet levels are paid.

### 12.1 Distance is free. Lane length is not a design lever.

| | |
|---|---|
| hyperspace speed | **215,000 units/s** (`speed_between_stars` 752,500) |
| charge time | **8.0s** (+/- 1.0 variance) |
| three_rings longest lane | 2,580 units = **0.012s** of travel |
| crossing the whole map | 6,869 units = **0.032s** of travel |

**Response time is `8s x hops`, and nothing else.** Lane length, `radius_scale` and all spacing work
have **zero** gameplay effect - the WW2 "wide" variant at 1.8x spacing plays identically to the
original in every travel sense.

**Long lanes were proposed as a way to make distant planets hard to defend. They are not one, and
nobody should reach for that lever again.** The two levers that do work are **approaches per
planet** (how many lanes a defender must cover) and **hop count** (how long one fleet takes to
respond). Cutting the inner ring into three arcs raised the worst lateral traverse from 5 hops to 8,
which is 24 real seconds of defender response time - that one did work.

### 12.2 The cost of holding ground

| | credits | metal | crystal | notes |
|---|---|---|---|---|
| starbase | 2,000 | 585 | 415 | **limit 1 per planet**, 4 per star, 180s build |
| gauss defense | 750 | 150 | 125 | needs defense track >= 1 for any military slot |
| autocannon defense | 500 | 150 | 50 | |
| hangar defense | 500 | 100 | 75 | |
| phase jump inhibitor | 750 | 200 | 300 | |
| garrison | | | | tier-1 unlock 700/100/125, and `garrison.base_max_supply` is **0**, so the tier-2 `trader_garrison_max_supply` (1200/200/300) is required before any garrison exists |

Against an expansion cost of a colony frigate (450/100/50) plus ~75 crystal of planet levels.
**Holding a planet costs roughly 4-8x what taking it cost**, and every defensive option is
research-gated while expansion is not.

Defense track military structure slots by level: **0 / 5 / 15 / 30 / 50**.
Logistics civilian structure slots by level: **0 / 4 / 7 / 9**.

### 12.3 OPEN: does `virtual_supply_cost` consume the fleet cap?

Every structure carries a `virtual_supply_cost` - starbase **200**, most structures **10**,
extractors **5** - while carrying `build.supply_cost: 0`. Ships are the mirror image: a real
`build.supply_cost` (scout 2, light frigate 5, heavy cruiser 15, capital ship 50) and
`virtual_supply_cost: 0`. The complementary shape suggests it is a strength valuation for AI threat
assessment, not a draw on the player's supply pool.

**This is not settled.** `unit-schema.json` types it as a bare integer with no description, and no
`uniforms` file references it. The semantics are engine-side.

**It matters enormously.** If structures do consume supply, a 5-planet player running 20 extractors
spends **100 supply - the entire starting fleet cap** - and §12.0 is wrong: expansion would carry a
steep, automatic military cost and would be self-limiting after all.

**The exact test (in game, ~30 seconds):** note the supply readout, build two resource extractors,
look at the readout again. A drop of 10 means structures consume supply and this section needs
rewriting; no change means the conclusion above stands.

### 12.4 Economic fairness was bought with defensive fairness (2026-09-25)

On 2026-09-24 the two-hop crystal spread was flattened to **0.0** by pinning every home-to-home lane
to `eligible(zone)[0]`, because `free_pair` took the nearest still-free pair and so which neighbour
planet you could see from your capital depended on link **order** rather than on the design.

It worked, and it quietly cost something nothing measured. Pinning both ring lanes to slot 0 also
funnelled entrances onto that planet:

| | gateways per home | busiest single gateway |
|---|---|---|
| before (nearest free pair) | 2,2,2,2,2,2,2,2,2,3 - mean **2.1** | max 4 |
| after the fixed-slot fix | 1,1,1,2,2,2,2,2,3,3 - mean **1.9** | max **5** |

**home_0, home_4 and home_7 ended up with all five external lanes on one planet** - one starbase
held a zone that should have cost three. Every rule in the set measured resources or distance; none
measured how many places a defender has to cover, so the regression was invisible while the
improvement it paid for was reported in a table.

**The fix keeps both.** Ring lanes between neighbouring capitals stay pinned to slot 0 - that pin is
what holds the opening flat - and *everything else* (mid-ring lanes, the wormhole) is placed
least-loaded-first, so slot 0 carries exactly the two ring lanes and the other two planets carry the
rest. Gated on `shape == "concentric"`; the six baseline maps are byte-identical.

| three_rings | before | after |
|---|---|---|
| gateways per home | 1-3 (mean 1.9) | **3-3 (uniform)** |
| busiest single gateway | 5 | **2** |
| planets with 6+ approaches | 5 (max 7) | **0 (max 5)** |
| 1-hop crystal spread | 0.0 | **0.0** |
| 2-hop crystal spread | 0.0 | **2.0** |
| defender response | 3 hops / 24s | 3-4 hops / 24-32s |
| lanes / bodies | 164 / 113 | **164 / 113** |

The residual 2.0 band at two hops is the honest price: a home's two mid-ring lanes can land on two
oceanic planets (5.0 each) or on an ice and an oceanic (7.0 + 5.0). Removing it would mean pinning
those lanes too, which brings single-gateway home zones straight back. Two hops is now asserted as a
**bound**, not an identity, in `tests/test_concentric.py`.

**`GATEWAY_SPREAD`** (new rule, a tightening) warns when comparable zones - same kind, same planet
count - differ by more than one in distinct entrance planets. It found a real pre-existing imbalance
on the installed WW2 maps the moment it was added: **italy and turkey have one entrance each while
spain has three.**

**The lesson, again.** A fix that improves a measured quantity can degrade an unmeasured one, and
the report will look like pure progress. Both times this has happened the unmeasured quantity was
the one the map is actually about. When a change buys an improvement, ask what it spent.
