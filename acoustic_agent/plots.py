"""Matplotlib figures rendered to PNG bytes.

Returning bytes (rather than figure objects) keeps the functions cacheable with
``st.cache_data`` and makes PNG export trivial. Colours come from a small
:class:`PlotTheme` so the app can pass the active Streamlit theme.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from scipy import signal as sps

from acoustic_agent.config import ExperimentConfig
from acoustic_agent.detect import Baseline
from acoustic_agent.features import Spectrum, detect_impulses, envelope_spectrum, highpass, welch_psd
from acoustic_agent.synth import Signal


@dataclass(frozen=True)
class PlotTheme:
    background: str = "#0f1719"
    panel: str = "#141f22"
    text: str = "#e6eef0"
    muted: str = "#8aa0a4"
    grid: str = "#27383c"
    primary: str = "#4fd1b9"
    secondary: str = "#ffb454"
    danger: str = "#ff6b6b"
    cmap: str = "magma"

    @classmethod
    def light(cls) -> PlotTheme:
        return cls(
            background="#ffffff",
            panel="#f6f8f8",
            text="#1f2a2c",
            muted="#5c6f73",
            grid="#d7dfe1",
            primary="#0f8f78",
            secondary="#c76b00",
            danger="#c62828",
            cmap="viridis",
        )


def _figure(theme: PlotTheme, size: tuple[float, float]) -> tuple[Figure, Axes]:
    fig, ax = plt.subplots(figsize=size, facecolor=theme.background)
    ax.set_facecolor(theme.panel)
    ax.tick_params(colors=theme.muted, labelsize=8)
    ax.xaxis.label.set_color(theme.muted)
    ax.yaxis.label.set_color(theme.muted)
    ax.title.set_color(theme.text)
    for spine in ax.spines.values():
        spine.set_color(theme.grid)
    ax.grid(True, color=theme.grid, linewidth=0.5, alpha=0.6)
    return fig, ax


def _to_png(fig: Figure, dpi: int = 130) -> bytes:
    buffer = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buffer, format="png", dpi=dpi, facecolor=fig.get_facecolor())
    plt.close(fig)
    return buffer.getvalue()


def _shade_band(ax: Axes, low: float, high: float, color: str, label: str) -> None:
    ax.axvspan(low, high, color=color, alpha=0.12, lw=0)
    ax.axvline(low, color=color, lw=0.8, ls="--", alpha=0.8)
    ax.text(
        low,
        1.01,
        label,
        color=color,
        fontsize=7,
        transform=ax.get_xaxis_transform(),
        ha="left",
        va="bottom",
    )


def spectrogram_png(signal: Signal, config: ExperimentConfig, theme: PlotTheme = PlotTheme()) -> bytes:
    """Linear-frequency STFT spectrogram in dB with the diagnostic band shaded."""
    x = signal.audio.astype(np.float64)
    nperseg = int(min(2048, max(256, x.size // 8)))
    f, t, sxx = sps.spectrogram(x, fs=signal.sample_rate_hz, nperseg=nperseg, noverlap=nperseg // 2, scaling="density")
    db = 10.0 * np.log10(sxx + 1e-14)
    vmax = float(np.max(db))
    fig, ax = _figure(theme, (11, 4.2))
    mesh = ax.pcolormesh(t, f / 1000.0, db, shading="auto", cmap=theme.cmap, vmin=vmax - 90, vmax=vmax)
    nyq_khz = signal.sample_rate_hz / 2000.0
    if config.band_low_hz / 1000.0 < nyq_khz:
        ax.axhspan(
            config.band_low_hz / 1000.0, min(config.band_high_hz, signal.sample_rate_hz / 2) / 1000.0, color=theme.primary, alpha=0.15, lw=0
        )
        ax.axhline(config.band_low_hz / 1000.0, color=theme.primary, lw=0.8, ls="--")
        ax.text(
            t[-1] if t.size else 0,
            config.band_low_hz / 1000.0,
            " diagnostic band",
            color=theme.primary,
            fontsize=7,
            va="bottom",
            ha="right",
        )
    ax.set_ylim(0, nyq_khz)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Frequency (kHz)")
    ax.set_title(f"Linear spectrogram · {signal.sample_rate_hz / 1000:.1f} kHz · {signal.duration_s:.2f} s", loc="left", fontsize=10)
    cbar = fig.colorbar(mesh, ax=ax, pad=0.01, fraction=0.025)
    cbar.ax.tick_params(colors=theme.muted, labelsize=7)
    cbar.set_label("dB", color=theme.muted, fontsize=8)
    return _to_png(fig)


def psd_overlay_png(
    signal: Signal,
    config: ExperimentConfig,
    baseline_signal: Signal | None = None,
    theme: PlotTheme = PlotTheme(),
) -> bytes:
    """Welch PSD of the current signal against a healthy reference, with both bands shaded."""
    current = welch_psd(signal.audio, signal.sample_rate_hz, config.welch_nperseg)
    fig, ax = _figure(theme, (11, 3.8))
    if baseline_signal is not None:
        ref = welch_psd(baseline_signal.audio, baseline_signal.sample_rate_hz, config.welch_nperseg)
        ax.plot(ref.frequencies_hz / 1000.0, 10 * np.log10(ref.psd + 1e-14), color=theme.muted, lw=0.9, label="healthy baseline")
    ax.plot(current.frequencies_hz / 1000.0, 10 * np.log10(current.psd + 1e-14), color=theme.primary, lw=1.0, label="current")
    nyq = signal.sample_rate_hz / 2.0
    if config.band_low_hz < nyq:
        _shade_band(ax, config.band_low_hz / 1000.0, min(config.band_high_hz, nyq) / 1000.0, theme.secondary, "diagnostic")
    if config.reference_band_low_hz < nyq:
        _shade_band(ax, config.reference_band_low_hz / 1000.0, min(config.reference_band_high_hz, nyq) / 1000.0, theme.muted, "reference")
    ax.set_xlim(0, nyq / 1000.0)
    ax.set_xlabel("Frequency (kHz)")
    ax.set_ylabel("PSD (dB/Hz)")
    ax.set_title("Welch power spectral density", loc="left", fontsize=10)
    legend = ax.legend(loc="upper right", fontsize=8, frameon=False)
    for text in legend.get_texts():
        text.set_color(theme.text)
    return _to_png(fig)


def envelope_spectrum_png(
    signal: Signal,
    config: ExperimentConfig,
    theme: PlotTheme = PlotTheme(),
    expected_hz: float | None = None,
) -> bytes:
    """Envelope spectrum of the high-passed residual in the bearing-frequency range."""
    residual = highpass(signal.audio, signal.sample_rate_hz, config.highpass_hz)
    spec: Spectrum = envelope_spectrum(residual, signal.sample_rate_hz)
    mask = (spec.frequencies_hz >= 0) & (spec.frequencies_hz <= config.envelope_max_hz * 1.2)
    fig, ax = _figure(theme, (11, 3.2))
    ax.plot(spec.frequencies_hz[mask], spec.psd[mask], color=theme.primary, lw=1.0)
    ax.axvspan(config.envelope_min_hz, config.envelope_max_hz, color=theme.primary, alpha=0.08, lw=0)
    if expected_hz:
        ax.axvline(expected_hz, color=theme.secondary, lw=0.9, ls="--")
        ax.text(
            expected_hz,
            0.95,
            f" expected {expected_hz:.1f} Hz",
            color=theme.secondary,
            fontsize=7,
            transform=ax.get_xaxis_transform(),
            va="top",
        )
    ax.set_xlabel("Envelope frequency (Hz)")
    ax.set_ylabel("Amplitude")
    ax.set_title(f"Envelope spectrum of residual above {config.highpass_hz / 1000:.1f} kHz", loc="left", fontsize=10)
    return _to_png(fig)


def waveform_png(signal: Signal, config: ExperimentConfig, theme: PlotTheme = PlotTheme(), max_points: int = 20_000) -> bytes:
    """Waveform with detected impulses in the residual marked."""
    x = signal.audio.astype(np.float64)
    n = x.size
    step = max(1, n // max_points)
    t = np.arange(0, n, step) / signal.sample_rate_hz
    residual = highpass(x, signal.sample_rate_hz, config.highpass_hz)
    impulses = detect_impulses(residual, signal.sample_rate_hz)
    fig, ax = _figure(theme, (11, 2.8))
    ax.plot(t, x[::step], color=theme.primary, lw=0.5, alpha=0.9)
    if impulses.size:
        ax.vlines(impulses / signal.sample_rate_hz, -1, 1, color=theme.secondary, lw=0.6, alpha=0.5)
    ax.set_ylim(-1.05, 1.05)
    ax.set_xlim(0, signal.duration_s)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Amplitude")
    ax.set_title(f"Waveform · {impulses.size} impulsive events detected in residual", loc="left", fontsize=10)
    return _to_png(fig)


def channel_contributions_png(
    z_by_channel: dict[str, float],
    weights: dict[str, float],
    baseline: Baseline,
    config: ExperimentConfig,
    theme: PlotTheme = PlotTheme(),
) -> bytes:
    """Horizontal bars of weighted z per channel with the 50 % and critical lines."""
    names = [c for c in z_by_channel if np.isfinite(z_by_channel[c])]
    values = [weights.get(c, 0.0) * z_by_channel[c] for c in names]
    fig, ax = _figure(theme, (6.5, 2.9))
    colors = [theme.danger if v > config.z_center else theme.primary for v in values]
    ax.barh(names, values, color=colors, height=0.6)
    ax.axvline(config.z_center, color=theme.secondary, lw=0.9, ls="--")
    ax.text(config.z_center, 1.02, " 50 % score", color=theme.secondary, fontsize=8, transform=ax.get_xaxis_transform(), va="bottom")
    ax.set_xlabel(f"Weighted z-score vs {baseline.n} healthy references (0 = baseline)")
    ax.set_xlim(0, max(6.0, max(values, default=0.0) * 1.15))
    ax.tick_params(axis="y", labelsize=9, colors=theme.text)
    ax.tick_params(axis="x", labelsize=8)
    return _to_png(fig, dpi=120)
