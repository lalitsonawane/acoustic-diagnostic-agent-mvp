from __future__ import annotations

import pytest

from acoustic_agent.config import ExperimentConfig, config_hash, sweepable_parameters


def test_roundtrip_yaml_and_json(tmp_path):
    cfg = ExperimentConfig(noise_std=0.05, inject_bursts=True, weights={**ExperimentConfig().weights, "band_power_db": 0.3})
    yaml_path, json_path = tmp_path / "c.yaml", tmp_path / "c.json"
    cfg.save(yaml_path)
    cfg.save(json_path)
    assert ExperimentConfig.load(yaml_path) == cfg
    assert ExperimentConfig.load(json_path) == cfg
    assert ExperimentConfig.from_text(cfg.to_json()) == cfg


def test_hash_is_stable_and_sensitive():
    a, b = ExperimentConfig(), ExperimentConfig()
    assert config_hash(a) == config_hash(b)
    assert len(config_hash(a)) == 12
    assert config_hash(a.with_updates(seed=43)) != config_hash(a)


def test_unknown_key_rejected():
    with pytest.raises(ValueError, match="Unknown configuration keys"):
        ExperimentConfig.from_dict({"not_a_field": 1})


@pytest.mark.parametrize(
    "changes",
    [
        {"profile": "Nope"},
        {"duration_s": 0},
        {"band_low_hz": 25_000, "band_high_hz": 24_000},
        {"warn_threshold": 80, "critical_threshold": 75},
        {"min_confidence": 1.5},
        {"baseline_seeds": 1},
        {"z_scale": 0},
    ],
)
def test_validation_errors(changes):
    with pytest.raises(ValueError):
        ExperimentConfig(**changes).validate()


def test_from_text_rejects_non_mapping():
    with pytest.raises(ValueError):
        ExperimentConfig.from_text("- a\n- b\n")


def test_sweepable_parameters_exist_on_config():
    cfg = ExperimentConfig()
    for name in sweepable_parameters():
        assert hasattr(cfg, name)
