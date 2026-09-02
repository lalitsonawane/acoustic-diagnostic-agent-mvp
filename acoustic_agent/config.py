"""Typed experiment configuration with JSON/YAML import and export.

Every parameter that used to be hard-coded in the MVP lives here so that a run can be
reproduced from its configuration alone. :func:`config_hash` gives a short, stable
identifier that is written into run logs and work-order payloads.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class MachineProfile:
    """Static description of a monitored asset."""

    name: str
    key: str
    part: str
    base_frequency_hz: float
    nominal_rul_days: int
    signature: str


MACHINE_PROFILES: dict[str, MachineProfile] = {
    "Robotic Arm Bearings": MachineProfile(
        name="Robotic Arm Bearings",
        key="robotic_arm",
        part="RB-6204-2RS",
        base_frequency_hz=440.0,
        nominal_rul_days=86,
        signature="Bearing race / micro-crack",
    ),
    "Stamping Press": MachineProfile(
        name="Stamping Press",
        key="stamping_press",
        part="SP-ROLLER-18",
        base_frequency_hz=220.0,
        nominal_rul_days=142,
        signature="Drive train resonance",
    ),
    "Conveyor Drive": MachineProfile(
        name="Conveyor Drive",
        key="conveyor_drive",
        part="CV-MOTOR-07",
        base_frequency_hz=330.0,
        nominal_rul_days=119,
        signature="Motor / gearbox harmonic",
    ),
}

PROFILE_BY_KEY: dict[str, MachineProfile] = {p.key: p for p in MACHINE_PROFILES.values()}


def default_weights() -> dict[str, float]:
    """Relative weight of each evidence channel when combining z-scores.

    The combined z is the maximum of the weighted channel z-scores, so a weight of 1.0
    means "this channel alone can drive the verdict"; smaller weights make a channel
    supporting evidence only.
    """
    return {
        "band_contrast_db": 1.0,
        # Time-resolved contrast catches short bursts buried in broadband noise that the
        # whole-capture Welch estimate averages away.
        "band_contrast_transient_db": 1.0,
        # band_power_db rises with *any* broadband noise, so a naive high-band detector
        # false-alarms on noisy-but-healthy recordings. It is computed and displayed for
        # teaching, but excluded from the verdict by default. Set > 0 to see the effect.
        "band_power_db": 0.0,
        "envelope_peak_snr_db": 1.0,
        "residual_kurtosis": 0.8,
        "residual_crest_factor": 0.6,
    }


def default_std_floors() -> dict[str, float]:
    """Minimum baseline spread per channel.

    Synthetic baselines are almost perfectly repeatable, so their raw standard deviation
    is tiny and would turn any deviation into an enormous z-score. The floors encode the
    smallest spread we consider physically plausible for each unit (dB, ratio, ...).
    """
    return {
        "band_contrast_db": 0.75,
        # Percentile-minus-median of noisy frames; ~1.2-1.6 dB for stationary noise, so a
        # 1 dB floor keeps a 4 sigma alarm at >= 5.5 dB of transient contrast.
        "band_contrast_transient_db": 1.0,
        "band_power_db": 0.75,
        "envelope_peak_snr_db": 2.0,
        "residual_kurtosis": 0.25,
        "residual_crest_factor": 0.5,
    }


@dataclass
class ExperimentConfig:
    """All tunable parameters for one experiment.

    Grouped by stage: synthesis, features, detector, decision. Field names are stable
    and appear verbatim in exported YAML/JSON, run logs and the CLI.
    """

    # --- synthesis -----------------------------------------------------------------
    profile: str = "Robotic Arm Bearings"
    sample_rate_hz: int = 48_000
    duration_s: float = 2.0
    seed: int = 42
    carrier_amplitude: float = 0.20
    harmonic_amplitude: float = 0.08
    noise_std: float = 0.018
    inject_bursts: bool = False
    burst_amplitude: float = 0.42
    burst_frequency_hz: float = 22_000.0
    burst_period_s: float = 0.37
    burst_first_s: float = 0.25
    burst_length_s: float = 0.012
    burst_decay: float = 260.0
    inject_bearing_impacts: bool = False
    shaft_hz: float = 29.95
    bpfo_ratio: float = 3.585
    resonance_hz: float = 5_200.0
    impact_amplitude: float = 0.35

    # --- features ------------------------------------------------------------------
    band_low_hz: float = 20_000.0
    band_high_hz: float = 24_000.0
    reference_band_low_hz: float = 14_000.0
    reference_band_high_hz: float = 18_000.0
    highpass_hz: float = 2_000.0
    welch_nperseg: int = 4_096
    envelope_min_hz: float = 5.0
    envelope_max_hz: float = 500.0

    # --- detector ------------------------------------------------------------------
    baseline_seeds: int = 8
    weights: dict[str, float] = field(default_factory=default_weights)
    std_floors: dict[str, float] = field(default_factory=default_std_floors)
    z_center: float = 3.0
    z_scale: float = 1.0
    demo_boost: float = 0.0

    # --- validity / decision -------------------------------------------------------
    min_duration_s: float = 0.5
    silence_rms: float = 2e-3
    clipping_fraction: float = 1e-3
    warn_threshold: float = 40.0
    critical_threshold: float = 75.0
    min_confidence: float = 0.6

    # ------------------------------------------------------------------------------
    def machine(self) -> MachineProfile:
        return MACHINE_PROFILES[self.profile]

    def nyquist_hz(self) -> float:
        return self.sample_rate_hz / 2.0

    def with_updates(self, **changes: Any) -> ExperimentConfig:
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentConfig:
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"Unknown configuration keys: {', '.join(unknown)}")
        cfg = cls(**data)
        cfg.validate()
        return cfg

    @classmethod
    def from_text(cls, text: str) -> ExperimentConfig:
        """Parse JSON or YAML (YAML is a superset, so one loader covers both)."""
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ValueError("Configuration must be a mapping of parameter names to values")
        return cls.from_dict(data)

    @classmethod
    def load(cls, path: str | Path) -> ExperimentConfig:
        return cls.from_text(Path(path).read_text(encoding="utf-8"))

    def save(self, path: str | Path) -> None:
        path = Path(path)
        text = self.to_json() if path.suffix.lower() == ".json" else self.to_yaml()
        path.write_text(text, encoding="utf-8")

    def validate(self) -> None:
        if self.profile not in MACHINE_PROFILES:
            raise ValueError(f"Unknown profile {self.profile!r}; choose from {list(MACHINE_PROFILES)}")
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        if self.duration_s <= 0:
            raise ValueError("duration_s must be positive")
        if not 0 <= self.band_low_hz < self.band_high_hz:
            raise ValueError("band_low_hz must be >= 0 and < band_high_hz")
        if not 0 <= self.reference_band_low_hz < self.reference_band_high_hz:
            raise ValueError("reference band must satisfy low < high")
        if not 0 < self.envelope_min_hz < self.envelope_max_hz:
            raise ValueError("envelope band must satisfy 0 < min < max")
        if self.z_scale <= 0:
            raise ValueError("z_scale must be positive")
        if not 0 <= self.warn_threshold < self.critical_threshold <= 100:
            raise ValueError("thresholds must satisfy 0 <= warn < critical <= 100")
        if not 0 <= self.min_confidence <= 1:
            raise ValueError("min_confidence must be within [0, 1]")
        if self.baseline_seeds < 2:
            raise ValueError("baseline_seeds must be at least 2")
        missing = set(default_weights()) - set(self.weights)
        if missing:
            raise ValueError(f"weights missing channels: {sorted(missing)}")
        if any(w < 0 for w in self.weights.values()):
            raise ValueError("weights must be non-negative")
        if any(s <= 0 for s in self.std_floors.values()):
            raise ValueError("std_floors must be positive")


def config_hash(config: ExperimentConfig, length: int = 12) -> str:
    """Short SHA-256 of the canonical JSON form; stable across processes."""
    digest = hashlib.sha256(config.to_json(indent=None).encode("utf-8")).hexdigest()
    return digest[:length]


def sweepable_parameters() -> dict[str, str]:
    """Numeric synthesis/detector parameters a sweep may vary, with a short description."""
    return {
        "burst_amplitude": "Amplitude of injected 22 kHz bursts",
        "noise_std": "Standard deviation of the broadband noise",
        "burst_frequency_hz": "Carrier frequency of the injected bursts",
        "impact_amplitude": "Amplitude of bearing outer-race impacts",
        "duration_s": "Capture length in seconds",
        "z_center": "z-score that maps to a 50 % anomaly score",
    }
