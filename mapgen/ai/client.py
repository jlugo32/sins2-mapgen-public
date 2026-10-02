"""Anthropic client: structured outputs, usage and cost logging.

The API key comes from ANTHROPIC_API_KEY in .env (gitignored) and is never printed or logged.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import ROOT

DEFAULT_MODEL = "claude-sonnet-5"
# Rough shape of a reply, used only to estimate cost before a call (real sessions: 3k-10k output).
ESTIMATED_OUTPUT_TOKENS = 6000
CHARS_PER_TOKEN = 3.6

KEY_HELP = "\n".join([
    "No Anthropic API key found.",
    r"  - Set one up:  .venv\Scripts\python generate_map.py setup",
    "  - Or set ANTHROPIC_API_KEY in your environment.",
    "  - Or skip the API entirely: drive the sins2-map skill from Claude Code. It needs no key and",
    "    costs nothing beyond your Claude subscription (README.md, 'Path A').",
])
# USD per million tokens. Override with MAPGEN_PRICE_IN / MAPGEN_PRICE_OUT when prices or model change.
PRICES = {"claude-sonnet-5": (2.0, 10.0)}
LOG_PATH = ROOT / "out" / "ai_log.jsonl"


def env_path() -> Path:
    """Where the key lives. MAPGEN_ENV_PATH exists so tests never touch the real .env."""
    return Path(os.environ.get("MAPGEN_ENV_PATH") or (ROOT / ".env"))


class AIError(Exception):
    pass


class BudgetExceeded(AIError):
    pass


@dataclass
class Policy:
    """Spend guardrails for the API path. The skill path never touches this."""
    max_cost: float = 1.00          # per process
    assume_yes: bool = False        # --yes skips the per-call confirmation
    confirm: object = None          # callable(prompt) -> bool; input() by default

    def ask(self, question: str) -> bool:
        if self.assume_yes:
            return True
        if self.confirm is not None:
            return bool(self.confirm(question))
        import sys
        if not sys.stdin or not sys.stdin.isatty():
            raise AIError("a cost confirmation needs a terminal. Re-run with --yes to accept each "
                          "call's cost up front (and --max-cost to cap the session).")
        return input(question).strip().lower() in ("", "y", "yes")


POLICY = Policy()


@dataclass
class Usage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    stop_reason: str | None = None
    seconds: float = 0.0

    @property
    def cost(self) -> float:
        pin, pout = PRICES.get(self.model, (float(os.environ.get("MAPGEN_PRICE_IN", 0)),
                                            float(os.environ.get("MAPGEN_PRICE_OUT", 0))))
        return self.input_tokens / 1e6 * pin + self.output_tokens / 1e6 * pout

    def line(self) -> str:
        return (f"{self.model}: {self.input_tokens} in + {self.output_tokens} out"
                f"{f' ({self.cache_read_tokens} cached)' if self.cache_read_tokens else ''} "
                f"= ${self.cost:.4f}, {self.seconds:.1f}s, stop_reason={self.stop_reason}")


@dataclass
class Reply:
    raw_text: str
    data: dict
    usage: Usage
    request: dict = field(default_factory=dict)


@dataclass
class Session:
    """Running totals for this process, so a chat session can show what it has spent."""
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost: float = 0.0

    def add(self, u: Usage) -> None:
        self.calls += 1
        self.input_tokens += u.input_tokens
        self.output_tokens += u.output_tokens
        self.cache_read_tokens += u.cache_read_tokens
        self.cost += u.cost

    def line(self) -> str:
        return (f"session total: {self.calls} call(s), {self.input_tokens} in + {self.output_tokens} out"
                f"{f' ({self.cache_read_tokens} cached)' if self.cache_read_tokens else ''} "
                f"= ${self.cost:.4f}")


SESSION = Session()


def model_name() -> str:
    return os.environ.get("MAPGEN_MODEL", DEFAULT_MODEL)


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path())
    except ImportError:
        pass


def find_key() -> str | None:
    """An existing ANTHROPIC_API_KEY wins; otherwise .env is loaded."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    _load_env()
    return os.environ.get("ANTHROPIC_API_KEY")


def make_client():
    key = find_key()
    if not key:
        raise AIError(KEY_HELP)
    from anthropic import Anthropic
    return Anthropic(api_key=key)


def estimate(system: str, messages: list[dict], schema: dict) -> tuple[int, float]:
    """(input tokens, USD) for the next call. Characters/3.6 is close enough to warn on."""
    chars = len(system) + sum(len(m["content"]) for m in messages) + len(json.dumps(schema))
    tokens = int(chars / CHARS_PER_TOKEN)
    pin, pout = PRICES.get(model_name(), (float(os.environ.get("MAPGEN_PRICE_IN", 0)),
                                          float(os.environ.get("MAPGEN_PRICE_OUT", 0))))
    return tokens, tokens / 1e6 * pin + ESTIMATED_OUTPUT_TOKENS / 1e6 * pout


def log(entry: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def call(client, system: str, messages: list[dict], schema: dict, max_tokens: int = 16000,
         label: str = "translate") -> Reply:
    """One structured-outputs call.

    Uses output_config.format with type "json_schema" (GA; the old output_format beta parameter and its
    beta header are superseded). The system prompt and the few-shot turns are cache-marked, so repeat
    calls in a session pay less: the schema is constant, so it does not invalidate the cache.
    """
    model = model_name()
    tokens, est = estimate(system, messages, schema)
    if SESSION.cost + est > POLICY.max_cost:
        raise BudgetExceeded(
            f"stopping: this call is estimated at ${est:.3f} and the session has spent "
            f"${SESSION.cost:.3f}, which would pass the ${POLICY.max_cost:.2f} limit. "
            f"Raise it with --max-cost, or use the no-cost skill path (README 'Path A').")
    print(f"next call: ~{tokens} input tokens, estimated ~${est:.3f} "
          f"(session so far ${SESSION.cost:.3f} of ${POLICY.max_cost:.2f})")
    if not POLICY.ask("  proceed? [Y/n] "):
        raise AIError("cancelled before the call; nothing was sent and nothing was spent")
    t0 = time.time()
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=messages,
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    usage = Usage(
        model=model,
        input_tokens=getattr(resp.usage, "input_tokens", 0),
        output_tokens=getattr(resp.usage, "output_tokens", 0),
        cache_read_tokens=getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        stop_reason=resp.stop_reason,
        seconds=time.time() - t0,
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    if resp.stop_reason == "refusal":
        raise AIError("the model refused this request (stop_reason=refusal); nothing was built")
    if resp.stop_reason == "max_tokens":
        raise AIError(f"response hit max_tokens ({max_tokens}) and is incomplete; retry with a higher limit")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIError(f"model returned text that is not JSON: {exc}") from exc
    SESSION.add(usage)
    from .schemas import WIRE_SOURCE     # which stripper built the wire schema, so an SDK change shows up
    log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "label": label, "model": model,
         "wire_schema_source": WIRE_SOURCE["used"],
         "session_calls": SESSION.calls, "session_cost_usd": round(SESSION.cost, 6),
         "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
         "cache_read_tokens": usage.cache_read_tokens, "cost_usd": round(usage.cost, 6),
         "seconds": round(usage.seconds, 2), "stop_reason": usage.stop_reason,
         "branch": "ask" if "clarifying_questions" in data else "build"})
    return Reply(raw_text=text, data=data, usage=usage)
