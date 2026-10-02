import io
import json
import zipfile

import pytest
from jsonschema import Draft7Validator, Draft202012Validator

from mapgen.pipeline import build
from mapgen.validate import ValidatorBroken, _schema, self_test, validate_mod


@pytest.fixture
def built(ring_spec, params, cfg, tmp_path):
    res = build(ring_spec, params, cfg, tmp_path)
    assert res.ok, [str(p) for p in res.problems]
    return res


def rewrite_member(scenario, member, fn):
    with zipfile.ZipFile(scenario) as z:
        members = {n: z.read(n) for n in z.namelist()}
    members[member] = fn(members[member])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, data in members.items():
            z.writestr(n, data)
    scenario.write_bytes(buf.getvalue())


def test_default_mod_is_valid(built, cfg):
    assert validate_mod(built.mod_dir, cfg) == []
    names = sorted(p.relative_to(built.mod_dir).as_posix() for p in built.mod_dir.rglob("*") if p.is_file())
    assert names == [".mod_meta_data", "localized_text/en.localized_text", "picture.png",
                     f"scenarios/{built.compiled.spec.meta.name}.scenario", "uniforms/scenario.uniforms"]


def test_self_test_rejects_a_permissive_validator(built, cfg):
    schema = _schema(cfg, "galaxy-chart-schema.json")
    with zipfile.ZipFile(next((built.mod_dir / "scenarios").glob("*.scenario"))) as z:
        chart = json.loads(z.read("galaxy_chart.json"))
    self_test(Draft202012Validator(schema), chart)  # the real one bites
    with pytest.raises(ValidatorBroken):
        self_test(Draft7Validator(schema), chart)   # draft-07 ignores unevaluatedProperties


def test_bogus_field_in_chart_fails(built, cfg):
    scen = next((built.mod_dir / "scenarios").glob("*.scenario"))

    def add_bogus(raw):
        c = json.loads(raw)
        c["root_nodes"][0]["child_nodes"][0]["bogus_field"] = 1
        return json.dumps(c).encode()
    rewrite_member(scen, "galaxy_chart.json", add_bogus)
    probs = validate_mod(built.mod_dir, cfg)
    assert any("galaxy_chart.json" in p.file and "bogus_field" in p.message for p in probs)


def test_scenario_info_key_not_in_vanilla_fails(built, cfg):
    scen = next((built.mod_dir / "scenarios").glob("*.scenario"))
    rewrite_member(scen, "scenario_info.json", lambda raw: json.dumps({**json.loads(raw), "made_up": 1}).encode())
    probs = validate_mod(built.mod_dir, cfg)
    assert any("scenario_info.json" in p.file and "made_up" in p.message for p in probs)


def test_uniforms_missing_required_array_fails(built, cfg):
    p = built.mod_dir / "uniforms" / "scenario.uniforms"
    data = json.loads(p.read_text())
    del data["dlc_scenarios"]
    p.write_text(json.dumps(data))
    probs = validate_mod(built.mod_dir, cfg)
    assert any("scenario.uniforms" in x.file and "dlc_scenarios" in x.message for x in probs)


def test_rule_violation_writes_nothing(ring_spec, params, cfg, tmp_path):
    from mapgen.spec import Link
    ring_spec.links.append(Link("filler", "core", "normal"))
    res = build(ring_spec, params, cfg, tmp_path)
    assert not res.ok and res.mod_dir is None
    assert not any(tmp_path.iterdir())


def test_unpack_pack_round_trip_is_byte_identical(ring_spec, params, cfg, tmp_path):
    """Solar Forge reads folders, the game reads the zip. The trip between them must lose nothing.

    Added 2026-09-27. Member bytes are taken exactly as they sit on disk, so whatever the editor
    wrote is what the game gets; only the zip envelope is ours, and it is fixed (1980 timestamps,
    sorted entries), so packing the same folder twice gives the same bytes.
    """
    from mapgen.scenario_writer import pack_scenario, unpack_scenario
    res = build(ring_spec, params, cfg, tmp_path / "mod")
    assert res.ok
    scenario = next((res.mod_dir / "scenarios").glob("*.scenario"))
    original = scenario.read_bytes()

    folder = tmp_path / "unpacked"
    names = unpack_scenario(scenario, folder)
    assert "galaxy_chart.json" in names and "scenario_info.json" in names

    pack_scenario(folder, scenario)
    assert scenario.read_bytes() == original


def test_pack_refuses_a_folder_that_is_not_a_scenario(tmp_path):
    from mapgen.scenario_writer import ScenarioError, pack_scenario
    folder = tmp_path / "junk"
    folder.mkdir()
    (folder / "notes.txt").write_text("hello", encoding="utf-8")
    with pytest.raises(ScenarioError) as exc:
        pack_scenario(folder, tmp_path / "x.scenario")
    assert "galaxy_chart.json" in str(exc.value)
