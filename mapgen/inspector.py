"""Read-only visual inspector: a local page that explains a compiled map.

Everything shown is derived from the same compiler, rules and colours the build uses - this module adds
no map logic of its own. There is no editing and no save path.
"""
from __future__ import annotations

import http.server
import json
import socketserver
import threading
from pathlib import Path

from . import ROOT, rules
from .compiler import CompiledMap
from .config import Config
from .params import MapParams
from .pipeline import reachable_resources
from .preview import KIND, ROLE, TIER_SIZE, open_file
from .spec import MapSpec, load as load_spec

CSS_COLOURS = {**{f"role_{k}": v for k, v in ROLE.items()}, **{f"kind_{k}": v for k, v in KIND.items()}}


def rgb(c) -> str:
    return "#%02x%02x%02x" % tuple(c)


def payload(m: CompiledMap, violations: list[rules.Violation]) -> dict:
    """Everything the page needs, computed once, server side."""
    spec = m.spec
    kinds = {z.id: z.kind for z in spec.zones}
    touching: dict[int, list[int]] = {}
    for i, v in enumerate(violations):
        for nid in v.node_ids:
            touching.setdefault(nid, []).append(i)

    lanes_by_node: dict[int, list[dict]] = {}
    lanes = []
    for l in m.lanes:
        lanes.append({"id": l.id, "a": l.a, "b": l.b, "type": l.type})
        for end, other in ((l.a, l.b), (l.b, l.a)):
            lanes_by_node.setdefault(end, []).append({"id": l.id, "other": other, "type": l.type})

    nodes = []
    for n in m.nodes:
        kind = kinds.get(n.zone) if n.zone else None
        nodes.append({
            "id": n.id, "x": round(n.pos[0], 1), "y": round(n.pos[1], 1),
            "role": n.role, "zone": n.zone, "zone_kind": kind,
            "tier": n.tier, "bias": n.bias, "filling_name": n.filling_name,
            "metal": list(n.metal), "crystal": list(n.crystal), "research_gated": n.research_gated,
            "ownership": n.ownership, "lanes": lanes_by_node.get(n.id, []),
            "findings": touching.get(n.id, []),
            "colour": rgb(ROLE[n.role] if n.role in ROLE else KIND.get(kind, (200, 200, 200))),
            "size": 2.2 if n.role == "star" else (1.9 if n.role == "home" else
                                                  (0.9 if n.role == "wormhole" else TIER_SIZE.get(n.tier, 1.0))),
        })

    zones = []
    for z in spec.zones:
        ids = m.zone_nodes[z.id]
        zones.append({
            "id": z.id, "kind": z.kind, "planet_count": z.planet_count, "nodes": ids,
            "size_tiers": z.size_tiers, "slot_biases": z.slot_biases, "resource_bias": z.resource_bias,
            "gated": z.gated, "chokepoints": z.chokepoints, "npc": z.npc,
            "owner_player": z.owner_player, "placement": z.placement.kind,
            "links": [f"{l.from_zone} -> {l.to_zone} [{l.lane}{'/chokepoint' if l.chokepoint else ''}]"
                      for l in spec.links if z.id in (l.from_zone, l.to_zone)],
            "metal": round(sum(m.nodes[i].metal_mean for i in ids), 1),
            "crystal": round(sum(m.nodes[i].crystal_mean for i in ids), 1),
        })

    adv = rules.region_advantages(m)
    reach = reachable_resources(m)
    regions = []
    for region, (core, majors) in sorted(adv.items()):
        metal, crystal, sources = reach[region]
        ids = m.zone_nodes[region]
        others = [m.nodes[i] for i in ids if m.nodes[i].role != "home"]
        regions.append({
            "id": region, "core_access": core, "majors": majors, "sources": sources,
            "reach_metal": round(metal, 1), "reach_crystal": round(crystal, 1),
            "cluster_metal": round(sum(n.metal_mean for n in others), 1),
            "cluster_crystal": round(sum(n.crystal_mean for n in others), 1),
            "research_gated": sum(1 for n in others if n.research_gated),
            "nodes": ids,
        })

    return {
        "meta": {"name": spec.meta.name, "display_name": spec.meta.display_name,
                 "players": spec.meta.players, "seed": spec.meta.seed,
                 "planets": len(m.planets()), "fixtures": len(m.fixtures()),
                 "bodies": len(m.bodies()), "lanes": len(m.lanes)},
        "nodes": nodes, "lanes": lanes, "zones": zones, "regions": regions,
        "findings": [{"code": v.code, "severity": v.severity, "message": v.message, "hint": v.hint,
                      "nodes": v.node_ids} for v in violations],
        "spokes": [{"from": s.from_zone, "zone": s.zone, "chokepoint": s.chokepoint, "path": s.path}
                   for s in m.spokes],
        "convoys": [{"from": a, "via": c, "to": b} for a, c, b in m.convoys],
    }


HTML = """<!doctype html>
<meta charset="utf-8"><title>{title} - sins2-mapgen inspector</title>
<style>
 :root {{ --bg:#0c0e18; --panel:#141726; --line:#2a2f45; --text:#b0bad2; --bright:#e8ecf6; }}
 * {{ box-sizing:border-box; }}
 body {{ margin:0; background:var(--bg); color:var(--text);
        font:13px/1.45 "Segoe UI",system-ui,sans-serif; display:flex; height:100vh; overflow:hidden; }}
 #side {{ width:320px; flex:none; background:var(--panel); border-right:1px solid var(--line);
          overflow-y:auto; padding:12px; }}
 #main {{ flex:1; display:flex; flex-direction:column; overflow:hidden; }}
 #map {{ flex:1; overflow:hidden; }}
 #tables {{ height:34%; overflow:auto; border-top:1px solid var(--line); padding:10px 14px;
            background:var(--panel); }}
 h1 {{ font-size:15px; color:var(--bright); margin:0 0 4px; }}
 h2 {{ font-size:12px; text-transform:uppercase; letter-spacing:.08em; color:#7f8aa6;
       margin:14px 0 6px; }}
 .row {{ padding:3px 6px; border-radius:4px; cursor:pointer; }}
 .row:hover {{ background:#1d2136; }}
 .row.sel {{ background:#28304e; color:var(--bright); }}
 .sw {{ display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:6px; }}
 table {{ border-collapse:collapse; width:100%; font-size:12px; }}
 th,td {{ text-align:left; padding:3px 8px; border-bottom:1px solid var(--line); white-space:nowrap; }}
 th {{ color:#7f8aa6; font-weight:600; }}
 tr.hl {{ background:#28304e; }}
 .warn {{ color:#ffc857; }} .err {{ color:#ff6b6b; }} .ok {{ color:#8fd694; }}
 #tip {{ position:fixed; pointer-events:none; background:#0a0c14; border:1px solid var(--line);
         padding:7px 9px; border-radius:6px; font-size:12px; display:none; max-width:320px;
         box-shadow:0 6px 20px #0008; z-index:9; }}
 #detail {{ font-size:12px; }} #detail b {{ color:var(--bright); }}
 .node {{ cursor:pointer; stroke:#0c0e18; stroke-width:1.5; }}   /* outline separates touching nodes */
 .dim {{ opacity:.10; }}
 .lane {{ stroke:#8e9bbd; stroke-width:3; stroke-linecap:round; }}
 .lane.wormhole {{ stroke:#e27aff; stroke-width:4.2; stroke-dasharray:11 8; }}
 .lane.star {{ stroke:#ffd25a; stroke-width:4.2; }}
 .lane.hl {{ stroke:#fff; stroke-width:5.5; }}
 small {{ color:#6f7a95; }}
 text.lbl {{ fill:#cbd5eb; font-size:12px; paint-order:stroke; stroke:#0c0e18; stroke-width:3px; }}
 #err {{ display:none; background:#3a1520; color:#ffb3b3; padding:8px 12px; font-size:12px;
         border-bottom:1px solid #6b2233; }}
</style>
<div id="side">
  <h1>{title}</h1>
  <small>{players} players &middot; {planets} planets &middot; {fixtures} fixtures &middot;
  {lanes_n} lanes &middot; seed {seed}</small>
  <h2>Findings</h2><div id="findings"></div>
  <h2>Zones</h2><div id="zones"></div>
  <h2>Selection</h2><div id="detail"><small>hover or click a node</small></div>
</div>
<div id="main"><div id="err"></div><div id="map">{svg}</div><div id="tables"></div></div>
<div id="tip"></div>
<script>
window.onerror = (m, src, line) => {{
  const e = document.getElementById('err');
  e.style.display = 'block';
  e.textContent = 'The map is drawn, but interactivity failed: ' + m + ' (line ' + line + ')';
}};
const D = {payload};
const byId = Object.fromEntries(D.nodes.map(n => [n.id, n]));
let selZone = null, selNode = null;

// the SVG above is rendered server side; this script only adds behaviour

// ---------- hover
const tip = document.getElementById('tip');
document.getElementById('map').addEventListener('mousemove', e => {{
  const el = e.target.closest('[data-id]');
  if (!el) {{ tip.style.display = 'none'; return; }}
  const n = byId[+el.dataset.id];
  const res = (n.metal[1] || n.crystal[1])
      ? `metal ${{n.metal[0]}}-${{n.metal[1]}} &middot; crystal ${{n.crystal[0]}}-${{n.crystal[1]}}` : 'no asteroids';
  tip.innerHTML = `<b>#${{n.id}}</b> ${{n.role}}${{n.zone ? ' &middot; ' + n.zone : ''}}<br>`
    + `<span style="color:#e8ecf6">${{n.filling_name}}</span><br>`
    + (n.tier ? `tier ${{n.tier}} &middot; ${{n.bias}}${{n.research_gated ? ' (R)' : ''}}<br>` : '')
    + res + `<br><small>${{n.lanes.length}} lane(s)`
    + (n.findings.length ? ` &middot; <span class="warn">${{n.findings.length}} finding(s)</span>` : '')
    + `</small>`;
  tip.style.display = 'block';
  tip.style.left = Math.min(e.clientX + 14, innerWidth - 340) + 'px';
  tip.style.top = (e.clientY + 16) + 'px';
}});
document.getElementById('map').addEventListener('mouseleave', () => tip.style.display = 'none');

// ---------- click a node
document.getElementById('map').addEventListener('click', e => {{
  const el = e.target.closest('[data-id]');
  if (!el) {{ selNode = null; selZone = null; paint(); return; }}
  selNode = +el.dataset.id; selZone = null; paint();
}});

function detail(n) {{
  const lanes = n.lanes.map(l => {{
    const o = byId[l.other];
    return `<div class="row" data-node="${{o.id}}">lane ${{l.id}} [${{l.type}}] &rarr; #${{o.id}}
            ${{o.zone || o.role}}</div>`;
  }}).join('');
  const fs = n.findings.map(i => {{
    const v = D.findings[i];
    return `<div class="${{v.severity === 'error' ? 'err' : 'warn'}}">${{v.code}}: ${{v.message}}
            <br><small>${{v.hint}}</small></div>`;
  }}).join('') || '<small>no rule findings touch this node</small>';
  return `<b>#${{n.id}}</b> ${{n.role}}${{n.zone ? ' in <b>' + n.zone + '</b>' : ''}}<br>`
    + `${{n.filling_name}}<br>`
    + (n.tier ? `tier ${{n.tier}}, ${{n.bias}} bias${{n.research_gated ? ', research-gated' : ''}}<br>` : '')
    + `metal ${{n.metal[0]}}-${{n.metal[1]}}, crystal ${{n.crystal[0]}}-${{n.crystal[1]}}<br>`
    + (n.ownership ? `ownership: ${{JSON.stringify(n.ownership)}}<br>` : '')
    + `<h2>Lanes (${{n.lanes.length}})</h2>${{lanes}}<h2>Rules</h2>${{fs}}`;
}}

// ---------- side panels
document.getElementById('findings').innerHTML = D.findings.length
  ? D.findings.map((v, i) => `<div class="row" data-finding="${{i}}">
      <span class="${{v.severity === 'error' ? 'err' : 'warn'}}">${{v.severity.toUpperCase()}}</span>
      ${{v.code}}<br><small>${{v.message}}</small></div>`).join('')
  : '<div class="ok">no rule findings</div>';
document.getElementById('zones').innerHTML = D.zones.map(z =>
  `<div class="row" data-zone="${{z.id}}"><span class="sw" style="background:${{
     (byId[z.nodes[0]] || {{}}).colour || '#888'}}"></span>${{z.id}}
   <small>${{z.kind}} &middot; ${{z.planet_count}}p${{z.gated ? ' &middot; gated' : ''}}</small></div>`).join('');

document.getElementById('side').addEventListener('click', e => {{
  const z = e.target.closest('[data-zone]'), f = e.target.closest('[data-finding]'),
        nd = e.target.closest('[data-node]');
  if (z) {{ selZone = z.dataset.zone; selNode = null; }}
  else if (nd) {{ selNode = +nd.dataset.node; selZone = null; }}
  else if (f) {{ const v = D.findings[+f.dataset.finding];
                selNode = null; selZone = null; highlight(v.nodes); return; }}
  paint();
}});

function highlight(ids) {{
  const set = new Set(ids);
  document.querySelectorAll('.node').forEach(el =>
    el.classList.toggle('dim', set.size > 0 && !set.has(+el.dataset.id)));
  document.querySelectorAll('.lane').forEach(el => {{
    const on = set.has(+el.dataset.a) && set.has(+el.dataset.b);
    el.classList.toggle('hl', on);
    el.classList.toggle('dim', set.size > 0 && !on && !(set.has(+el.dataset.a) || set.has(+el.dataset.b)));
  }});
  document.querySelectorAll('[data-ring]').forEach(el =>
    el.classList.toggle('dim', set.size > 0 && !set.has(+el.dataset.ring)));
}}

function paint() {{
  document.querySelectorAll('.row').forEach(r => r.classList.remove('sel'));
  const det = document.getElementById('detail');
  if (selNode !== null) {{
    const n = byId[selNode];
    det.innerHTML = detail(n);
    highlight([n.id, ...n.lanes.map(l => l.other)]);
  }} else if (selZone) {{
    const z = D.zones.find(z => z.id === selZone);
    document.querySelector(`[data-zone="${{selZone}}"]`).classList.add('sel');
    det.innerHTML = `<b>${{z.id}}</b> (${{z.kind}})<br>${{z.planet_count}} planets &middot;
      ${{z.resource_bias}} bias<br>tiers ${{JSON.stringify(z.size_tiers)}}<br>`
      + (z.slot_biases ? `slot biases ${{JSON.stringify(z.slot_biases)}}<br>` : '')
      + (z.gated ? `<span class="warn">gated, ${{z.chokepoints}} chokepoint(s)</span><br>` : '')
      + (z.owner_player !== null && z.owner_player !== undefined ? `player ${{z.owner_player}}<br>` : '')
      + `metal ${{z.metal}} &middot; crystal ${{z.crystal}}<br>`
      + `<h2>Links</h2>` + (z.links.map(l => `<div>${{l}}</div>`).join('') || '<small>none</small>')
      + `<h2>Planets</h2>` + z.nodes.map(i =>
          `<div class="row" data-node="${{i}}">#${{i}} ${{byId[i].filling_name}}</div>`).join('');
    highlight(z.nodes);
  }} else {{
    det.innerHTML = '<small>hover or click a node</small>';
    highlight([]);
  }}
  document.querySelectorAll('#tables tr').forEach(tr =>
    tr.classList.toggle('hl', !!selZone && tr.dataset.region === selZone));
}}

// ---------- tables
document.getElementById('tables').innerHTML = `
 <table><tr><th>region</th><th>core access</th><th>majors touched</th><th>cluster metal/crystal</th>
 <th>(R)</th><th>reachable metal</th><th>reachable crystal</th><th>sources</th></tr>
 ${{D.regions.map(r => `<tr data-region="${{r.id}}"><td>${{r.id}}</td>
   <td>${{r.core_access ? 'spoke' : '-'}}</td><td>${{r.majors.join(', ') || '-'}}</td>
   <td>${{r.cluster_metal}} / ${{r.cluster_crystal}}</td><td>${{r.research_gated}}</td>
   <td>${{r.reach_metal}}</td>
   <td class="${{r.reach_crystal < 15 ? 'warn' : ''}}">${{r.reach_crystal}}</td>
   <td><small>${{r.sources.join(', ')}}</small></td></tr>`).join('')}}</table>
 <p><small>Reachable = own cluster + border/contested zones it links to, without entering a gated zone.
 Shared with neighbours, so it is an upper bound. Convoys:
 ${{D.convoys.map(c => c.from + '-' + c.to).join(', ') || 'none'}}.
 Spokes: ${{D.spokes.map(s => s.from + ' &rarr; #' + s.chokepoint).join(', ') || 'none'}}.</small></p>`;
paint();
</script>
"""


def render_svg(data: dict) -> str:
    """The map, drawn server side so it shows even if the page's JavaScript never runs."""
    nodes = {n["id"]: n for n in data["nodes"]}
    xs = [n["x"] for n in data["nodes"]]
    ys = [n["y"] for n in data["nodes"]]
    pad, r_unit = 60, 12
    vb = (min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad)
    out = [f'<svg id="svg" viewBox="{vb[0]:.0f} {vb[1]:.0f} {vb[2]:.0f} {vb[3]:.0f}" '
           f'preserveAspectRatio="xMidYMid meet" style="width:100%;height:100%">']
    for l in data["lanes"]:
        a, b = nodes[l["a"]], nodes[l["b"]]
        out.append(f'<line class="lane {l["type"]}" data-lane="{l["id"]}" data-a="{l["a"]}" '
                   f'data-b="{l["b"]}" x1="{a["x"]}" y1="{a["y"]}" x2="{b["x"]}" y2="{b["y"]}"/>')
    for n in data["nodes"]:
        r = r_unit * n["size"]
        if n["role"] == "wormhole":
            pts = f'{n["x"]},{n["y"] - r} {n["x"] + r},{n["y"]} {n["x"]},{n["y"] + r} {n["x"] - r},{n["y"]}'
            out.append(f'<polygon class="node" data-id="{n["id"]}" fill="{n["colour"]}" points="{pts}"/>')
        else:
            out.append(f'<circle class="node" data-id="{n["id"]}" cx="{n["x"]}" cy="{n["y"]}" '
                       f'r="{r:.1f}" fill="{n["colour"]}"/>')
        if n["role"] in ("home", "chokepoint"):
            out.append(f'<circle class="ring" data-ring="{n["id"]}" cx="{n["x"]}" cy="{n["y"]}" '
                       f'r="{r + 4:.1f}" fill="none" stroke="#fff" stroke-width="1.6" pointer-events="none"/>')
        if n["findings"]:
            out.append(f'<circle class="ring" data-ring="{n["id"]}" cx="{n["x"]}" cy="{n["y"]}" '
                       f'r="{r + 8:.1f}" fill="none" stroke="#ffc857" stroke-width="1.4" '
                       f'stroke-dasharray="3 3" pointer-events="none"/>')
        label = str(n["id"])
        if n["role"] == "home" and n["ownership"]:
            label += f' P{n["ownership"]["player_index"]}'
        elif n["zone"]:
            label += f' {n["zone"]}'
        if n["role"] != "star":
            out.append(f'<text class="lbl" x="{n["x"] + r + 3:.1f}" y="{n["y"] - r - 2:.1f}" '
                       f'pointer-events="none">{label}</text>')
    out.append("</svg>")
    return "".join(out)


def render_html(data: dict) -> str:
    meta = data["meta"]
    return HTML.format(title=meta["display_name"], players=meta["players"], planets=meta["planets"],
                       fixtures=meta["fixtures"], lanes_n=meta["lanes"], seed=meta["seed"],
                       svg=render_svg(data), payload=json.dumps(data))


def resolve_spec(target: Path) -> MapSpec:
    """Accept a .mapspec.json, or a built mod folder whose spec sits beside it or in specs/."""
    if target.is_file():
        return load_spec(target)
    if target.is_dir():
        for candidate in (target.parent / f"{target.name}.mapspec.json",
                          ROOT / "specs" / f"{target.name}.mapspec.json",
                          target / f"{target.name}.mapspec.json"):
            if candidate.exists():
                return load_spec(candidate)
        raise FileNotFoundError(
            f"no MapSpec found for {target}. Looked for {target.name}.mapspec.json beside it and in "
            f"specs/. The inspector needs the spec, not just the built mod.")
    raise FileNotFoundError(f"{target} not found")


def build_page(target: Path, cfg: Config, params: MapParams | None = None) -> tuple[str, dict]:
    from .compiler import compile_spec, to_galaxy_chart
    params = params or MapParams()
    spec = resolve_spec(target)
    m = compile_spec(spec, params.geometry)
    violations = rules.check(m, to_galaxy_chart(m), cfg.limits)
    data = payload(m, violations)
    return render_html(data), data


def make_handler(body: bytes):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"                        # keep-alive; Content-Length is always set
        timeout = 10                                         # drop a connection that never sends a request

        def do_GET(self):                                    # noqa: N802
            if self.path in ("/favicon.ico", "/robots.txt"):
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):                        # quiet
            pass

    return Handler


class _Server(socketserver.ThreadingTCPServer):
    """Threaded on purpose: browsers open speculative connections and send nothing on them, which
    blocks a single-threaded server in readline() so the real request never gets served."""
    daemon_threads = True
    allow_reuse_address = True


def serve(html: str, port: int = 8765, open_browser: bool = True) -> None:
    """Serve the page on localhost until Ctrl-C. Nothing is written and nothing leaves the machine."""
    body = html.encode("utf-8")
    try:
        httpd = _Server(("127.0.0.1", port), make_handler(body))
    except OSError as exc:
        raise OSError(f"cannot listen on 127.0.0.1:{port} ({exc}). Try --port 8766.") from exc
    url = f"http://127.0.0.1:{port}/"
    print(f"inspector: {url}   (read-only; Ctrl-C to stop)", flush=True)
    if open_browser:
        threading.Timer(0.3, lambda: open_file(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.shutdown()
        httpd.server_close()
