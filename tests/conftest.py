import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mapgen.config import ConfigError, load_config  # noqa: E402
from mapgen.params import MapParams  # noqa: E402
from mapgen.templates import build_ring  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    try:
        c = load_config()
    except ConfigError as exc:
        pytest.skip(str(exc))
    if not c.schema_dir.exists() or not c.game_dir.exists():
        pytest.skip("schema_dir or game_dir from config.toml not present on this machine")
    return c


@pytest.fixture
def params():
    return MapParams()


@pytest.fixture
def ring_spec(params, cfg):
    return build_ring(params, cfg.limits.max_bodies_per_star)


@pytest.fixture(autouse=True)
def _non_interactive_ai(monkeypatch):
    """Tests never prompt and never spend: mocked clients only, fresh session totals each test."""
    from mapgen.ai.client import POLICY, Session
    import mapgen.ai.client as client_mod
    monkeypatch.setattr(POLICY, "assume_yes", True)
    monkeypatch.setattr(POLICY, "max_cost", 1000.0)
    monkeypatch.setattr(client_mod, "SESSION", Session())
    monkeypatch.setattr(client_mod, "LOG_PATH", client_mod.ROOT / "out" / "test_ai_log.jsonl")
    monkeypatch.setenv("MAPGEN_NO_OPEN", "1")   # never spawn an image viewer from a test
