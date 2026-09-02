"""Input validity checks that gate how much the verdict can be trusted.

Each check either invalidates the input outright (silence, too short) or reduces a
multiplicative confidence factor and records a human-readable warning. Confidence is a
heuristic in [0, 1]; it is *not* a probability.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from acoustic_agent.config import ExperimentConfig
from acoustic_agent.features import FeatureSet


@dataclass
class Validity:
    valid: bool = True
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def penalise(self, factor: float, flag: str, message: str) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence * factor))
        self.flags.append(flag)
        self.warnings.append(message)

    def invalidate(self, flag: str, message: str) -> None:
        self.valid = False
        self.confidence = 0.0
        self.flags.append(flag)
        self.warnings.append(message)


def assess_validity(features: FeatureSet, config: ExperimentConfig) -> Validity:
    v = Validity()

    if features.duration_s < 0.05 or features.sample_rate_hz <= 0:
        v.invalidate("empty", "Signal is empty or has no sample rate.")
        return v

    if features.rms < config.silence_rms:
        v.invalidate(
            "silence",
            f"Signal RMS {features.rms:.2e} is below the silence floor {config.silence_rms:.0e}: "
            "sensor may be disconnected or muted. No verdict issued.",
        )
        return v

    if features.duration_s < config.min_duration_s:
        v.penalise(
            0.5,
            "short",
            f"Capture is {features.duration_s:.2f} s; at least {config.min_duration_s:.1f} s is needed for stable spectral estimates.",
        )

    if not features.band_available:
        v.penalise(
            0.4,
            "band_unavailable",
            f"Sample rate {features.sample_rate_hz / 1000:.1f} kHz gives a Nyquist limit of "
            f"{features.sample_rate_hz / 2000:.1f} kHz, below the {config.band_low_hz / 1000:.0f}-"
            f"{config.band_high_hz / 1000:.0f} kHz diagnostic band. Ultrasonic evidence is unavailable "
            "and any high-frequency content is aliased.",
        )
    elif not features.reference_band_available:
        v.penalise(
            0.7,
            "reference_band_unavailable",
            "Reference band lies above Nyquist; band contrast could not be computed.",
        )

    if features.clipping_fraction > config.clipping_fraction:
        v.penalise(
            0.6,
            "clipping",
            f"{features.clipping_fraction * 100:.2f} % of samples are at full scale: the recording is "
            "clipped, which creates artificial harmonics and impulsiveness.",
        )

    return v
