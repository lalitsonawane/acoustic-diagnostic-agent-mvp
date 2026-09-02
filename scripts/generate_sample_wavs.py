"""Generate a small, labelled, deterministic set of synthetic WAV files for testing.

The set mirrors the signal model used by ``app.py`` (base tone + third harmonic +
white noise + optional damped 22 kHz bursts) and adds edge cases the app must
handle gracefully, plus two physically motivated bearing-impact recordings.

Usage:
    python scripts/generate_sample_wavs.py [--out data/samples] [--duration 2.0]

Every file is regenerated from a fixed per-file seed, so the output is
byte-for-byte reproducible. A ``manifest.csv`` describing each file is written
alongside the audio.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

MACHINE_PROFILES: dict[str, float] = {
    "robotic_arm": 440.0,
    "stamping_press": 220.0,
    "conveyor_drive": 330.0,
}

# Amplitudes below follow app.generate_acoustic_data so the files are directly
# comparable with the in-app simulator.
CARRIER_AMP = 0.20
HARMONIC_AMP = 0.08
DEFAULT_NOISE_STD = 0.018
DEFAULT_BURST_AMP = 0.42
BURST_FREQ_HZ = 22_000.0
BURST_PERIOD_S = 0.37
BURST_FIRST_S = 0.25
BURST_LEN_S = 0.012
BURST_DECAY = 260.0


@dataclass
class Spec:
    file: str
    machine_profile: str
    condition: str  # healthy | fault | edge_case
    fault_type: str
    sample_rate_hz: int
    channels: int
    seed: int
    burst_amplitude: float
    noise_std: float
    purpose: str
    duration_s: float = 0.0
    gain: float = 1.0
    extra: dict = field(default_factory=dict)


def tonal_base(profile_hz: float, t: np.ndarray, rng: np.random.Generator, noise_std: float) -> np.ndarray:
    carrier = CARRIER_AMP * np.sin(2 * np.pi * profile_hz * t)
    harmonic = HARMONIC_AMP * np.sin(2 * np.pi * 3 * profile_hz * t)
    return carrier + harmonic + rng.normal(0.0, noise_std, t.shape)


def add_ultrasonic_bursts(signal: np.ndarray, sr: int, amplitude: float) -> None:
    """In-place: short damped 22 kHz bursts, identical timing to the app simulator."""
    duration = signal.size / sr
    for start in np.arange(BURST_FIRST_S, duration, BURST_PERIOD_S):
        index = int(start * sr)
        n = min(int(BURST_LEN_S * sr), signal.size - index)
        if n <= 0:
            continue
        bt = np.arange(n) / sr
        signal[index : index + n] += amplitude * np.exp(-bt * BURST_DECAY) * np.sin(2 * np.pi * BURST_FREQ_HZ * bt)


def add_bearing_impacts(
    signal: np.ndarray,
    sr: int,
    shaft_hz: float,
    bpfo_ratio: float,
    resonance_hz: float,
    amplitude: float,
    rng: np.random.Generator,
) -> dict:
    """In-place: periodic impacts at the outer-race defect frequency exciting a structural resonance.

    This is closer to a real bearing fault than a 22 kHz tone: the diagnostic
    information lives in the *envelope* (repetition rate = BPFO) and in a mid/high
    frequency resonance band, not in a single ultrasonic carrier.
    """
    bpfo_hz = shaft_hz * bpfo_ratio
    period = 1.0 / bpfo_hz
    duration = signal.size / sr
    # 1-2 % random jitter approximates rolling-element slip.
    starts = np.cumsum(rng.normal(period, 0.015 * period, int(duration / period) + 2))
    ring_len = int(0.004 * sr)
    for start in starts[starts < duration]:
        index = int(start * sr)
        n = min(ring_len, signal.size - index)
        if n <= 0:
            continue
        bt = np.arange(n) / sr
        ring = np.exp(-bt * 1500.0) * np.sin(2 * np.pi * resonance_hz * bt)
        signal[index : index + n] += amplitude * rng.uniform(0.8, 1.2) * ring
    return {"shaft_hz": shaft_hz, "bpfo_hz": round(bpfo_hz, 2), "resonance_hz": resonance_hz}


def render(spec: Spec, duration: float) -> tuple[np.ndarray, Spec]:
    sr = spec.sample_rate_hz
    rng = np.random.default_rng(spec.seed)
    t = np.linspace(0.0, duration, int(sr * duration), endpoint=False)
    base_hz = MACHINE_PROFILES.get(spec.machine_profile, 440.0)

    if spec.fault_type == "silence":
        signal = rng.normal(0.0, 0.0005, t.shape)
    else:
        signal = tonal_base(base_hz, t, rng, spec.noise_std)

    if spec.fault_type in {"ultrasonic_bursts"}:
        add_ultrasonic_bursts(signal, sr, spec.burst_amplitude)
    elif spec.fault_type == "bearing_outer_race_impacts":
        spec.extra.update(
            add_bearing_impacts(
                signal,
                sr,
                shaft_hz=29.95,  # ~1797 rpm, a common induction-motor speed
                bpfo_ratio=3.585,  # typical for a 9-ball deep-groove bearing
                resonance_hz=5_200.0,
                amplitude=spec.burst_amplitude,
                rng=rng,
            )
        )

    signal = signal * spec.gain
    signal = np.clip(signal, -1.0, 1.0).astype(np.float32)
    if spec.channels == 2:
        # Slightly different noise per channel so the file is genuinely stereo.
        right = signal + rng.normal(0.0, spec.noise_std * 0.5, signal.shape).astype(np.float32)
        signal = np.stack([signal, np.clip(right, -1.0, 1.0)], axis=1)
    spec.duration_s = duration
    return signal, spec


def build_specs(duration: float) -> list[Spec]:
    specs: list[Spec] = []
    seed = 1000
    for profile in MACHINE_PROFILES:
        seed += 1
        specs.append(
            Spec(
                file=f"{profile}_healthy_48k.wav",
                machine_profile=profile,
                condition="healthy",
                fault_type="none",
                sample_rate_hz=48_000,
                channels=1,
                seed=seed,
                burst_amplitude=0.0,
                noise_std=DEFAULT_NOISE_STD,
                purpose="Baseline healthy signal; expected HEALTHY / low score.",
            )
        )
        seed += 1
        specs.append(
            Spec(
                file=f"{profile}_fault_48k.wav",
                machine_profile=profile,
                condition="fault",
                fault_type="ultrasonic_bursts",
                sample_rate_hz=48_000,
                channels=1,
                seed=seed,
                burst_amplitude=DEFAULT_BURST_AMP,
                noise_std=DEFAULT_NOISE_STD,
                purpose="Injected 22 kHz micro-crack bursts, same parameters as the in-app toggle.",
            )
        )

    edge = [
        Spec(
            file="robotic_arm_fault_weak_48k.wav",
            machine_profile="robotic_arm",
            condition="fault",
            fault_type="ultrasonic_bursts",
            sample_rate_hz=48_000,
            channels=1,
            seed=2001,
            burst_amplitude=0.10,
            noise_std=DEFAULT_NOISE_STD,
            purpose="Weak bursts near the detection floor; useful for threshold and ROC studies.",
        ),
        Spec(
            file="robotic_arm_fault_noisy_48k.wav",
            machine_profile="robotic_arm",
            condition="fault",
            fault_type="ultrasonic_bursts",
            sample_rate_hz=48_000,
            channels=1,
            seed=2002,
            burst_amplitude=DEFAULT_BURST_AMP,
            noise_std=0.12,
            purpose="Full-strength bursts under heavy broadband noise (low SNR).",
        ),
        Spec(
            file="robotic_arm_healthy_noisy_48k.wav",
            machine_profile="robotic_arm",
            condition="healthy",
            fault_type="none",
            sample_rate_hz=48_000,
            channels=1,
            seed=2003,
            burst_amplitude=0.0,
            noise_std=0.12,
            purpose="Healthy but noisy; a naive high-band energy detector will false-alarm on this.",
        ),
        Spec(
            file="robotic_arm_fault_stereo_48k.wav",
            machine_profile="robotic_arm",
            condition="fault",
            fault_type="ultrasonic_bursts",
            sample_rate_hz=48_000,
            channels=2,
            seed=2004,
            burst_amplitude=DEFAULT_BURST_AMP,
            noise_std=DEFAULT_NOISE_STD,
            purpose="Stereo file; verifies mono down-mix on upload.",
        ),
        Spec(
            file="robotic_arm_fault_clipped_48k.wav",
            machine_profile="robotic_arm",
            condition="edge_case",
            fault_type="ultrasonic_bursts",
            sample_rate_hz=48_000,
            channels=1,
            seed=2005,
            burst_amplitude=DEFAULT_BURST_AMP,
            noise_std=DEFAULT_NOISE_STD,
            gain=6.0,
            purpose="Heavily clipped input; a validity check should flag this and lower confidence.",
        ),
        Spec(
            file="robotic_arm_fault_16k.wav",
            machine_profile="robotic_arm",
            condition="edge_case",
            fault_type="ultrasonic_bursts",
            sample_rate_hz=16_000,
            channels=1,
            seed=2006,
            burst_amplitude=DEFAULT_BURST_AMP,
            noise_std=DEFAULT_NOISE_STD,
            purpose="16 kHz sample rate: Nyquist is 8 kHz, so the 22 kHz fault aliases and the >20 kHz band is empty. The app must warn instead of reporting a confident score.",
        ),
        Spec(
            file="silence_48k.wav",
            machine_profile="none",
            condition="edge_case",
            fault_type="silence",
            sample_rate_hz=48_000,
            channels=1,
            seed=2007,
            burst_amplitude=0.0,
            noise_std=0.0005,
            purpose="Near-silent capture (sensor disconnected); should be rejected as invalid input.",
        ),
        Spec(
            file="bearing_outer_race_healthy_48k.wav",
            machine_profile="robotic_arm",
            condition="healthy",
            fault_type="none",
            sample_rate_hz=48_000,
            channels=1,
            seed=3001,
            burst_amplitude=0.0,
            noise_std=0.03,
            purpose="Healthy counterpart for the bearing-impact file (same noise level).",
        ),
        Spec(
            file="bearing_outer_race_fault_48k.wav",
            machine_profile="robotic_arm",
            condition="fault",
            fault_type="bearing_outer_race_impacts",
            sample_rate_hz=48_000,
            channels=1,
            seed=3002,
            burst_amplitude=0.35,
            noise_std=0.03,
            purpose="Physically motivated outer-race defect: impacts at BPFO (~107 Hz) ringing a 5.2 kHz resonance. Invisible to a >20 kHz detector; visible to envelope/kurtosis analysis.",
        ),
    ]
    specs.extend(edge)
    return specs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("data/samples"))
    parser.add_argument("--duration", type=float, default=2.0, help="Seconds of audio per file")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for spec in build_specs(args.duration):
        audio, spec = render(spec, args.duration)
        path = args.out / spec.file
        sf.write(path, audio, spec.sample_rate_hz, subtype="PCM_16")
        row = asdict(spec)
        row["extra"] = ";".join(f"{k}={v}" for k, v in spec.extra.items())
        row["size_bytes"] = path.stat().st_size
        rows.append(row)
        print(f"wrote {path} ({row['size_bytes'] / 1024:.0f} KB)")

    manifest = args.out / "manifest.csv"
    with manifest.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {manifest} ({len(rows)} files)")


if __name__ == "__main__":
    main()
