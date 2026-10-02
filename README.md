# sins2-mapgen

Generate **Sins of a Solar Empire II** maps: a complete, loadable mod folder built by a deterministic
compiler, from a template, a spec file, or a plain-English description.

Windows, Python 3.12. Every value written into a game file traces back to the official schemas or to the
vanilla install - see [FINDINGS.md](FINDINGS.md).

## Two ways to drive it

### Path A - the Claude Code skill (recommended, no API cost)

Open this repo in **Claude Code** and ask for a map. The `sins2-map` skill
([.claude/skills/sins2-map](.claude/skills/sins2-map/SKILL.md)) writes a MapSpec, builds it, repairs any
rule violations and shows you the summary and preview.

> "Build me a 6-player ring map, 60 planets, with a rich core behind two chokepoints."

**No API key. No per-call cost** beyond whatever Claude subscription you already have. This is the
default path and the one the project is tuned for. The worked example it produces is
[specs/skill_test_quad.mapspec.json](specs/skill_test_quad.mapspec.json) - 40 planets, built first try.

### Path B - the `ai` CLI (opt-in, pay per call, bring your own key)

The same translation done through the Anthropic API instead of your Claude Code session, for scripting
or for running outside Claude Code.

```
.venv\Scripts\python generate_map.py setup          # store your key in .env (hidden input)
.venv\Scripts\python generate_map.py ai "eight players, 80 planets, rich core behind three chokepoints"
.venv\Scripts\python generate_map.py ai --chat      # REPL that edits the current map
```

**What it costs** (measured, `claude-sonnet-5` at $2 in / $10 out per MTok):

| | |
|---|---|
| one call | **$0.06 - $0.12** |
| a repair round | about the same as a first attempt - the whole spec is rewritten and resent |
| a finished map (one repair) | ~$0.10 - $0.25 |
| a real 6-call chat session | **$0.63** |

Guardrails are on by default: every call prints its estimated cost and asks before sending, the session
stops at `--max-cost` (default $1.00), and `--max-repair-rounds 0..3` caps repair spend. `--yes` skips
the prompts for scripts. Every call is logged with tokens and cost to `out/ai_log.jsonl`.

`MAPGEN_MODEL` selects the model (default `claude-sonnet-5`). A cheaper model will cost less per call -
**only `claude-sonnet-5` has been tested**, so output quality on smaller models is unverified, and a
model that gets specs wrong more often can cost more overall through extra repair rounds.

### Neither path phones home

Nothing is sent anywhere except, on Path B, to Anthropic's API. There is no telemetry, no server of
ours, and nothing is uploaded to the author of this repo. Your API key is written only to `.env`, which
is git-ignored, never printed and never logged. On Path A, the request never leaves your Claude Code
session.

## Setup

```
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy config.example.toml config.toml
```

Then edit `config.toml`:

- `game_dir` - your Sins II install (read-only; we copy reference files out of it, never write into it).
- `schema_dir` - **the official schemas are not included in this repo.** They are Stardock's and
  proprietary. Clone them yourself and point at the folder:
  ```
  git clone --filter=blob:none --sparse https://github.com/StardockCorp/sins2modtools
  cd sins2modtools && git sparse-checkout set json_schemas docs
  ```
  Validation is done against that clone by path; no schema file is ever copied into this repo or into a
  built mod.
- `[limits]` - body limits (warn above 102, refuse above 150, at most 10 stars).

`data/reference/` holds files copied out of your game install by `tools/inspect_vanilla.py`. It is
git-ignored and must stay that way: those are Stardock's files, not ours to redistribute.

## Building

```
.venv\Scripts\python generate_map.py build --template ring --players 10 --planets 100 --seed 42
.venv\Scripts\python generate_map.py build --spec specs\skill_test_quad.mapspec.json
.venv\Scripts\python generate_map.py validate out\<name>
.venv\Scripts\python generate_map.py install out\<name>     # copies into %LOCALAPPDATA%\sins2\mods
```

Output: `out/<name>/` (the mod), `out/<name>_preview.png`, `out/<name>.mapspec.json`.

### Looking at a map

```
.venv\Scripts\python generate_map.py build ... --open     # open the labelled preview when done
.venv\Scripts\python generate_map.py inspect out\<name>   # read-only inspector on localhost
```

The preview PNG labels every node with its id and zone, colours by role, draws wormhole lanes dashed,
rings chokepoints and marks each cluster's home planet.

The **inspector** serves a local read-only page: hover a node for its zone, role, tier, bias, resolved
filling name and asteroid ranges; click it for its lanes and the rules that touch it; click a zone to
highlight its planets and links; and read the region tables and current rule findings beside the map.
It never edits or saves anything, and nothing leaves your machine. `inspect` with no path re-runs the
vanilla game-files inspector instead.

To load in game: copy `out/<name>/` to `%LOCALAPPDATA%\sins2\mods\<name>\`, then
Modding → Local → Enable → Manage → Apply Changes, and pick the map in skirmish.

## How it works

```
description ──► MapSpec ──► compiler ──► rules ──► schema validation ──► mod folder
  (you, or       (roles &     (ids,       (engine    (official Draft
   a model)       tiers)       lanes,      + design    2020-12 + vanilla
                               positions)  rules)      key diff)
```

**Whatever writes the spec, the compiler writes the game files.** A model never emits a `filling_name`,
a node id or a coordinate - the schema rejects them. Rule violations mean no output at all, and the
rules cannot be weakened to make a map pass: their source hashes are pinned in
`tests/test_rule_fingerprints.py` and re-checked at runtime during repairs.

- [BRIEF.md](BRIEF.md) - the design and every decision made, in order.
- [FINDINGS.md](FINDINGS.md) - provenance: which game file or schema every emitted value comes from.
- [CLAUDE.md](CLAUDE.md) - working notes for Claude Code sessions.

## Status

Verified in game: the default 10-player ring map loads and plays (10 slots, 116 bodies, no lag over 2+
hours). AI-generated maps pass schema and rule validation; the first ones have been built but not yet
play-tested. Only the `ring` layout is implemented.

## Licence and third-party material

Our code is MIT (see [LICENSE](LICENSE)). That covers this repository's own source only.

- **Stardock schemas and game files are not included** and not ours to license. You supply your own copy
  of both.
- **BVisagie/sins2-mapmaker** (AGPL) was read as a reference for how another tool models Sins maps.
  **No code was copied from it**, and several of its rules turned out to be wrong when checked against
  vanilla files (see FINDINGS §2). This project shares no source with it.
- Built mods contain only generated content plus the names you choose.
