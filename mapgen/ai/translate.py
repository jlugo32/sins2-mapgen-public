"""Natural language -> MapSpec, via structured outputs."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Limits
from ..spec import MapSpec, SpecError, from_dict
from . import prompts
from .client import AIError, Reply, call, make_client
from .schemas import validation_errors, wire_schema


@dataclass
class Translation:
    spec: MapSpec | None = None
    questions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    reply: Reply | None = None

    @property
    def asked(self) -> bool:
        return bool(self.questions)


def interpret(data: dict) -> Translation:
    """Validate one wrapper response and turn it into a Translation (no API call)."""
    errs = validation_errors(data)
    if errs:
        raise SpecError("response does not match the MapSpecResponse schema:\n  " + "\n  ".join(errs))
    if "clarifying_questions" in data:
        return Translation(questions=list(data["clarifying_questions"]))
    return Translation(spec=from_dict(data["spec"]), assumptions=list(data.get("assumptions", [])))


def translate(request: str, limits: Limits, seed: int | None = None, client=None,
              messages: list[dict] | None = None, label: str = "translate") -> Translation:
    """One call. Schema-invalid answers raise SpecError; repair.py (3.3) handles retrying."""
    client = client or make_client()
    reply = call(client, prompts.system_prompt(limits), messages or prompts.messages(request, seed),
                 wire_schema(), label=label)
    out = interpret(reply.data)
    out.reply = reply
    return out


__all__ = ["AIError", "Translation", "interpret", "translate"]
