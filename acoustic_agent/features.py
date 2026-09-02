"""Signal features used by the detector.

All features are *normalised* so that they do not depend on absolute gain or recording
length, which is what made the original mean-FFT-magnitude score incomparable across
files. Each helper is pure and independently testable.

Channels
--------
band_power_db
    Welch band power in the diagnostic band relative to total power (dB). Rises with any
    energy above ``band_low_hz`` - including broadband noise.
band_contrast_db
    Diagnostic band power relative to an adjacent reference band (dB). Roughly 0 dB for
    white noise of any level, so it isolates *narrow-band* ultrasonic content and is
    robust to noisy recordings.
band_contrast_transient_db
    Time-resolved version of the above: band contrast is computed per STFT frame and the
    98th percentile minus the median is reported. Short bursts that Welch averaging dilutes
    (a few ms of energy in a 2 s capture under heavy noise) stand out here, while
    stationary noise of any level gives ~1-2 dB.
residual_kurtosis / residual_crest_factor
    Impulsiveness of the high-passed residual (tonal carrier removed). Gaussian noise has
    kurtosis 3; repetitive impacts push it well above.
envelope_peak_hz / envelope_peak_snr_db
    Dominant repetition rate of the residual's Hilbert envelope and how far it stands
    above the envelope-spectrum floor. Bearing defects show up here (BPFO/BPFI/BSF).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy import signal as sps
from scipy import stats

from acoustic_agent.config import ExperimentConfig

EPS = 1e-12


@dataclass(frozen=True)
class Spectrum:
    frequencies_hz: np.ndarray
    psd: np.ndarray  # power spectral density, V**2/Hz

    def band_power(self, low_hz: float, high_hz: float) -> float:
        mask = (self.frequencies_hz >= low_hz) & (self.frequencies_hz < high_hz)
        if not np.any(mask):
            return 0.0
        return float(np.trapezoid(self.psd[mask], self.frequencies_hz[mask]))

    def total_power(self) -> float:
        return float(np.trapezoid(self.psd, self.frequencies_hz))


@dataclass(frozen=True)
class FeatureSet:
    """Scalar features of one signal. ``nan`` marks a channel that could not be computed."""

    rms: float
    peak: float
    clipping_fraction: float
    duration_s: float
    sample_rate_hz: int
    band_power_db: float
    band_contrast_db: float
    band_contrast_transient_db: float
    residual_kurtosis: float
    residual_crest_factor: float
    envelope_peak_hz: float
    envelope_peak_snr_db: float
    band_available: bool
    reference_band_available: bool

    def as_dict(self) -> dict[str, float | int | bool]:
        return asdict(self)

    def channels(self) -> dict[str, float]:
        """The scored evidence channels only."""
        return {
            "band_power_db": self.band_power_db,
            "band_contrast_db": self.band_contrast_db,
            "band_contrast_transient_db": self.band_contrast_transient_db,
            "residual_kurtosis": self.residual_kurtosis,
            "residual_crest_factor": self.residual_crest_factor,
            "envelope_peak_snr_db": self.envelope_peak_snr_db,
        }


def to_mono_float(audio: np.ndarray) -> np.ndarray:
    x = np.asarray(audio)
    if x.ndim == 2:
        x = x.mean(axis=1)
    return np.ascontiguousarray(x, dtype=np.float64)


def welch_psd(audio: np.ndarray, sample_rate_hz: int, nperseg: int = 4096) -> Spectrum:
    x = to_mono_float(audio)
    n = int(min(nperseg, x.size))
    if n < 16:
        return Spectrum(np.array([0.0]), np.array([0.0]))
    f, p = sps.welch(x, fs=sample_rate_hz, nperseg=n, noverlap=n // 2, detrend="constant", scaling="density")
    return Spectrum(f, p)


def band_power_db(spectrum: Spectrum, low_hz: float, high_hz: float) -> float:
    """Band power relative to total power in dB (always <= 0)."""
    total = spectrum.total_power()
    band = spectrum.band_power(low_hz, high_hz)
    return float(10.0 * np.log10((band + EPS) / (total + EPS)))


def band_contrast_db(spectrum: Spectrum, band: tuple[float, float], reference: tuple[float, float]) -> float:
    """Band power relative to a reference band of equal-ish width, in dB."""
    b = spectrum.band_power(*band) / max(band[1] - band[0], EPS)
    r = spectrum.band_power(*reference) / max(reference[1] - reference[0], EPS)
    return float(10.0 * np.log10((b + EPS) / (r + EPS)))


def band_contrast_transient_db(
    audio: np.ndarray,
    sample_rate_hz: int,
    band: tuple[float, float],
    reference: tuple[float, float],
    nperseg: int = 1024,
    percentile: float = 98.0,
) -> float:
    """Spread of the per-frame band contrast: high percentile minus median, in dB.

    Frames of ~20 ms resolve bursts that a whole-capture Welch estimate averages away.
    Stationary noise gives a small spread regardless of its level; short ultrasonic
    bursts give a large one.
    """
    x = to_mono_float(audio)
    nperseg = int(min(nperseg, max(64, x.size // 4)))
    if x.size < 4 * nperseg:
        return float("nan")
    freqs, _, sxx = sps.spectrogram(x, fs=sample_rate_hz, nperseg=nperseg, noverlap=nperseg // 2, scaling="density")
    b = (freqs >= band[0]) & (freqs < band[1])
    r = (freqs >= reference[0]) & (freqs < reference[1])
    if not np.any(b) or not np.any(r) or sxx.shape[1] < 8:
        return float("nan")
    contrast = 10.0 * np.log10((sxx[b].mean(axis=0) + EPS) / (sxx[r].mean(axis=0) + EPS))
    return float(np.percentile(contrast, percentile) - np.median(contrast))


def highpass(audio: np.ndarray, sample_rate_hz: int, cutoff_hz: float, order: int = 4) -> np.ndarray:
    """Zero-phase Butterworth high-pass; falls back to the input if the cutoff is invalid."""
    x = to_mono_float(audio)
    nyq = sample_rate_hz / 2.0
    if cutoff_hz <= 0 or cutoff_hz >= 0.95 * nyq or x.size < 3 * (order + 1) * 3:
        return x - x.mean()
    sos = sps.butter(order, cutoff_hz / nyq, btype="highpass", output="sos")
    return np.asarray(sps.sosfiltfilt(sos, x), dtype=np.float64)


def kurtosis(x: np.ndarray) -> float:
    x = to_mono_float(x)
    if x.size < 8 or np.allclose(x, x[0]):
        return float("nan")
    return float(stats.kurtosis(x, fisher=False, bias=False))


def crest_factor(x: np.ndarray) -> float:
    x = to_mono_float(x)
    rms = float(np.sqrt(np.mean(x**2))) if x.size else 0.0
    if rms < EPS:
        return float("nan")
    return float(np.max(np.abs(x)) / rms)


def envelope_spectrum(residual: np.ndarray, sample_rate_hz: int) -> Spectrum:
    """Amplitude spectrum of the Hilbert envelope (DC removed)."""
    x = to_mono_float(residual)
    if x.size < 16:
        return Spectrum(np.array([0.0]), np.array([0.0]))
    env = np.abs(sps.hilbert(x))
    env = env - env.mean()
    window = np.hanning(env.size)
    spec = np.abs(np.fft.rfft(env * window)) / max(np.sum(window), EPS)
    freqs = np.fft.rfftfreq(env.size, 1.0 / sample_rate_hz)
    return Spectrum(freqs, spec)


def envelope_peak(spectrum: Spectrum, min_hz: float, max_hz: float) -> tuple[float, float]:
    """Dominant envelope frequency and its prominence over the median floor in dB."""
    mask = (spectrum.frequencies_hz >= min_hz) & (spectrum.frequencies_hz <= max_hz)
    if np.count_nonzero(mask) < 4:
        return float("nan"), float("nan")
    band = spectrum.psd[mask]
    freqs = spectrum.frequencies_hz[mask]
    floor = float(np.median(band))
    idx = int(np.argmax(band))
    snr_db = float(20.0 * np.log10((band[idx] + EPS) / (floor + EPS)))
    return float(freqs[idx]), snr_db


def detect_impulses(residual: np.ndarray, sample_rate_hz: int, k: float = 6.0, min_gap_s: float = 0.005) -> np.ndarray:
    """Sample indices where the residual envelope exceeds median + k * MAD."""
    x = to_mono_float(residual)
    if x.size < 16:
        return np.array([], dtype=int)
    env = np.abs(sps.hilbert(x))
    med = float(np.median(env))
    mad = float(np.median(np.abs(env - med))) + EPS
    threshold = med + k * 1.4826 * mad
    distance = max(1, int(min_gap_s * sample_rate_hz))
    peaks, _ = sps.find_peaks(env, height=threshold, distance=distance)
    return np.asarray(peaks, dtype=int)


def extract_features(audio: np.ndarray, sample_rate_hz: int, config: ExperimentConfig) -> FeatureSet:
    """Compute the full :class:`FeatureSet` for a mono signal."""
    x = to_mono_float(audio)
    duration = x.size / sample_rate_hz if sample_rate_hz > 0 else 0.0
    rms = float(np.sqrt(np.mean(x**2))) if x.size else 0.0
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    clipping = float(np.mean(np.abs(x) >= 0.999)) if x.size else 0.0

    nyq = sample_rate_hz / 2.0
    band_available = config.band_low_hz < nyq
    ref_available = config.reference_band_low_hz < nyq
    band_high = min(config.band_high_hz, nyq)
    ref_high = min(config.reference_band_high_hz, nyq)

    spectrum = welch_psd(x, sample_rate_hz, config.welch_nperseg)
    bp = band_power_db(spectrum, config.band_low_hz, band_high) if band_available else float("nan")
    contrast = (
        band_contrast_db(spectrum, (config.band_low_hz, band_high), (config.reference_band_low_hz, ref_high))
        if band_available and ref_available
        else float("nan")
    )
    transient = (
        band_contrast_transient_db(x, sample_rate_hz, (config.band_low_hz, band_high), (config.reference_band_low_hz, ref_high))
        if band_available and ref_available
        else float("nan")
    )

    residual = highpass(x, sample_rate_hz, config.highpass_hz)
    env_spec = envelope_spectrum(residual, sample_rate_hz)
    env_hz, env_snr = envelope_peak(env_spec, config.envelope_min_hz, config.envelope_max_hz)

    return FeatureSet(
        rms=rms,
        peak=peak,
        clipping_fraction=clipping,
        duration_s=float(duration),
        sample_rate_hz=int(sample_rate_hz),
        band_power_db=bp,
        band_contrast_db=contrast,
        band_contrast_transient_db=transient,
        residual_kurtosis=kurtosis(residual),
        residual_crest_factor=crest_factor(residual),
        envelope_peak_hz=env_hz,
        envelope_peak_snr_db=env_snr,
        band_available=bool(band_available),
        reference_band_available=bool(ref_available),
    )
