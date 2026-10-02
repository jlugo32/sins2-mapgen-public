import json
import zipfile
from dataclasses import replace

from mapgen.pipeline import build
from mapgen.templates import build_ring


def tree_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_same_spec_and_seed_is_byte_identical(ring_spec, params, cfg, tmp_path):
    a = build(ring_spec, params, cfg, tmp_path / "a")
    b = build(ring_spec, params, cfg, tmp_path / "b")
    assert a.ok and b.ok
    assert tree_bytes(a.mod_dir) == tree_bytes(b.mod_dir)
    assert a.preview.read_bytes() == b.preview.read_bytes()


def test_zip_timestamps_are_fixed(ring_spec, params, cfg, tmp_path):
    res = build(ring_spec, params, cfg, tmp_path)
    with zipfile.ZipFile(next((res.mod_dir / "scenarios").glob("*.scenario"))) as z:
        assert {i.date_time for i in z.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        assert [i.filename for i in z.infolist()] == sorted(i.filename for i in z.infolist())


def test_different_seed_changes_layout(params, cfg, tmp_path):
    def chart(seed):
        res = build(build_ring(replace(params, seed=seed), 150), params, cfg, tmp_path / str(seed))
        with zipfile.ZipFile(next((res.mod_dir / "scenarios").glob("*.scenario"))) as z:
            return json.loads(z.read("galaxy_chart.json"))
    assert chart(1) != chart(2)


def test_mapspec_round_trip_is_byte_identical(ring_spec, params, cfg, tmp_path):
    """Template -> MapSpec -> file -> MapSpec must give the same bytes, spec and mod alike."""
    from mapgen.spec import load
    a, b = tmp_path / "a.mapspec.json", tmp_path / "b.mapspec.json"
    ring_spec.save(a)
    reloaded = load(a)
    reloaded.save(b)
    assert a.read_bytes() == b.read_bytes()
    assert reloaded.to_dict() == ring_spec.to_dict()
    from_template = build(ring_spec, params, cfg, tmp_path / "tpl")
    from_file = build(reloaded, params, cfg, tmp_path / "spec")
    assert tree_bytes(from_template.mod_dir) == tree_bytes(from_file.mod_dir)
    assert from_template.preview.read_bytes() == from_file.preview.read_bytes()


def test_committed_spec_matches_the_template(ring_spec, tmp_path):
    """specs/ww2_rimward_front.mapspec.json is the default ring template, byte for byte."""
    from mapgen import ROOT
    out = tmp_path / "x.json"
    ring_spec.save(out)
    assert out.read_bytes() == (ROOT / "specs" / "ww2_rimward_front.mapspec.json").read_bytes()
