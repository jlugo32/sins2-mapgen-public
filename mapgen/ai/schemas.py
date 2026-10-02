"""The wrapper schema the model answers with. MapSpec itself stays untouched and strict.

Two mutually exclusive branches:
  A) {"spec": MapSpec, "assumptions"?: [str]}   -> builds; assumptions are printed in the summary
  B) {"clarifying_questions": [str]}            -> blocks; nothing is built

Local validation uses `oneOf`, so a response carrying both branches fails. The wire schema sent to the
API uses `anyOf` instead: the structured-outputs docs list `anyOf`/`allOf` as supported and do not list
`oneOf`. The branches stay mutually exclusive there because each one requires its own key and sets
additionalProperties: false, so neither can carry the other's key.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache

from jsonschema import Draft202012Validator

from .. import ROOT
from ..spec import SCHEMA_PATH

MAX_QUESTIONS = 3


def _mapspec_defs() -> tuple[dict, dict]:
    """MapSpec as an inlinable subschema plus its $defs (external $ref is not supported on the wire)."""
    ms = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    defs = ms.pop("$defs", {})
    ms.pop("$schema", None)
    ms.pop("$id", None)
    return ms, defs


def _branches(mapspec: dict) -> tuple[dict, dict]:
    a = {
        "type": "object",
        "title": "build",
        "description": "Build this map. Use for every request you can answer.",
        "additionalProperties": False,
        "required": ["spec"],
        "properties": {
            "spec": mapspec,
            "assumptions": {
                "description": "Interpretive calls you made that the user did not state. Flavour and "
                               "design judgement belong here, never in clarifying_questions.",
                "type": "array",
                "items": {"type": "string"},
            },
        },
    }
    b = {
        "type": "object",
        "title": "ask",
        "description": "Ask instead of guessing. Only when the answer changes the build and only the "
                       "user can supply it.",
        "additionalProperties": False,
        "required": ["clarifying_questions"],
        "properties": {
            "clarifying_questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_QUESTIONS,
                "items": {"type": "string"},
            },
        },
    }
    return a, b


@lru_cache(maxsize=1)
def strict_schema() -> dict:
    """Local validation schema: oneOf, with every MapSpec constraint intact."""
    mapspec, defs = _mapspec_defs()
    a, b = _branches({"$ref": "#/$defs/mapspec"})
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "MapSpecResponse",
        "oneOf": [a, b],
        "$defs": {**defs, "mapspec": mapspec},
    }


@lru_cache(maxsize=1)
def wire_schema() -> dict:
    """Schema sent as output_config.format: anyOf, and constraints the API does not support removed."""
    mapspec, defs = _mapspec_defs()
    a, b = _branches({"$ref": "#/$defs/mapspec"})
    # The API rejects sibling keys next to anyOf ("For 'anyOf', '$defs, additionalProperties, type' is
    # not supported"), so the wire root is anyOf and nothing else, with every $ref inlined.
    schema = {"anyOf": [_inline(a, defs, mapspec), _inline(b, defs, mapspec)]}
    try:
        from anthropic import transform_schema
        out = transform_schema(copy.deepcopy(schema))
        WIRE_SOURCE["used"] = "anthropic.transform_schema"
        return out
    except Exception as exc:               # noqa: BLE001
        # anthropic 1.8.0 raises "Schema must have a 'type', 'anyOf', 'oneOf', or 'allOf' field" on
        # $ref-based schemas like ours, so we strip the unsupported keywords ourselves. Same contract:
        # constraints move into descriptions and are still enforced locally by strict_schema().
        WIRE_SOURCE["used"] = f"local fallback ({type(exc).__name__})"
        return _strip_unsupported(schema)


WIRE_SOURCE: dict[str, str] = {"used": "not built yet"}


def _inline(node, defs: dict, mapspec: dict):
    """Expand every internal $ref. MapSpec is not recursive, so this terminates."""
    if isinstance(node, list):
        return [_inline(x, defs, mapspec) for x in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        target = mapspec if name == "mapspec" else defs[name]
        merged = {**copy.deepcopy(target), **{k: v for k, v in node.items() if k != "$ref"}}
        return _inline(merged, defs, mapspec)
    return {k: _inline(v, defs, mapspec) for k, v in node.items()}


UNSUPPORTED = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
               "minLength", "maxLength", "maxItems", "uniqueItems")


def _strip_unsupported(node):
    """Remove keywords structured outputs rejects, keeping the information in `description`."""
    if isinstance(node, list):
        return [_strip_unsupported(x) for x in node]
    if not isinstance(node, dict):
        return node
    out, notes = {}, []
    for k, v in node.items():
        if k in UNSUPPORTED:
            notes.append(f"{k}: {v}")
            continue
        if k == "minItems" and v not in (0, 1):
            notes.append(f"minItems: {v}")
            continue
        out[k] = _strip_unsupported(v)
    if notes:
        out["description"] = " ".join(filter(None, [out.get("description"), "(" + "; ".join(notes) + ")"]))
    if out.get("type") == "object":
        out.setdefault("additionalProperties", False)
    return out


def _messages(validator: Draft202012Validator, data, prefix: str = "") -> list[str]:
    out = []
    for e in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        path = prefix + ("/".join(str(p) for p in e.absolute_path) or "<root>")
        message = e.message if len(e.message) < 300 else e.message[:300] + " ..."
        out.append(f"{path}: {message}")
    return out


def validation_errors(data: dict) -> list[str]:
    """Errors against the strict wrapper schema.

    A failing `oneOf` reports only "is not valid under any of the given schemas" and inlines the whole
    instance, which is useless as repair feedback. When the intended branch is obvious we validate
    against that branch instead, so the caller gets the actual field-level problem.
    """
    errs = _messages(Draft202012Validator(strict_schema()), data)
    if not errs or not isinstance(data, dict):
        return errs
    has_spec, has_questions = "spec" in data, "clarifying_questions" in data
    if has_spec and has_questions:
        return ["<root>: answer with exactly one branch: either 'spec' (+ optional 'assumptions') "
                "or 'clarifying_questions', never both"]
    if has_spec:
        schema = strict_schema()
        detail = _messages(Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/mapspec"}),
                           data["spec"], prefix="spec/")
        extra = sorted(set(data) - {"spec", "assumptions"})
        if extra:
            detail.append(f"<root>: unexpected field(s) {extra} beside 'spec'")
        if detail:
            return detail
    return errs


def write_reference_copy() -> None:
    """Keep schemas/ai_response.schema.json in step with the generated strict schema."""
    p = ROOT / "schemas" / "ai_response.schema.json"
    p.write_text(json.dumps(strict_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
