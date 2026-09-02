from __future__ import annotations

import numpy as np

from acoustic_agent.config import ExperimentConfig
from acoustic_agent.features import (
    Spectrum,
    band_contrast_db,
    crest_factor,
    detect_impulses,
    envelope_peak,
    extract_features,
    kurtosis,
    welch_psd,
)
from acoustic_agent.synth import Signal, healthy_reference, synthesize

CHANNELS = {
    "band_power_db",
    "band_contrast_db",
    "band_contrast_transient_db",
    "residual_kurtosis",
    "residual_crest_factor",
    "envelope_peak_snr_db",
}


def _feats(sig: Signal, cfg: ExperimentConfig) -> dict[str, float]:
    return extract_features(sig.audio, sig.sample_rate_hz, cfg).channels()


def test_synthesis_is_deterministic_and_bounded():
    cfg = ExperimentConfig(inject_bursts=True, inject_bearing_impacts=True)
    a, b = synthesize(cfg), synthesize(cfg)
    assert np.array_equal(a.audio, b.audio)
    assert a.sample_rate_hz == cfg.sample_rate_hz
    assert a.audio.shape == (int(cfg.sample_rate_hz * cfg.duration_s),)
    assert a.audio.dtype == np.float32
    assert np.max(np.abs(a.audio)) <= 1.0 + 1e-6
    assert abs(a.duration_s - cfg.duration_s) < 1e-9


def test_seed_and_overrides_change_signal():
    cfg = ExperimentConfig()
    assert not np.array_equal(synthesize(cfg, seed=1).audio, synthesize(cfg, seed=2).audio)
    assert not np.array_equal(synthesize(cfg).audio, synthesize(cfg, inject_bursts=True).audio)
    assert np.array_equal(healthy_reference(cfg, cfg.seed).audio, synthesize(cfg).audio)


def test_feature_channels_finite():
    cfg = ExperimentConfig()
    fs = extract_features(synthesize(cfg).audio, cfg.sample_rate_hz, cfg)
    assert set(fs.channels()) == CHANNELS
    assert all(np.isfinite(v) for v in fs.channels().values())
    assert fs.band_available and fs.reference_band_available
    assert 0 <= fs.clipping_fraction <= 1


def test_features_invariant_to_gain():
    """All scored channels are ratio-based and must not depend on recording gain."""
    cfg = ExperimentConfig(inject_bursts=True, inject_bearing_impacts=True)
    sig = synthesize(cfg)
    quiet = Signal(sig.audio * 0.05, sig.sample_rate_hz, "quiet")
    f1, f2 = _feats(sig, cfg), _feats(quiet, cfg)
    for name in CHANNELS:
        assert abs(f1[name] - f2[name]) < 0.25, name


def test_ultrasonic_bursts_raise_band_contrast():
    cfg = ExperimentConfig()
    healthy = _feats(synthesize(cfg), cfg)
    faulty = _feats(synthesize(cfg, inject_bursts=True), cfg)
    assert faulty["band_contrast_db"] > healthy["band_contrast_db"] + 3


def test_transient_contrast_finds_bursts_under_heavy_noise():
    """Welch averaging dilutes 12 ms bursts under 16 dB more noise; the per-frame spread must not."""
    noisy = ExperimentConfig(noise_std=0.12)
    healthy = _feats(synthesize(noisy), noisy)
    faulty = _feats(synthesize(noisy, inject_bursts=True), noisy)
    assert healthy["band_contrast_transient_db"] < 2.5  # stationary noise, any level
    assert faulty["band_contrast_transient_db"] > healthy["band_contrast_transient_db"] + 4
    # whereas the averaged contrast barely moves on this input
    assert faulty["band_contrast_db"] - healthy["band_contrast_db"] < 1.5


def test_bearing_impacts_raise_impulsiveness_channels():
    cfg = ExperimentConfig()
    healthy = _feats(synthesize(cfg), cfg)
    faulty = _feats(synthesize(cfg, inject_bearing_impacts=True), cfg)
    assert faulty["envelope_peak_snr_db"] > healthy["envelope_peak_snr_db"] + 3
    assert faulty["residual_kurtosis"] > healthy["residual_kurtosis"] + 0.5
    assert faulty["residual_crest_factor"] > healthy["residual_crest_factor"]


def test_low_sample_rate_marks_band_unavailable():
    cfg = ExperimentConfig()
    rng = np.random.default_rng(0)
    fs = extract_features(rng.normal(size=16_000).astype(np.float32), 16_000, cfg)
    assert not fs.band_available
    assert np.isnan(fs.band_power_db) and np.isnan(fs.band_contrast_db) and np.isnan(fs.band_contrast_transient_db)
    # impulsiveness channels still work at 16 kHz
    assert np.isfinite(fs.residual_kurtosis)


def test_white_noise_band_contrast_near_zero():
    rng = np.random.default_rng(1)
    x = rng.normal(size=96_000)
    spec = welch_psd(x, 48_000)
    assert abs(band_contrast_db(spec, (20_000, 24_000), (10_000, 14_000))) < 1.0


def test_kurtosis_and_crest_edge_cases():
    assert np.isnan(kurtosis(np.ones(100)))
    assert np.isnan(crest_factor(np.zeros(100)))
    rng = np.random.default_rng(2)
    g = rng.normal(size=200_000)
    assert abs(kurtosis(g) - 3.0) < 0.1
    assert crest_factor(np.array([1.0, -1.0, 1.0, -1.0])) == 1.0


def test_envelope_peak_finds_repetition_rate():
    fs = 48_000
    t = np.arange(fs) / fs
    rate = 97.0
    impulses = (np.sin(2 * np.pi * rate * t) > 0.995).astype(float)  # short pulses at `rate` Hz
    carrier = impulses * np.sin(2 * np.pi * 8_000 * t)
    from acoustic_agent.features import envelope_spectrum

    hz, snr = envelope_peak(envelope_spectrum(carrier, fs), 20, 500)
    assert abs(hz - rate) < 2.0
    assert snr > 10


def test_detect_impulses_counts_events():
    fs = 48_000
    x = np.random.default_rng(3).normal(scale=0.01, size=fs)
    for i in range(10, fs, fs // 10):
        x[i : i + 20] += 1.0
    peaks = detect_impulses(x, fs)
    assert 8 <= peaks.size <= 12


def test_empty_spectrum_band_power_is_zero():
    assert Spectrum(np.array([0.0, 1.0]), np.array([1.0, 1.0])).band_power(10, 20) == 0.0
