"""Is the ring few-shot load-bearing? Run the same requests with and without it.

Usage:  .venv\\Scripts\\python tools\\prompt_experiment.py            (6 live calls, ~$0.40)
        .venv\\Scripts\\python tools\\prompt_experiment.py --dry      (prompt sizes only, no calls)

Writes out/prompt_experiment.json and prints a comparison table.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console                                    # noqa: E402

from mapgen import rules                                            # noqa: E402
from mapgen.ai import prompts                                       # noqa: E402
from mapgen.ai.client import call, make_client                      # noqa: E402
from mapgen.ai.repair import check                                  # noqa: E402
from mapgen.ai.schemas import wire_schema                           # noqa: E402
from mapgen.ai.translate import interpret                           # noqa: E402
from mapgen.config import load_config                               # noqa: E402
from mapgen.params import MapParams                                 # noqa: E402
from mapgen.spec import SpecError                                   # noqa: E402

REQUESTS = {
    "gated_core": ("Eight players on a ring, 80 planets, with a rich core in the middle that can only "
                   "be reached through three chokepoints."),
    "contested_centre": "6 players, 60 planets, ring, one contested center",
    "big_convoys": ("Ten players, 110 planets on a ring, wormhole convoys between players who are not "
                    "neighbours, and pirates in the gaps."),
}
VARIANTS = {
    "A_all_three": None,                                     # ring + duel + oil (current default)
    "B_no_ring": ("duel_4p", "oil_chokepoint_6p"),           # the two small examples only
}


def save_call(variant: str, name: str, payload: dict) -> Path:
    """Every call keeps its raw response and resulting spec, so later questions need no new calls."""
    d = Path(__file__).resolve().parent.parent / "out" / "prompt_experiment"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{variant}__{name}.json"
    f.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return f


def measure(name: str, request: str, variant: str, only, cfg, client, console) -> dict:
    msgs = prompts.messages(request, seed=42, only=only)
    row: dict = {"request": name, "variant": variant,
                 "prompt_chars": len(prompts.system_prompt(cfg.limits)) + sum(len(m["content"]) for m in msgs)}
    if client is None:
        return row
    record: dict = {"request_text": request, "variant": variant, "messages_sent": msgs}
    # call and interpret separately, so a rejected answer still keeps its raw text
    reply = call(client, prompts.system_prompt(cfg.limits), msgs, wire_schema(),
                 label=f"experiment:{variant}:{name}")
    u = reply.usage
    record["raw_response"] = reply.raw_text
    record["usage"] = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                       "cost": round(u.cost, 4)}
    try:
        t = interpret(reply.data)
    except SpecError as exc:
        record.update(schema_ok=False, error=str(exc))
        row["saved"] = str(save_call(variant, name, record))
        row.update(schema_ok=False, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                   cost=round(u.cost, 4), error=str(exc).splitlines()[0],
                   error_detail=[l.strip() for l in str(exc).splitlines()[1:6]])
        return row
    record["questions"] = t.questions
    record["assumptions"] = t.assumptions
    record["spec"] = t.spec.to_dict() if t.spec else None
    row["saved"] = str(save_call(variant, name, record))
    row.update(schema_ok=True, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
               cost=round(u.cost, 4), asked=t.asked, assumptions=len(t.assumptions))
    if t.asked:
        row["questions"] = t.questions
        return row
    spec = t.spec
    gated = [z for z in spec.zones if z.gated]
    row.update(planets=spec.constraints.total_planets,
               zone_sum=sum(z.planet_count for z in spec.zones),
               players=spec.meta.players,
               gated_zones=[z.id for z in gated],
               chokepoints=sum(z.chokepoints for z in gated),
               chokepoint_links=sum(1 for l in spec.links if l.chokepoint),
               wormhole_links=sum(1 for l in spec.links if l.lane == "wormhole"))
    try:
        m, violations = check(spec, cfg.limits, MapParams())
    except Exception as exc:                                  # noqa: BLE001 - compile failure is a result
        row.update(builds=False, errors=[f"COMPILE: {type(exc).__name__}"])
        return row
    errs = rules.errors(violations)
    row.update(builds=not errs, errors=[v.code for v in errs],
               warnings=[v.code for v in violations if v.severity == "warning"],
               compiled_planets=len(m.planets()), fixtures=len(m.fixtures()))
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="prompt sizes only, no API calls")
    ap.add_argument("--request", choices=sorted(REQUESTS), action="append",
                    help="limit to these requests (default: all)")
    ap.add_argument("--variant", choices=sorted(VARIANTS), action="append",
                    help="limit to these variants (default: all)")
    ap.add_argument("--tag", default="", help="suffix for the output file, e.g. after-prompt-change")
    args = ap.parse_args()
    cfg = load_config()
    console = Console(width=120)
    client = None if args.dry else make_client()
    rows = []
    variants = {k: v for k, v in VARIANTS.items() if not args.variant or k in args.variant}
    requests = {k: v for k, v in REQUESTS.items() if not args.request or k in args.request}
    for variant, only in variants.items():
        for name, request in requests.items():
            row = measure(name, request, variant, only, cfg, client, console)
            rows.append(row)
            console.print(f"[dim]{variant:12} {name:17} "
                          f"{row.get('input_tokens', '-')} in / {row.get('output_tokens', '-')} out "
                          f"builds={row.get('builds')} gated={row.get('gated_zones')}[/]")
    out = (Path(__file__).resolve().parent.parent / "out" /
           f"prompt_experiment{('_' + args.tag) if args.tag else ''}.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    console.print(f"\nwrote {out}")
    total = sum(r.get("cost", 0) for r in rows)
    console.print(f"total cost: ${total:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
