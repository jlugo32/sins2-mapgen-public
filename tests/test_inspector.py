"""The read-only inspector: payload correctness and a renderable page. No editing, no save path."""
import json
import re

import pytest

from mapgen import ROOT, rules
from mapgen.compiler import compile_spec, to_galaxy_chart
from mapgen.inspector import build_page, payload, render_html, resolve_spec
from mapgen.params import MapParams


@pytest.fixture
def data(ring_spec, cfg):
    m = compile_spec(ring_spec)
    return m, payload(m, rules.check(m, to_galaxy_chart(m), cfg.limits))


def test_payload_covers_every_node_lane_and_zone(data, ring_spec):
    m, d = data
    assert len(d["nodes"]) == len(m.nodes) and len(d["lanes"]) == len(m.lanes)
    assert {z["id"] for z in d["zones"]} == {z.id for z in ring_spec.zones}
    assert d["meta"]["planets"] == len(m.planets()) == 100
    assert len(d["regions"]) == ring_spec.meta.players
    assert [c["from"] for c in d["convoys"]] and [s["from"] for s in d["spokes"]]


def test_every_node_carries_what_the_hover_shows(data):
    _, d = data
    planet = next(n for n in d["nodes"] if n["role"] == "planet")
    for key in ("zone", "role", "tier", "bias", "filling_name", "metal", "crystal", "colour", "lanes"):
        assert planet[key] is not None, key
    assert planet["filling_name"].startswith("random_")
    assert all(len(n["lanes"]) >= 1 for n in d["nodes"] if n["role"] != "star")


def test_findings_link_back_to_their_nodes(ring_spec, cfg):
    from mapgen.spec import Link
    ring_spec.links.append(Link("filler", "core", "normal"))
    m = compile_spec(ring_spec)
    d = payload(m, rules.check(m, to_galaxy_chart(m), cfg.limits))
    bypass = next(f for f in d["findings"] if f["code"] == "CHOKEPOINT_BYPASS")
    assert bypass["nodes"], "a finding must name the nodes it touches"
    for nid in bypass["nodes"]:
        assert d["findings"].index(bypass) in d["nodes"][nid]["findings"]


def test_zone_entries_drive_the_side_list(data):
    _, d = data
    core = next(z for z in d["zones"] if z["id"] == "core")
    assert core["gated"] and core["chokepoints"] == 3
    assert all("core" in l for l in core["links"])
    assert core["nodes"] and core["crystal"] > 0


def test_region_table_matches_the_rules_module(data):
    m, d = data
    adv = rules.region_advantages(m)
    for row in d["regions"]:
        core, majors = adv[row["id"]]
        assert row["core_access"] == core and row["majors"] == majors


def test_page_renders_without_leftover_template_braces(data):
    _, d = data
    html = render_html(d)
    assert "{{" not in html and "}}" not in html
    assert "<svg" in html or "viewBox" in html
    payload_json = re.search(r"const D = (\{.*?\});\n", html, re.S).group(1)
    assert json.loads(payload_json)["meta"]["display_name"] == d["meta"]["display_name"]


def test_page_has_no_write_path(data):
    """Read-only: nothing in the page posts, saves or edits."""
    _, d = data
    html = render_html(d).lower()
    for forbidden in ("fetch(", "xmlhttprequest", "method=\"post\"", "contenteditable", "<form"):
        assert forbidden not in html, forbidden


def test_build_page_from_a_spec_file(cfg):
    html, d = build_page(ROOT / "specs" / "skill_test_quad.mapspec.json", cfg)
    assert d["meta"]["planets"] == 40 and "<svg" in html or "viewBox" in html


def test_resolve_spec_finds_the_spec_beside_a_mod_folder(cfg, tmp_path, ring_spec):
    (tmp_path / "mymap").mkdir()
    ring_spec.save(tmp_path / "mymap.mapspec.json")
    assert resolve_spec(tmp_path / "mymap").meta.name == ring_spec.meta.name


def test_resolve_spec_explains_itself_when_there_is_no_spec(tmp_path):
    (tmp_path / "orphan").mkdir()
    with pytest.raises(FileNotFoundError, match="needs the spec"):
        resolve_spec(tmp_path / "orphan")


def test_svg_is_rendered_server_side(data):
    """The map must be in the HTML, so a JS failure cannot leave a blank page."""
    _, d = data
    html = render_html(d)
    assert '<svg id="svg"' in html
    assert html.count('class="lane') == len(d["lanes"])
    assert html.count('class="node"') == len(d["nodes"])
    assert html.count('class="lbl"') == len(d["nodes"]) - 1        # every node but the star
    assert "window.onerror" in html, "a script failure must surface, not look like a hang"


def test_server_keeps_working_while_a_connection_sits_idle():
    """Browsers preconnect and send nothing; a single-threaded server would block forever on that."""
    import socket
    import threading
    import urllib.request
    from mapgen.inspector import _Server, make_handler

    body = b"<!doctype html><title>t</title>ok"
    httpd = _Server(("127.0.0.1", 0), make_handler(body))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    idle = [socket.create_connection(("127.0.0.1", port)) for _ in range(3)]
    try:
        got = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read()
        assert got == body
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/favicon.ico", timeout=5).status == 204
    finally:
        for s in idle:
            s.close()
        httpd.shutdown()
        httpd.server_close()
