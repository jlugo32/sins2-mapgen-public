"""Key setup and the no-key paths. Never touches the real .env (MAPGEN_ENV_PATH is redirected)."""
import json
import os
import subprocess
import sys

import pytest

from mapgen import ROOT
from mapgen.ai.setup_key import ensure_ignored, looks_like_key, write_key

FAKE = "sk-ant-api03-" + "A1b2C3d4E5f6G7h8I9j0" * 2


def run_cli(args, env=None, stdin=""):
    e = {**os.environ, "ANTHROPIC_API_KEY": "", **(env or {})}
    e.pop("ANTHROPIC_API_KEY") if e.get("ANTHROPIC_API_KEY") == "" else None
    return subprocess.run([sys.executable, "generate_map.py", *args], cwd=ROOT, input=stdin,
                          capture_output=True, text=True, timeout=120, env=e)


@pytest.mark.parametrize("key,ok", [
    (FAKE, True),
    ("", False),
    ("sk-ant-short", False),
    ("not-a-key-at-all", False),
    (f" {FAKE} ", False),
    ("sk-ant-api03-has space inside here 1234567890", False),
])
def test_key_format_is_validated(key, ok):
    assert looks_like_key(key)[0] is ok


def test_write_key_creates_the_file(tmp_path):
    env = tmp_path / ".env"
    write_key(FAKE, env)
    assert env.read_text(encoding="utf-8") == f"ANTHROPIC_API_KEY={FAKE}\n"


def test_write_key_replaces_without_losing_other_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text("MAPGEN_MODEL=claude-sonnet-5\nANTHROPIC_API_KEY=sk-ant-old\nOTHER=1\n", encoding="utf-8")
    write_key(FAKE, env)
    text = env.read_text(encoding="utf-8")
    assert f"ANTHROPIC_API_KEY={FAKE}" in text and "sk-ant-old" not in text
    assert "MAPGEN_MODEL=claude-sonnet-5" in text and "OTHER=1" in text
    assert text.count("ANTHROPIC_API_KEY=") == 1


def test_setup_cli_writes_env_and_never_echoes_the_key():
    """Inside the repo: the file must land git-ignored (out/ is ignored, so it stands in for .env)."""
    env_file = ROOT / "out" / "test_setup.env"
    env_file.unlink(missing_ok=True)
    try:
        r = run_cli(["setup", "--from-stdin"], env={"MAPGEN_ENV_PATH": str(env_file)}, stdin=FAKE + "\n")
        assert r.returncode == 0, r.stdout + r.stderr
        assert env_file.read_text(encoding="utf-8").strip() == f"ANTHROPIC_API_KEY={FAKE}"
        assert FAKE not in r.stdout and FAKE not in r.stderr, "the key must never be echoed"
        assert FAKE[-8:] not in r.stdout, "not even the tail of the key"
        assert str(env_file) in r.stdout and "git-ignored: yes" in r.stdout
    finally:
        env_file.unlink(missing_ok=True)


def test_setup_outside_the_repo_says_so(tmp_path):
    env_file = tmp_path / ".env"
    r = run_cli(["setup", "--from-stdin"], env={"MAPGEN_ENV_PATH": str(env_file)}, stdin=FAKE + "\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert env_file.exists() and "outside the repo" in r.stdout


def test_setup_cli_rejects_a_bad_key_and_writes_nothing(tmp_path):
    env_file = tmp_path / ".env"
    r = run_cli(["setup", "--from-stdin"], env={"MAPGEN_ENV_PATH": str(env_file)}, stdin="hunter2\n")
    assert r.returncode == 2 and not env_file.exists()
    assert "sk-ant-" in r.stdout and "Nothing was written" in r.stdout


def test_ai_without_a_key_explains_itself(tmp_path):
    r = run_cli(["ai", "four player ring"], env={"MAPGEN_ENV_PATH": str(tmp_path / "missing.env")})
    assert r.returncode == 2
    assert "Traceback" not in r.stderr
    for needle in ("No Anthropic API key found", "generate_map.py setup", "sins2-map skill", "Path A"):
        assert needle in r.stdout, needle


def test_skill_path_works_with_no_key_at_all(tmp_path):
    """Path A: building from a spec must never need a key."""
    r = run_cli(["build", "--spec", "specs/skill_test_quad.mapspec.json"],
                env={"MAPGEN_ENV_PATH": str(tmp_path / "missing.env")})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "mod:" in r.stdout and "ANTHROPIC" not in r.stdout


def test_env_is_gitignored():
    assert ensure_ignored(ROOT / ".env"), ".env must be git-ignored"


def test_ensure_ignored_never_touches_the_repo_gitignore_for_an_outside_path(tmp_path):
    """A redirected MAPGEN_ENV_PATH must not append rules to the repo's .gitignore."""
    gitignore = ROOT / ".gitignore"
    before = gitignore.read_text(encoding="utf-8")
    assert ensure_ignored(tmp_path / ".env") is False
    assert gitignore.read_text(encoding="utf-8") == before
    assert before.split().count(".env") == 1, "exactly one .env rule"
