from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime

import numpy as np
import pytest

from acoustic_agent import FEATURE_VERSION
from acoustic_agent.config import ExperimentConfig, config_hash
from acoustic_agent.decision import decide, health_state, illustrative_rul_days, work_order_payload
from acoustic_agent.detect import Baseline, calibrate_baseline, logistic_score, score_features
from acoustic_agent.features import extract_features
from acoustic_agent.synth import synthesize
from acoustic_agent.validate import Validity, assess_validity


def _features(cfg: ExperimentConfig, **overrides):
    sig = synthesize(cfg, **overrides)
    return extract_features(sig.audio, sig.sample_rate_hz, cfg)


# --- baseline -----------------------------------------------------------------------------


def test_baseline_roundtrip_and_source(baseline: Baseline, config: ExperimentConfig):
    assert baseline.n == config.baseline_seeds
    assert baseline.source.startswith("synthetic-healthy:")
    assert Baseline.from_dict(baseline.to_dict()) == baseline
    assert all(math.isfinite(v) for v in baseline.mean.values())


def test_baseline_needs_two_signals(config: ExperimentConfig):
    with pytest.raises(ValueError):
        Baseline.from_features([_features(config)], "x")


def test_baseline_ignores_nan_channels(config: ExperimentConfig):
    """At 16 kHz the ultrasonic channels are NaN; the baseline must still be buildable."""
    cfg = config.with_updates(sample_rate_hz=16_000)
    b = calibrate_baseline(cfg)
    assert math.isnan(b.mean["band_contrast_db"])
    assert math.isfinite(b.mean["residual_kurtosis"])


# --- scoring ------------------------------------------------------------------------------


def test_logistic_score_shape():
    assert logistic_score(3.0, 3.0, 1.0) == pytest.approx(50.0)
    assert logistic_score(-1e9, 3.0, 1.0) == pytest.approx(0.0)
    assert logistic_score(1e9, 3.0, 1.0) == pytest.approx(100.0)
    assert logistic_score(4.0, 3.0, 1.0) > logistic_score(3.5, 3.0, 1.0)


def test_healthy_signal_scores_low(config: ExperimentConfig, baseline: Baseline):
    det = score_features(_features(config), baseline, config)
    assert det.score < config.warn_threshold
    assert det.demo_boost == 0.0
    assert det.score == det.raw_score


def test_unseen_healthy_seeds_stay_below_warn(config: ExperimentConfig, baseline: Baseline):
    """False-alarm guard: healthy renders with seeds outside the calibration set."""
    for seed in (1, 7, 99, 2024, 31337):
        det = score_features(_features(config, seed=seed), baseline, config)
        assert det.score < config.warn_threshold, (seed, det.score, det.driver)


def test_ultrasonic_fault_is_critical_with_band_evidence(config: ExperimentConfig, baseline: Baseline):
    det = score_features(_features(config, inject_bursts=True), baseline, config)
    assert det.score > config.critical_threshold
    # Both spectral channels fire strongly; the bursts are also impulsive so kurtosis may
    # end up as the nominal driver. What matters is that ultrasonic evidence is present.
    assert det.z_by_channel["band_contrast_db"] > 4
    assert det.z_by_channel["band_contrast_transient_db"] > 4


def test_noisy_fault_is_caught_by_transient_channel(config: ExperimentConfig):
    """Regression for the shipped robotic_arm_fault_noisy_48k sample."""
    noisy = config.with_updates(noise_std=0.12)
    base = calibrate_baseline(noisy)
    det = score_features(_features(noisy, inject_bursts=True), base, noisy)
    assert det.score > noisy.critical_threshold
    assert det.driver == "band_contrast_transient_db"
    healthy = score_features(_features(noisy), base, noisy)
    assert healthy.score < noisy.warn_threshold


def test_bearing_fault_is_critical_via_impulsiveness(config: ExperimentConfig, baseline: Baseline):
    det = score_features(_features(config, inject_bearing_impacts=True), baseline, config)
    assert det.score > config.critical_threshold
    assert det.driver in {"envelope_peak_snr_db", "residual_kurtosis", "residual_crest_factor"}


def test_noisy_healthy_recording_does_not_alarm(config: ExperimentConfig):
    """Broadband noise must not be mistaken for an ultrasonic fault (band_power weight is 0)."""
    noisy = config.with_updates(noise_std=0.2)
    base = calibrate_baseline(noisy)
    det = score_features(_features(noisy), base, noisy)
    assert det.score < noisy.warn_threshold


def test_band_power_weight_zero_by_default(config: ExperimentConfig, baseline: Baseline):
    det = score_features(_features(config, inject_bursts=True), baseline, config)
    assert det.weighted_z_by_channel["band_power_db"] == 0.0
    assert det.z_by_channel["band_power_db"] > 0.0  # computed and displayed, just not scored


def test_z_scores_are_clipped_at_zero(config: ExperimentConfig, baseline: Baseline):
    det = score_features(_features(config), baseline, config)
    assert all(v >= 0.0 for v in det.z_by_channel.values() if math.isfinite(v))


def test_std_floor_prevents_explosive_z(config: ExperimentConfig, baseline: Baseline):
    tiny = replace(baseline, std={k: 1e-9 for k in baseline.std})
    det = score_features(_features(config, seed=5), tiny, config)
    assert det.z_combined < 5.0  # floors, not raw std, govern the scale


def test_demo_boost_is_additive_and_recorded(config: ExperimentConfig, baseline: Baseline):
    boosted = config.with_updates(demo_boost=30.0)
    det = score_features(_features(config), baseline, boosted)
    assert det.demo_boost == 30.0
    assert det.score == pytest.approx(min(100.0, det.raw_score + 30.0))


def test_channels_with_nan_are_skipped(config: ExperimentConfig, baseline: Baseline):
    cfg = config.with_updates(sample_rate_hz=16_000)
    feats = _features(cfg)
    det = score_features(feats, baseline, cfg)
    assert "band_contrast_db" not in det.channels_used
    assert math.isnan(det.z_by_channel["band_contrast_db"])
    assert math.isfinite(det.score)


# --- validity -----------------------------------------------------------------------------


def test_silence_is_invalid(config: ExperimentConfig):
    feats = extract_features(np.zeros(48_000, dtype=np.float32), 48_000, config)
    v = assess_validity(feats, config)
    assert not v.valid and v.confidence == 0.0 and "silence" in v.flags


def test_short_capture_penalised(config: ExperimentConfig):
    rng = np.random.default_rng(0)
    feats = extract_features(rng.normal(scale=0.1, size=4_800).astype(np.float32), 48_000, config)
    v = assess_validity(feats, config)
    assert v.valid and "short" in v.flags and v.confidence == pytest.approx(0.5)


def test_low_sample_rate_penalised(config: ExperimentConfig):
    rng = np.random.default_rng(0)
    feats = extract_features(rng.normal(scale=0.1, size=32_000).astype(np.float32), 16_000, config)
    v = assess_validity(feats, config)
    assert "band_unavailable" in v.flags
    assert v.confidence < config.min_confidence


def test_clipping_penalised(config: ExperimentConfig):
    x = np.clip(np.random.default_rng(0).normal(scale=2.0, size=96_000), -1, 1).astype(np.float32)
    feats = extract_features(x, 48_000, config)
    v = assess_validity(feats, config)
    assert "clipping" in v.flags


def test_penalties_compound():
    v = Validity()
    v.penalise(0.5, "a", "A")
    v.penalise(0.5, "b", "B")
    assert v.confidence == pytest.approx(0.25)
    assert v.flags == ["a", "b"]


# --- decision -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "conf", "valid", "expected"),
    [
        (10, 1.0, True, "HEALTHY"),
        (70, 1.0, True, "WARNING"),
        (90, 1.0, True, "CRITICAL"),
        (90, 0.3, True, "CRITICAL (unconfirmed)"),
        (90, 1.0, False, "INVALID"),
    ],
)
def test_health_state(score, conf, valid, expected, config: ExperimentConfig):
    assert health_state(score, conf, valid, config) == expected


def test_rul_monotonic_and_floored(config: ExperimentConfig):
    p = config.machine()
    assert illustrative_rul_days(p, 0) >= illustrative_rul_days(p, 50) >= illustrative_rul_days(p, 100) >= 3


def test_decide_only_actionable_when_confirmed_critical(config: ExperimentConfig, baseline: Baseline):
    det = score_features(_features(config, inject_bursts=True), baseline, config)
    ok = decide(det, Validity(), config.machine(), config)
    assert ok.state == "CRITICAL" and ok.actionable and ok.rul_days is not None
    assert "standard deviations above the healthy baseline" in ok.explanation

    low = Validity()
    low.penalise(0.4, "band_unavailable", "Nyquist too low.")
    unconfirmed = decide(det, low, config.machine(), config)
    assert unconfirmed.state == "CRITICAL (unconfirmed)" and not unconfirmed.actionable
    assert "Nyquist too low." in unconfirmed.explanation

    bad = Validity()
    bad.invalidate("silence", "Silent.")
    invalid = decide(det, bad, config.machine(), config)
    assert invalid.state == "INVALID" and invalid.rul_days is None and invalid.explanation == "Silent."


def test_healthy_explanation_does_not_cite_weak_driver(config: ExperimentConfig, baseline: Baseline):
    det = score_features(_features(config), baseline, config)
    d = decide(det, Validity(), config.machine(), config)
    assert "No channel deviates meaningfully" in d.explanation


def test_work_order_payload_is_traceable(config: ExperimentConfig, baseline: Baseline):
    det = score_features(_features(config, inject_bursts=True), baseline, config)
    d = decide(det, Validity(), config.machine(), config)
    now = datetime(2026, 9, 2, 6, 0, tzinfo=UTC)
    wo = work_order_payload(config.machine(), det, d, config, now=now, source="synthetic")
    assert wo["ticket_id"].startswith("WO-20260902-")
    assert wo["priority"].startswith("P1")
    assert wo["config_hash"] == config_hash(config)
    assert wo["feature_version"] == FEATURE_VERSION
    assert wo["demo_boost_applied"] is False
    assert wo["suggested_window_start"].startswith("2026-09-04T22:00")
