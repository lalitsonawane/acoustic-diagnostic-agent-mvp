"""Baseline-calibrated anomaly detector.

Scoring rule
------------
1. Each evidence channel ``c`` is standardised against a healthy baseline::

       z_c = (x_c - mean_c) / max(std_c, floor_c)

   Only positive deviations count (less impulsive than healthy is not a fault).
2. Channels are weighted and the *strongest* one drives the verdict::

       z = max_c  w_c * z_c

   A single strong channel (for example the envelope spectrum for a bearing defect,
   which is invisible above 20 kHz) is therefore enough to raise the alarm, and the
   per-channel contributions stay interpretable.
3. The score is a logistic squash to 0-100 %::

       score = 100 / (1 + exp(-(z - z_center) / z_scale))

   With the defaults a 3-sigma excursion scores 50 % and ~4.1 sigma reaches the 75 %
   critical threshold.

The optional ``demo_boost`` is added *after* scoring, flagged in the result, and is not a
measurement. It exists purely so a classroom demo can force the critical path.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from acoustic_agent.config import ExperimentConfig
from acoustic_agent.features import FeatureSet, extract_features
from acoustic_agent.synth import healthy_reference

CHANNELS: tuple[str, ...] = (
    "band_contrast_db",
    "band_contrast_transient_db",
    "band_power_db",
    "envelope_peak_snr_db",
    "residual_kurtosis",
    "residual_crest_factor",
)


@dataclass(frozen=True)
class Baseline:
    """Per-channel healthy statistics."""

    mean: dict[str, float]
    std: dict[str, float]
    n: int
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Baseline:
        return cls(mean=dict(data["mean"]), std=dict(data["std"]), n=int(data["n"]), source=str(data["source"]))

    @classmethod
    def from_features(cls, feature_sets: list[FeatureSet], source: str) -> Baseline:
        if len(feature_sets) < 2:
            raise ValueError("At least two healthy signals are required to build a baseline")
        mean: dict[str, float] = {}
        std: dict[str, float] = {}
        for channel in CHANNELS:
            values = np.array([fs.channels()[channel] for fs in feature_sets], dtype=float)
            values = values[np.isfinite(values)]
            if values.size == 0:
                mean[channel] = float("nan")
                std[channel] = float("nan")
                continue
            mean[channel] = float(values.mean())
            std[channel] = float(values.std(ddof=1)) if values.size > 1 else 0.0
        return cls(mean=mean, std=std, n=len(feature_sets), source=source)


def calibrate_baseline(config: ExperimentConfig) -> Baseline:
    """Healthy baseline from ``config.baseline_seeds`` synthetic renders of the profile."""
    seeds = range(10_000, 10_000 + config.baseline_seeds)
    feats = []
    for seed in seeds:
        sig = healthy_reference(config, seed)
        feats.append(extract_features(sig.audio, sig.sample_rate_hz, config))
    return Baseline.from_features(feats, source=f"synthetic-healthy:{config.machine().key}:{config.baseline_seeds}")


@dataclass(frozen=True)
class Detection:
    score: float
    raw_score: float
    z_combined: float
    z_by_channel: dict[str, float]
    weighted_z_by_channel: dict[str, float]
    driver: str | None
    demo_boost: float
    channels_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def logistic_score(z: float, z_center: float, z_scale: float) -> float:
    x = (z - z_center) / z_scale
    # Clamp to avoid overflow for absurd z values.
    x = max(-60.0, min(60.0, x))
    return 100.0 / (1.0 + math.exp(-x))


def score_features(features: FeatureSet, baseline: Baseline, config: ExperimentConfig) -> Detection:
    z_by: dict[str, float] = {}
    wz_by: dict[str, float] = {}
    used: list[str] = []
    values = features.channels()
    for channel in CHANNELS:
        x = values.get(channel, float("nan"))
        mu = baseline.mean.get(channel, float("nan"))
        sd = baseline.std.get(channel, float("nan"))
        floor = config.std_floors.get(channel, 1e-6)
        if not (math.isfinite(x) and math.isfinite(mu)):
            z_by[channel] = float("nan")
            wz_by[channel] = float("nan")
            continue
        sd_eff = max(sd if math.isfinite(sd) else 0.0, floor)
        z = max(0.0, (x - mu) / sd_eff)
        z_by[channel] = z
        wz_by[channel] = config.weights.get(channel, 0.0) * z
        used.append(channel)

    finite = {c: v for c, v in wz_by.items() if math.isfinite(v)}
    driver: str | None
    if finite:
        driver = max(finite, key=finite.__getitem__)
        z_combined = finite[driver]
        if z_combined <= 0.0:
            driver = None
    else:
        driver = None
        z_combined = 0.0

    raw = logistic_score(z_combined, config.z_center, config.z_scale)
    boosted = min(100.0, raw + max(0.0, config.demo_boost))
    return Detection(
        score=float(boosted),
        raw_score=float(raw),
        z_combined=float(z_combined),
        z_by_channel=z_by,
        weighted_z_by_channel=wz_by,
        driver=driver,
        demo_boost=float(config.demo_boost),
        channels_used=used,
    )
