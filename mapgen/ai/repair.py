"""Repair loop: compile, check, send the violations back, at most 3 rounds.

Engine rules are never loosened. Only the spec changes: the limits, the rule set and the compiler are
identical on every round, and `assert_rules_unchanged` proves it before the result is returned.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .. import ROOT, rules
from ..compiler import CompileError, CompiledMap, compile_spec, to_galaxy_chart
from ..config import Limits
from ..params import MapParams
from ..spec import MapSpec, SpecError
from . import prompts
from . import client as _client
from .client import AIError, Usage
from .translate import Translation, translate

MAX_ROUNDS = 3
ROUNDS_DIR = ROOT / "out" / "repair_rounds"


def save_round(spec: MapSpec, number: int) -> None:
    """Keep every round's spec, including the failing one: that is the run worth having later."""
    try:
        ROUNDS_DIR.mkdir(parents=True, exist_ok=True)
        spec.save(ROUNDS_DIR / f"{spec.meta.name}__round{number}.mapspec.json")
    except OSError:                       # never let bookkeeping break a run
        pass


@dataclass
class Round:
    number: int
    violations: list[str] = field(default_factory=list)   # problems sent INTO this round
    spec: MapSpec | None = None
    changes: list[str] = field(default_factory=list)      # diff against the previous round's spec
    error: str | None = None                              # schema or compile failure
    usage: "Usage | None" = None


@dataclass
class RepairResult:
    spec: MapSpec | None = None
    compiled: CompiledMap | None = None
    violations: list[rules.Violation] = field(default_factory=list)
    rounds: list[Round] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.spec is not None and not rules.errors(self.violations)

    @property
    def asked(self) -> bool:
        return bool(self.questions)

    @property
    def cost(self) -> float:
        """What this repair run cost, separate from the session total."""
        return sum(r.usage.cost for r in self.rounds if r.usage)

    def cost_lines(self) -> list[str]:
        out = [f"round {r.number}: ${r.usage.cost:.4f} "
               f"({r.usage.input_tokens} in + {r.usage.output_tokens} out"
               f"{f', {r.usage.cache_read_tokens} cached' if r.usage.cache_read_tokens else ''})"
               for r in self.rounds if r.usage]
        out.append(f"this run: {len([r for r in self.rounds if r.usage])} call(s) = ${self.cost:.4f}")
        out.append(_client.SESSION.line())
        return out

    def summary_lines(self) -> list[str]:
        out: list[str] = []
        for r in self.rounds:
            head = f"round {r.number}: " + ("first attempt" if not r.violations
                                            else f"{len(r.violations)} problem(s) sent back")
            out.append(head + (f" -> {r.error}" if r.error else ""))
            out += [f"    in:  {v}" for v in r.violations]
            out += [f"    fix: {c}" for c in r.changes]
            if r.usage:
                out.append(f"    {r.usage.line()}")
        return out


def violation_lines(m: CompiledMap, violations: list[rules.Violation]) -> list[str]:
    """Rule failures in the model's own vocabulary: codes, hints and zone ids, never node ids."""
    out = []
    for v in rules.errors(violations):
        zones = sorted({m.nodes[i].zone for i in v.node_ids
                        if 0 <= i < len(m.nodes) and m.nodes[i].zone})
        where = f" [zones: {', '.join(zones)}]" if zones else ""
        out.append(f"{v.code}: {v.message}{where} | hint: {v.hint}")
    return out


def spec_diff(before: MapSpec, after: MapSpec) -> list[str]:
    """Readable diff between two specs, for the repair log and for chat /diff."""
    out: list[str] = []
    b_zones = {z.id: z for z in before.zones}
    a_zones = {z.id: z for z in after.zones}
    for zid in sorted(set(b_zones) - set(a_zones)):
        out.append(f"zone removed: {zid}")
    for zid in sorted(set(a_zones) - set(b_zones)):
        z = a_zones[zid]
        out.append(f"zone added: {zid} ({z.kind}, {z.planet_count} planets)")
    for zid in sorted(set(a_zones) & set(b_zones)):
        b, a = b_zones[zid], a_zones[zid]
        for fld in ("kind", "planet_count", "size_tiers", "slot_biases", "resource_bias",
                    "internal_links", "gated", "chokepoints", "loot", "npc", "owner_player"):
            if getattr(b, fld) != getattr(a, fld):
                out.append(f"zone {zid}.{fld}: {getattr(b, fld)} -> {getattr(a, fld)}")
        if (b.placement.kind, b.placement.slot, b.placement.zones) != \
           (a.placement.kind, a.placement.slot, a.placement.zones):
            out.append(f"zone {zid}.placement: {b.placement.kind}{b.placement.zones or ''} -> "
                       f"{a.placement.kind}{a.placement.zones or ''}")

    def key(l):
        return (l.from_zone, l.to_zone, l.lane, l.chokepoint)
    b_links, a_links = {key(l) for l in before.links}, {key(l) for l in after.links}
    for f, t, lane, ch in sorted(b_links - a_links):
        out.append(f"link removed: {f} -> {t} [{lane}{'/chokepoint' if ch else ''}]")
    for f, t, lane, ch in sorted(a_links - b_links):
        out.append(f"link added: {f} -> {t} [{lane}{'/chokepoint' if ch else ''}]")
    for fld in ("total_planets", "max_bodies_per_star", "symmetric"):
        if getattr(before.constraints, fld) != getattr(after.constraints, fld):
            out.append(f"constraints.{fld}: {getattr(before.constraints, fld)} -> "
                       f"{getattr(after.constraints, fld)}")
    for fld in ("players", "seed", "name", "display_name"):
        if getattr(before.meta, fld) != getattr(after.meta, fld):
            out.append(f"meta.{fld}: {getattr(before.meta, fld)} -> {getattr(after.meta, fld)}")
    return out or ["(no structural change)"]


def check(spec: MapSpec, limits: Limits, params: MapParams) -> tuple[CompiledMap, list[rules.Violation]]:
    m = compile_spec(spec, params.geometry)
    return m, rules.check(m, to_galaxy_chart(m), limits)


def _fingerprint(limits: Limits) -> tuple:
    return (limits.warn_bodies_per_star, limits.max_bodies_per_star, limits.max_stars,
            limits.max_region_hop_spread,
            rules.check.__code__.co_code, rules.engine_rules.__code__.co_code,
            rules.design_rules.__code__.co_code, rules.balance_rules.__code__.co_code,
            rules.spacing_rules.__code__.co_code, rules.proximity_rules.__code__.co_code,
            rules.gateway_rules.__code__.co_code)


def assert_rules_unchanged(limits: Limits, before: tuple) -> None:
    """The loop may never buy a pass by relaxing a limit or dropping a rule."""
    if _fingerprint(limits) != before:
        raise AIError("engine rules or limits changed during the repair loop; refusing the result")


def repair(request: str, limits: Limits, params: MapParams, seed: int | None = None, client=None,
           max_rounds: int = MAX_ROUNDS) -> RepairResult:
    """Translate, then compile / check / re-ask until it passes or the rounds run out.

    Returns the last spec it produced even when it never passed, so the caller can show the closest
    attempt and the outstanding violations.
    """
    fingerprint = _fingerprint(limits)
    res = RepairResult()
    messages = prompts.messages(request, seed)
    previous: MapSpec | None = None
    pending: list[str] = []

    for number in range(1, max_rounds + 2):        # first attempt, then up to max_rounds repairs
        rnd = Round(number=number, violations=list(pending))
        try:
            translation: Translation = translate(
                request, limits, seed=seed, client=client, messages=messages,
                label="translate" if number == 1 else f"repair-{number - 1}")
        except SpecError as exc:
            rnd.error = str(exc).splitlines()[0]
            res.rounds.append(rnd)
            pending = [str(exc)]
            if number > max_rounds:
                break
            messages = messages + [
                {"role": "assistant", "content": "(response rejected by the MapSpec schema)"},
                {"role": "user", "content": prompts.repair_message(pending)}]
            continue

        if translation.reply:
            rnd.usage = translation.reply.usage
        if translation.asked:
            res.questions = translation.questions
            res.rounds.append(rnd)
            return res

        spec = translation.spec
        rnd.spec = spec
        save_round(spec, number)
        res.assumptions = translation.assumptions
        if previous is not None:
            rnd.changes = spec_diff(previous, spec)

        try:
            m, violations = check(spec, limits, params)
        except CompileError as exc:
            rnd.error = str(exc)
            res.rounds.append(rnd)
            pending = [f"COMPILE_ERROR: {exc} | hint: the spec compiles to an impossible layout; "
                       f"change zone placement or counts"]
        else:
            res.spec, res.compiled, res.violations = spec, m, violations
            res.rounds.append(rnd)
            pending = violation_lines(m, violations)
            if not pending:
                assert_rules_unchanged(limits, fingerprint)
                return res

        previous = spec
        if number > max_rounds:
            break
        messages = messages + [
            {"role": "assistant", "content": json.dumps({"spec": spec.to_dict()}, sort_keys=True)},
            {"role": "user", "content": prompts.repair_message(pending)}]

    assert_rules_unchanged(limits, fingerprint)
    return res
