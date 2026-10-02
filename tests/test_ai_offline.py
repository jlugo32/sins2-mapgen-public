"""Mocked AI-layer tests (BRIEF S3 "Offline tests"). No API call except the opt-in live one.

Cases:
  1. a valid spec builds
  2. a schema-invalid spec triggers one re-ask, then fails
  3. CHOKEPOINT_BYPASS is repaired by the loop
  4. an unresolvable spec stops after 3 rounds and presents options
  5. an ambiguous request surfaces clarifying questions and builds nothing
  plus: exhaustion keeps the closest spec, the questions branch spends one call, and commands in chat
  mode never call the API.
"""
import json
import types

import pytest

from mapgen import rules
from mapgen.ai.client import SESSION, AIError
from mapgen.ai.repair import MAX_ROUNDS, assert_rules_unchanged, repair, spec_diff
from mapgen.params import MapParams
from mapgen.spec import Link
from mapgen.templates import build_ring


class FakeClient:
    """Replays canned answers; counts calls and keeps the messages it was sent."""

    def __init__(self, answers, repeat_last=True):
        self.answers = list(answers)
        self.repeat_last = repeat_last
        self.calls = 0
        self.sent: list[list[dict]] = []

    @property
    def messages(self):
        return types.SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls += 1
        self.sent.append(kw["messages"])
        answer = self.answers.pop(0) if len(self.answers) > 1 or not self.repeat_last else self.answers[0]
        body = answer if isinstance(answer, str) else json.dumps(answer)
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text=body)],
            stop_reason=kw.get("_stop", "end_turn"),
            usage=types.SimpleNamespace(input_tokens=11000, output_tokens=3000,
                                        cache_read_input_tokens=10000))


@pytest.fixture
def good(cfg):
    return build_ring(MapParams(), cfg.limits.max_bodies_per_star)


@pytest.fixture
def bypassed(cfg):
    spec = build_ring(MapParams(), cfg.limits.max_bodies_per_star)
    spec.links.append(Link("filler", "core", "normal"))       # back door into the gated core
    return spec


# --------------------------------------------------------------------------- 1
def test_valid_spec_builds_first_time(good, cfg):
    client = FakeClient([{"spec": good.to_dict(), "assumptions": ["ten regions on a ring"]}])
    res = repair("ten player ring", cfg.limits, MapParams(), client=client)
    assert res.ok and client.calls == 1
    assert len(res.rounds) == 1 and res.assumptions == ["ten regions on a ring"]
    assert [v.code for v in rules.errors(res.violations)] == []


# --------------------------------------------------------------------------- 2
def test_schema_invalid_answer_reasks_once_then_fails(good, cfg):
    bad = good.to_dict()
    bad["zones"][0]["filling_name"] = "random_ferrous_planet"   # MapSpec has no such field
    client = FakeClient([{"spec": bad}], repeat_last=True)
    res = repair("ten player ring", cfg.limits, MapParams(), client=client, max_rounds=1)
    assert not res.ok and res.spec is None
    assert client.calls == 2, "one first attempt plus exactly one re-ask"
    assert all(r.error for r in res.rounds)
    assert "MapSpecResponse schema" in res.rounds[0].error
    resent = res.rounds[1].violations          # the full schema errors are what we send back
    assert resent and "Additional properties" in resent[0] and "filling_name" in resent[0]


# --------------------------------------------------------------------------- 3
def test_chokepoint_bypass_is_repaired(bypassed, good, cfg):
    client = FakeClient([{"spec": bypassed.to_dict()}, {"spec": good.to_dict()}], repeat_last=False)
    res = repair("ring with a gated core", cfg.limits, MapParams(), client=client)
    assert res.ok and client.calls == 2 and len(res.rounds) == 2
    sent = res.rounds[1].violations
    assert any("CHOKEPOINT_BYPASS" in v for v in sent)
    assert any("hint:" in v for v in sent)
    assert res.rounds[1].changes == ["link removed: filler -> core [normal]"]
    # the model was told about it in its own vocabulary: zone ids, never node ids
    repair_turn = client.sent[1][-1]["content"]
    assert "CHOKEPOINT_BYPASS" in repair_turn and "zones: core" in repair_turn
    assert "node 83" not in repair_turn


# --------------------------------------------------------------------------- 4
def test_unresolvable_spec_stops_after_three_rounds(bypassed, cfg):
    client = FakeClient([{"spec": bypassed.to_dict()}])           # never fixes it
    res = repair("ring with a gated core", cfg.limits, MapParams(), client=client)
    assert not res.ok
    assert client.calls == MAX_ROUNDS + 1 == 4, "first attempt plus three repairs"
    assert len(res.rounds) == 4
    assert res.spec is not None, "the closest spec is kept so the caller can offer options"
    assert [v.code for v in rules.errors(res.violations)] == ["CHOKEPOINT_BYPASS"]
    assert res.cost > 0 and res.cost_lines()[-1].startswith("session total:")


# --------------------------------------------------------------------------- 5
def test_ambiguous_request_asks_and_builds_nothing(cfg):
    client = FakeClient([{"clarifying_questions": ["How many players?", "Should the centre be gated?"]}])
    res = repair("make me a good map", cfg.limits, MapParams(), client=client)
    assert res.asked and res.spec is None and res.compiled is None
    assert client.calls == 1, "asking costs one call and stops"
    assert len(res.questions) == 2 and not res.ok


# --------------------------------------------------------------------------- guards
def test_repair_never_loosens_a_rule(good, cfg, monkeypatch):
    client = FakeClient([{"spec": good.to_dict()}])
    import mapgen.rules as rules_mod

    real_check = rules_mod.check

    def weakened(m, chart, limits):                      # a rule that quietly drops every error
        return [v for v in real_check(m, chart, limits) if v.severity != "error"]

    res = repair("ten player ring", cfg.limits, MapParams(), client=client)
    assert res.ok
    monkeypatch.setattr(rules_mod, "check", weakened)
    with pytest.raises(AIError, match="engine rules or limits changed"):
        assert_rules_unchanged(cfg.limits, (cfg.limits.warn_bodies_per_star, cfg.limits.max_bodies_per_star,
                                            cfg.limits.max_stars, real_check.__code__.co_code,
                                            rules_mod.engine_rules.__code__.co_code,
                                            rules_mod.design_rules.__code__.co_code,
                                            rules_mod.balance_rules.__code__.co_code))


def test_refusal_and_max_tokens_raise(good, cfg):
    for stop in ("refusal", "max_tokens"):
        client = FakeClient([{"spec": good.to_dict()}])
        client.create = lambda **kw: types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text="{}")], stop_reason=stop,
            usage=types.SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0))
        with pytest.raises(AIError):
            repair("x", cfg.limits, MapParams(), client=client)


def test_spec_diff_reports_only_real_changes(good, cfg):
    same = build_ring(MapParams(), cfg.limits.max_bodies_per_star)
    assert spec_diff(good, same) == ["(no structural change)"]


# --------------------------------------------------------------------------- chat mode
def test_chat_commands_never_call_the_api(good, cfg, tmp_path):
    from rich.console import Console
    from mapgen.ai.chat import Chat
    client = FakeClient([{"spec": good.to_dict(), "assumptions": ["a"]}], repeat_last=False)
    chat = Chat(cfg=cfg, params=MapParams(), console=Console(width=100, no_color=True),
                client=client, out_root=tmp_path, specs_dir=tmp_path)
    chat.handle("ten player ring")
    assert client.calls == 1 and chat.spec is not None
    before = client.calls
    for command in ("/diff", "/summary", "/preview", "/seed 7", "/undo", "/save", "/build", "/help"):
        assert chat.handle(command) is True
    assert client.calls == before, "commands must be local"
    assert chat.handle("/quit") is False


def test_chat_undo_restores_the_previous_spec(good, cfg, tmp_path):
    from rich.console import Console
    from mapgen.ai.chat import Chat
    chat = Chat(cfg=cfg, params=MapParams(), console=Console(width=100, no_color=True),
                client=FakeClient([{"spec": good.to_dict()}], repeat_last=False),
                out_root=tmp_path, specs_dir=tmp_path)
    chat.handle("ten player ring")
    seed_before = chat.spec.meta.seed
    chat.handle("/seed 4242")
    assert chat.spec.meta.seed == 4242
    chat.handle("/undo")
    assert chat.spec.meta.seed == seed_before and not chat.history


# --------------------------------------------------------------------------- opt-in live test
@pytest.mark.live
def test_live_translate_builds(cfg):
    """Opt in with: pytest -m live   (spends tokens)."""
    from mapgen.ai.repair import repair as live_repair
    res = live_repair("four players, 40 planets, ring, no wormholes", cfg.limits, MapParams(), seed=1)
    assert res.ok or res.asked
    if res.ok:
        assert len(res.compiled.planets()) == res.spec.constraints.total_planets
    assert SESSION.calls >= 1


def test_every_round_spec_is_saved_including_the_failing_one(bypassed, good, cfg, monkeypatch, tmp_path):
    """The pre-repair spec is the one worth keeping: it is what broke."""
    import mapgen.ai.repair as repair_mod
    monkeypatch.setattr(repair_mod, "ROUNDS_DIR", tmp_path / "repair_rounds")
    client = FakeClient([{"spec": bypassed.to_dict()}, {"spec": good.to_dict()}], repeat_last=False)
    res = repair_mod.repair("ring with a gated core", cfg.limits, MapParams(), client=client)
    assert res.ok
    saved = sorted(p.name for p in (tmp_path / "repair_rounds").glob("*.mapspec.json"))
    name = good.meta.name
    assert saved == [f"{name}__round1.mapspec.json", f"{name}__round2.mapspec.json"]
    from mapgen.spec import load
    failing = load(tmp_path / "repair_rounds" / f"{name}__round1.mapspec.json")
    assert any(l.from_zone == "filler" and l.to_zone == "core" for l in failing.links), \
        "round 1 must be the spec that still had the bypass"
    fixed = load(tmp_path / "repair_rounds" / f"{name}__round2.mapspec.json")
    assert not any(l.from_zone == "filler" and l.to_zone == "core" for l in fixed.links)
