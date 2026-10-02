"""`generate_map.py setup`: store an Anthropic API key in .env, for the opt-in API path.

The key is read with hidden input, written only to .env, and never echoed, printed or logged.
"""
from __future__ import annotations

import getpass
import os
import re
import subprocess
import sys
from pathlib import Path

from .. import ROOT
from .client import env_path

KEY_PATTERN = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,}$")
VAR = "ANTHROPIC_API_KEY"


def looks_like_key(key: str) -> tuple[bool, str]:
    if not key:
        return False, "nothing entered"
    if key != key.strip():
        return False, "there is whitespace around the key"
    if " " in key or "\n" in key:
        return False, "the key contains whitespace"
    if not key.startswith("sk-ant-"):
        return False, "an Anthropic key starts with 'sk-ant-'"
    if not KEY_PATTERN.match(key):
        return False, "that does not look like a full key (too short, or unexpected characters)"
    return True, ""


def write_key(key: str, path: Path) -> None:
    """Replace or append ANTHROPIC_API_KEY, keeping every other line intact."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, replaced = [], False
    for line in lines:
        if line.startswith(f"{VAR}=") or line.startswith(f"#{VAR}="):
            if not replaced:
                out.append(f"{VAR}={key}")
                replaced = True
            continue
        out.append(line)
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{VAR}={key}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    try:                                    # best effort; Windows ACLs are not POSIX modes
        os.chmod(path, 0o600)
    except OSError:
        pass


def is_ignored(path: Path) -> bool:
    try:
        r = subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=ROOT,
                           capture_output=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        gitignore = ROOT / ".gitignore"
        return gitignore.exists() and ".env" in gitignore.read_text(encoding="utf-8").split()


def ensure_ignored(path: Path) -> bool:
    """True if the file is ignored, adding a .gitignore rule when it is ours to add.

    Only ever touches the repo's .gitignore for a file inside the repo, and never writes a rule that is
    already there - otherwise a redirected MAPGEN_ENV_PATH would keep appending to it.
    """
    if is_ignored(path):
        return True
    gitignore = ROOT / ".gitignore"
    if not path.resolve().is_relative_to(ROOT.resolve()) or path.name != ".env" or not gitignore.exists():
        return False
    text = gitignore.read_text(encoding="utf-8")
    if ".env" in text.split():
        return False                       # already listed; something else is unignoring it
    gitignore.write_text(text + ("" if text.endswith("\n") else "\n") + ".env\n",
                         encoding="utf-8", newline="\n")
    return is_ignored(path)


def run(from_stdin: bool = False) -> int:
    path = env_path()
    existing = os.environ.get(VAR)
    if existing and not from_stdin:
        print(f"{VAR} is already set in this environment, so no .env is needed.")
        print("Writing one anyway is fine - press Ctrl-C to keep the environment variable only.")
    print("Get a key at https://console.anthropic.com/settings/keys")
    print("It is stored only in this file and never printed or logged:")
    print(f"  {path}")
    try:
        key = sys.stdin.readline().strip() if from_stdin else getpass.getpass("Paste your API key (hidden): ")
    except (EOFError, KeyboardInterrupt):
        print("\ncancelled; nothing was written")
        return 1
    ok, why = looks_like_key(key)
    if not ok:
        print(f"error: {why}. Nothing was written.")
        return 2
    write_key(key, path)
    print(f"saved to {path}")
    inside_repo = path.resolve().is_relative_to(ROOT.resolve())
    ignored = True
    if inside_repo:
        ignored = ensure_ignored(path)
        print("git-ignored: yes" if ignored
              else f"WARNING: {path} is NOT git-ignored - add it to .gitignore before committing")
    else:
        print("outside the repo, so it cannot be committed by accident")
    print("Try it:  .venv\\Scripts\\python generate_map.py ai \"4 players, 40 planets, ring\" --dry-run")
    print("Costs:   about $0.06-0.12 per call; see README.md 'Path B'.")
    return 0 if ignored else 1
