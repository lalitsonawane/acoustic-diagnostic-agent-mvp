from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("MPLBACKEND", "Agg")

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
