# sins2-mapgen

Generates Sins of a Solar Empire II scenarios (maps) and a complete, loadable mod folder. Local Windows
Python 3.12 tool. **BRIEF.md is the source of truth**; FINDINGS.md holds provenance for every value we emit.

## Two ways to drive it
**Path A (default, no API cost): the `sins2-map` skill in this Claude Code session.** Ask for a map,
write a MapSpec, build it with `build --spec`, repair violations, show the summary. No key, no per-call
charge beyond the Claude subscription. Prefer this unless the user asks for the CLI.

**Path B (opt-in, pay per call): `ai` / `ai --chat`** with the user's own key in `.env`. Same pipeline,
the translation just happens over the API instead of in this session. Costs money per call - never start
it on the user's behalf without them asking.

Templates and spec files (`build`, `build --spec`) underlie both and need no key at all.

**The AI writes specs; the compiler writes game files.** The model only ever produces a MapSpec
(`schemas/mapspec.schema.json`: abstract roles and tiers, no filling names, ids or coordinates). Every
byte that reaches the game comes from the compiler, and the same rules and schema validation apply on
both paths. Never hand-edit anything under `out/`.

The model cannot buy a pass by weakening a rule: the limits and rule functions are fingerprinted at the
start of a repair run and re-checked before any result is returned, and their source hashes are pinned in
`tests/test_rule_fingerprints.py`.

## Setup
```
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy config.example.toml config.toml     # then edit game_dir / schema_dir; [limits] holds body limits
copy .env.example .env                   # only needed for `ai` / `ai --chat`
```
`.env` holds `ANTHROPIC_API_KEY` (and optionally `MAPGEN_MODEL`, default `claude-sonnet-5`). It is
gitignored and never logged. Without it, `build` and the `sins2-map` skill still work.

## Sources
- Official schemas: StardockCorp/sins2modtools sparse clone at `schema_dir`, commit `8e061033` (never copied here).
- Vanilla install at `game_dir` (read-only; `tools/inspect_vanilla.py` copies references into `data/reference/`).
- `data/fillings.json` is generated from the vanilla `.unit` / `.player` files by `tools/build_fillings.py`.
- BVisagie/sins2-mapmaker: hints only (AGPL; no code copied; several of its rules proved wrong).

## The hop tables describe the board, not the game
`player_home_planet` is `random_fair_planet` - the **engine** rolls it at load: ice 30% (6-8
crystal asteroids), volcanic 30% (**0**), barren 25% and swamp 15% (3-4 each). Two players on
identically-built home zones can open with 0 and 8. That +-6 swing is larger than any spread the
layout controls, and a MapSpec cannot touch it. So an even crystal table means **every player has
an equal map**, never "an equal opening" - say it that way. Crystal is also not the binding
resource: credits bind ~7x tighter for TEC, metal for Vasari, and no player runs dry of crystal
inside 25 minutes even sitting on their home planet. FINDINGS.md §11 has the model; don't
re-derive it.

## Commands
```
.venv\Scripts\python generate_map.py build --template ring --players 10 --planets 100 --seed 42 --name ww2_rimward_front --display-name "WW2: Rimward Front"
.venv\Scripts\python generate_map.py build --spec specs\ww2_rimward_front.mapspec.json
.venv\Scripts\python generate_map.py build --params my_params.json --preview-only
.venv\Scripts\python generate_map.py build ... --install          # copy to %LOCALAPPDATA%\sins2\mods\<name>
.venv\Scripts\python generate_map.py validate out\ww2_rimward_front
.venv\Scripts\python generate_map.py install out\ww2_rimward_front
.venv\Scripts\python generate_map.py inspect out\<name>          # read-only map inspector (localhost)
.venv\Scripts\python generate_map.py inspect                      # no path: re-run the vanilla inspector
.venv\Scripts\python -m pytest -q
```
Ring knobs: `--players`, `--planets`, `--convoy-skip`, `--core-access 0,3,7`, `--inline-names`, or any
`MapParams` field via `--params file.json`. Output: `out/<name>/` (mod), `out/<name>_preview.png`,
`out/<name>.mapspec.json`.

## Path B: the `ai` CLI (opt-in, costs money)
```
.venv\Scripts\python generate_map.py setup                          # store a key in .env, hidden input
.venv\Scripts\python generate_map.py ai "eight players on a ring, 80 planets, rich core behind three chokepoints"
.venv\Scripts\python generate_map.py ai "..." --seed 7 --dry-run     # describe, write nothing
.venv\Scripts\python generate_map.py ai --chat
```
Guardrails: each call prints an estimate and asks first (`--yes` skips), the session stops at
`--max-cost` (default $1.00), and `--max-repair-rounds 0..3` caps repair spend. With no key found, `ai`
exits with instructions rather than a stack trace. `MAPGEN_MODEL` picks the model; only
`claude-sonnet-5` has been tested, so cheaper models are unverified and may cost more through extra
repair rounds.
A request is translated to a MapSpec, compiled, and rule-checked. On a violation the codes and hints go
back to the model, at most 3 repair rounds. If a request is genuinely ambiguous the model returns
questions and nothing is built.

**Every round's spec is kept** at `out/repair_rounds/<name>__round<N>.mapspec.json`, including the
failing pre-repair one - that is the spec worth having when you later ask why something broke. The final
spec also lands in `out/<name>.mapspec.json`.

Chat commands - **all local, none of them call the API**:

| command | does |
|---|---|
| `/preview` | render `out/<name>_preview.png` |
| `/summary` | what was actually built, from the compiled graph |
| `/diff` | changes since the previous spec |
| `/undo` | step back through spec history |
| `/save` | write `specs/<name>.mapspec.json` |
| `/build` | build and validate the mod folder |
| `/install` | build, then copy into the game's mods folder |
| `/seed N` | change the seed and recompile |
| `/help`, `/quit` | list commands; leave (prints the session total) |

Only plain text spends tokens. Every call is logged to `out/ai_log.jsonl` with tokens, cost and the
running session total.

### What it costs (real numbers, 2026-09-22, claude-sonnet-5 at $2/$10 per MTok)
- **$0.06-$0.12 per call.** A first attempt is ~12k input; the reply is 3k-10k output, and output is
  where the money goes.
- **A repair round costs about as much as the first attempt** (the whole spec is resent and rewritten),
  so a request that needs one repair costs roughly double. Budget ~$0.10-0.25 per finished map.
- **Vague requests cost more than precise ones**: a full redesign rewrites every zone. "6 players, 60
  planets, ring, one contested center" cost $0.056; open-ended chat requests ran $0.09-$0.12.
- A whole chat session of 3 requests with a repair each came to **$0.63**.
- Prompt caching only covers the ~4.4k-token system block; the few-shots and the spec are resent every
  round, so caching saves less than the numbers above might suggest.

## Solar Forge round-trip (hand-positioning a finished map)
```
.venv\Scripts\python generate_map.py unpack out\<name>                  # -> out/solarforge_test/<name>
                                                                        # Forge: File -> open scenario FOLDER
.venv\Scripts\python generate_map.py pack out\solarforge_test\<name> --into out\<name> --install
```
Solar Forge has no zip handling, so it opens an unpacked folder while the game loads the
`.scenario` zip (FINDINGS §9). `pack` validates the folder before writing, keeps the previous
scenario as `.scenario.bak`, and re-validates the mod after. The trip is byte-lossless - member
bytes are copied exactly, only the zip envelope is ours - and a test asserts it.

**It is a one-way finishing move.** A hand-edited chart no longer matches its MapSpec, so
`build --spec` discards the edits. Forge also rewrites more than you touch: on three_rings it moved
75 of 114 nodes and rewired 49 lanes out / 48 in on a single save.

## Loading in game
Copy `out/<name>/` to `%LOCALAPPDATA%\sins2\mods\<name>\`, then Modding → Local → Enable → Manage →
Apply Changes, then pick the map in skirmish. To reload while iterating: disable → apply → enable → apply.

## Path A: the sins2-map skill (default, no API key)
`.claude/skills/sins2-map/` does the same job inside Claude Code: it writes a MapSpec, builds it with
`generate_map.py build --spec`, repairs violations, and asks before installing. Use it when you do not
want to spend API tokens.

**Read `specs/skill_test_quad.mapspec.json` first** - it is the minimal worked example, 40 planets on a
4-player ring with no wormholes and nothing gated, written and built through the skill with no repair
round. `specs/ww2_rimward_front.mapspec.json` is the full 10-player design once you need convoys, a
gated core and chokepoints.

## After a game patch
Re-run `generate_map.py inspect` and `tools/build_fillings.py`, `git pull` the schemas, re-run the tests.

## Troubleshooting
- "Mod Compatibility Version: 0" → bad `.mod_meta_data`.
- Stray lanes in game → an unlinked planet or orbit drift (we lock orbits; check LANE_MISSING).
- Map missing from the list → name in `uniforms/scenario.uniforms` does not match the `.scenario` filename.
