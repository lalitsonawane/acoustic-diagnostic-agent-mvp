from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("MPLBACKEND", "Agg")

# Isolate SQLite history from the developer's real cache during tests.
_TEST_DATA = Path(__file__).resolve().parent / ".tmp_acoustic_agent_data"
_TEST_DATA.mkdir(exist_ok=True)
os.environ["ACOUSTIC_AGENT_DATA_DIR"] = str(_TEST_DATA)

from acoustic_agent.config import ExperimentConfig
from acoustic_agent.detect import Baseline, calibrate_baseline

REPO = Path(__file__).resolve().parent.parent
SAMPLES = REPO / "data" / "samples"


@pytest.fixture(scope="session")
def config() -> ExperimentConfig:
    return ExperimentConfig()


@pytest.fixture(scope="session")
def baseline(config: ExperimentConfig) -> Baseline:
    return calibrate_baseline(config)


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    return SAMPLES


@pytest.fixture(autouse=True)
def _clean_test_store() -> None:
    """Start each test with an empty persistent store (session log stays per AppTest)."""
    from acoustic_agent.store import RunStore

    store = RunStore(_TEST_DATA / "history.sqlite3")
    store.clear()
    yield
