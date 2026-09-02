"""Deterministic synthetic acoustic signals.

The signal model is a rotating-machine tone (carrier + third harmonic) in white noise,
optionally with two kinds of fault signature:

* damped ultrasonic bursts (a stylised micro-crack "click" at ~22 kHz);
* periodic outer-race bearing impacts that ring a mid-frequency structural resonance.

All randomness comes from a caller-supplied seed so any run can be reproduced exactly.
``scripts/generate_sample_wavs.py`` uses these same primitives to build the committed
test set, so files in ``data/samples`` are directly comparable with in-app simulations.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from acoustic_agent.config import ExperimentConfig

# Defaults mirrored by the sample-set generator.
CARRIER_AMP = 0.20
HARMONIC_AMP = 0.08
DEFAULT_NOISE_STD = 0.018
DEFAULT_BURST_AMP = 0.42
BURST_FREQ_HZ = 22_000.0
BURST_PERIOD_S = 0.37
BURST_FIRST_S = 0.25
BURST_LEN_S = 0.012
BURST_DECAY = 260.0


@dataclass(frozen=True)
class Signal:
    """A mono float32 signal with its sample rate and provenance."""

    audio: np.ndarray
    sample_rate_hz: int
    source: str

    @property
    def duration_s(self) -> float:
        return float(self.audio.size / self.sample_rate_hz)


def time_axis(sample_rate_hz: int, duration_s: float) -> np.ndarray:
    return np.linspace(0.0, duration_s, int(sample_rate_hz * duration_s), endpoint=False)


def tonal_base(
    base_frequency_hz: float,
    t: np.ndarray,
    rng: np.random.Generator,
    noise_std: float,
    carrier_amp: float = CARRIER_AMP,
    harmonic_amp: float = HARMONIC_AMP,
) -> np.ndarray:
    carrier = carrier_amp * np.sin(2 * np.pi * base_frequency_hz * t)
    harmonic = harmonic_amp * np.sin(2 * np.pi * 3 * base_frequency_hz * t)
    return carrier + harmonic + rng.normal(0.0, noise_std, t.shape)


def add_ultrasonic_bursts(
    signal: np.ndarray,
    sample_rate_hz: int,
    amplitude: float,
    frequency_hz: float = BURST_FREQ_HZ,
    period_s: float = BURST_PERIOD_S,
    first_s: float = BURST_FIRST_S,
    length_s: float = BURST_LEN_S,
    decay: float = BURST_DECAY,
) -> list[float]:
    """In place: short damped bursts at fixed spacing. Returns the burst onset times."""
    duration = signal.size / sample_rate_hz
    onsets: list[float] = []
    for start in np.arange(first_s, duration, period_s):
        index = int(start * sample_rate_hz)
        n = min(int(length_s * sample_rate_hz), signal.size - index)
        if n <= 0:
            continue
        bt = np.arange(n) / sample_rate_hz
        signal[index : index + n] += amplitude * np.exp(-bt * decay) * np.sin(2 * np.pi * frequency_hz * bt)
        onsets.append(float(start))
    return onsets


def add_bearing_impacts(
    signal: np.ndarray,
    sample_rate_hz: int,
    shaft_hz: float,
    bpfo_ratio: float,
    resonance_hz: float,
    amplitude: float,
    rng: np.random.Generator,
) -> dict[str, float]:
    """In place: impacts at the ball-pass frequency of the outer race exciting a resonance.

    The diagnostic information lives in the *envelope* (repetition rate = BPFO) and in a
    mid/high-frequency resonance band rather than in a single ultrasonic carrier, which is
    much closer to what a real bearing defect sounds like.
    """
    bpfo_hz = shaft_hz * bpfo_ratio
    period = 1.0 / bpfo_hz
    duration = signal.size / sample_rate_hz
    # 1-2 % random jitter approximates rolling-element slip.
    starts = np.cumsum(rng.normal(period, 0.015 * period, int(duration / period) + 2))
    ring_len = int(0.004 * sample_rate_hz)
    for start in starts[starts < duration]:
        index = int(start * sample_rate_hz)
        n = min(ring_len, signal.size - index)
        if n <= 0:
            continue
        bt = np.arange(n) / sample_rate_hz
        ring = np.exp(-bt * 1500.0) * np.sin(2 * np.pi * resonance_hz * bt)
        signal[index : index + n] += amplitude * rng.uniform(0.8, 1.2) * ring
    return {"shaft_hz": shaft_hz, "bpfo_hz": round(bpfo_hz, 2), "resonance_hz": resonance_hz}


def synthesize(
    config: ExperimentConfig,
    *,
    seed: int | None = None,
    inject_bursts: bool | None = None,
    inject_bearing_impacts: bool | None = None,
) -> Signal:
    """Render one signal from ``config``; keyword overrides support baselines and sweeps."""
    seed = config.seed if seed is None else seed
    bursts = config.inject_bursts if inject_bursts is None else inject_bursts
    impacts = config.inject_bearing_impacts if inject_bearing_impacts is None else inject_bearing_impacts

    profile = config.machine()
    rng = np.random.default_rng(seed)
    t = time_axis(config.sample_rate_hz, config.duration_s)
    signal = tonal_base(
        profile.base_frequency_hz,
        t,
        rng,
        config.noise_std,
        carrier_amp=config.carrier_amplitude,
        harmonic_amp=config.harmonic_amplitude,
    )
    tags: list[str] = []
    if bursts:
        add_ultrasonic_bursts(
            signal,
            config.sample_rate_hz,
            config.burst_amplitude,
            frequency_hz=config.burst_frequency_hz,
            period_s=config.burst_period_s,
            first_s=config.burst_first_s,
            length_s=config.burst_length_s,
            decay=config.burst_decay,
        )
        tags.append("bursts")
    if impacts:
        add_bearing_impacts(
            signal,
            config.sample_rate_hz,
            shaft_hz=config.shaft_hz,
            bpfo_ratio=config.bpfo_ratio,
            resonance_hz=config.resonance_hz,
            amplitude=config.impact_amplitude,
            rng=rng,
        )
        tags.append("bearing-impacts")
    audio = np.clip(signal, -1.0, 1.0).astype(np.float32)
    label = f"synthetic:{profile.key}:seed={seed}" + (f":{'+'.join(tags)}" if tags else ":healthy")
    return Signal(audio=audio, sample_rate_hz=config.sample_rate_hz, source=label)


def healthy_reference(config: ExperimentConfig, seed: int) -> Signal:
    """A healthy render of the configured profile used for baseline calibration."""
    return synthesize(config, seed=seed, inject_bursts=False, inject_bearing_impacts=False)
