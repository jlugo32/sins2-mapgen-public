"""Every text file the generator writes uses LF only, on every OS.

PNGs are exempt: the PNG signature itself is b"\\x89PNG\\r\\n\\x1a\\n". The .scenario zip container is
compressed binary, so its members are checked instead of its raw bytes.
"""
import importlib.util
import shutil
import zipfile
from pathlib import Path

from mapgen import ROOT
from mapgen.pipeline import build

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def assert_lf(name: str, data: bytes) -> None:
    if name.endswith(".png"):
        assert data.startswith(PNG_SIG), f"{name}: not a PNG"
        return
    assert b"\r\n" not in data, f"{name}: contains CRLF"
    assert b"\r" not in data, f"{name}: contains CR"


def test_generated_files_are_lf_only(ring_spec, params, cfg, tmp_path):
    res = build(ring_spec, params, cfg, tmp_path)
    assert res.ok
    checked = 0
    for p in sorted(tmp_path.rglob("*")):
        if not p.is_file():
            continue
        checked += 1
        if p.suffix != ".scenario":  # the zip container is compressed binary; its members are checked below
            assert_lf(p.name, p.read_bytes())
        else:
            with zipfile.ZipFile(p) as z:
                for member in z.namelist():
                    assert_lf(f"{p.name}:{member}", z.read(member))
                    checked += 1
    # mod (5 files) + 4 zip members + preview + saved spec
    assert checked == 11


def test_build_fillings_writes_lf(cfg, tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("build_fillings", ROOT / "tools" / "build_fillings.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    (tmp_path / "data").mkdir()
    shutil.copy(ROOT / "config.toml", tmp_path / "config.toml")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    assert mod.main() == 0
    out = tmp_path / "data" / "fillings.json"
    assert_lf(out.name, out.read_bytes())
    assert out.read_bytes() == (ROOT / "data" / "fillings.json").read_bytes()


def test_spec_save_writes_lf(ring_spec, tmp_path):
    p = Path(tmp_path) / "x.mapspec.json"
    ring_spec.save(p)
    assert_lf(p.name, p.read_bytes())
