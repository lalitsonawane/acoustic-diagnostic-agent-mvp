"""Acoustic Diagnostic Agent - Streamlit front-end.

All signal processing lives in the ``acoustic_agent`` package; this file only wires
widgets to :func:`acoustic_agent.pipeline.analyze` and renders results.
"""

from __future__ import annotations

import json
from dataclasses import fields
from datetime import UTC, datetime
from typing import Any, Literal

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from acoustic_agent import FEATURE_VERSION, __version__
from acoustic_agent.config import (
    MACHINE_PROFILES,
    PROFILE_BY_KEY,
    ExperimentConfig,
    config_hash,
    sweepable_parameters,
)
from acoustic_agent.decision import STATE_COLORS, STATE_ICONS, work_order_payload
from acoustic_agent.detect import CHANNELS, Baseline, calibrate_baseline
from acoustic_agent.features import extract_features
from acoustic_agent.io import (
    AudioLoadError,
    SampleEntry,
    audio_to_wav_bytes,
    labels_from_manifest_text,
    load_audio,
    load_sample_manifest,
    result_npz_bytes,
    rows_to_csv,
)
from acoustic_agent.pipeline import AnalysisResult, BatchResult, analyze, run_batch, sweep
from acoustic_agent.plots import (
    PlotTheme,
    channel_contributions_png,
    envelope_spectrum_png,
    psd_overlay_png,
    spectrogram_png,
    waveform_png,
)
from acoustic_agent.synth import Signal, healthy_reference, synthesize

st.set_page_config(
    page_title="Acoustic Diagnostic Agent",
    page_icon=":material/graphic_eq:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ----------------------------------------------------------------------------------
# Constants and small helpers
# ----------------------------------------------------------------------------------

SIDEBAR_FIELDS = (
    "profile",
    "inject_bursts",
    "inject_bearing_impacts",
    "seed",
    "noise_std",
    "burst_amplitude",
    "warn_threshold",
    "critical_threshold",
    "demo_boost",
)
DEMO_BOOST_POINTS = 60.0


def plot_theme() -> PlotTheme:
    try:
        return PlotTheme() if st.context.theme.type == "dark" else PlotTheme.light()
    except Exception:  # pragma: no cover - theme unavailable in some test contexts
        return PlotTheme()


@st.cache_data(show_spinner=False, max_entries=32, ttl=3600)
def cached_baseline(config_json: str) -> Baseline:
    return calibrate_baseline(ExperimentConfig.from_text(config_json))


@st.cache_data(show_spinner=False, max_entries=64, ttl=3600)
def cached_analysis(audio: np.ndarray, sample_rate_hz: int, source: str, config_json: str, baseline_json: str) -> AnalysisResult:
    cfg = ExperimentConfig.from_text(config_json)
    baseline = Baseline.from_dict(json.loads(baseline_json))
    return analyze(Signal(audio=audio, sample_rate_hz=sample_rate_hz, source=source), cfg, baseline)


@st.cache_data(show_spinner=False, max_entries=64, ttl=3600)
def cached_plot(kind: str, audio: np.ndarray, sample_rate_hz: int, source: str, config_json: str, dark: bool) -> bytes:
    cfg = ExperimentConfig.from_text(config_json)
    sig = Signal(audio=audio, sample_rate_hz=sample_rate_hz, source=source)
    theme = PlotTheme() if dark else PlotTheme.light()
    if kind == "spectrogram":
        return spectrogram_png(sig, cfg, theme)
    if kind == "psd":
        ref = healthy_reference(cfg.with_updates(sample_rate_hz=sig.sample_rate_hz), seed=10_000)
        return psd_overlay_png(sig, cfg, ref, theme)
    if kind == "envelope":
        expected = cfg.shaft_hz * cfg.bpfo_ratio if cfg.inject_bearing_impacts else None
        return envelope_spectrum_png(sig, cfg, theme, expected_hz=expected)
    if kind == "waveform":
        return waveform_png(sig, cfg, theme)
    raise ValueError(kind)


@st.cache_data(show_spinner=False)
def cached_manifest() -> list[SampleEntry]:
    return load_sample_manifest()


@st.cache_data(show_spinner=False, max_entries=64)
def cached_sample(path: str) -> Signal:
    return load_audio(path)


def init_state() -> None:
    """``cfg`` is the single source of truth; sidebar widgets mirror it via callbacks.

    Widget keys are removed by Streamlit when a widget is not rendered (for example when
    the source mode hides it), so values are never read from widget keys directly.
    """
    if "cfg" not in st.session_state:
        st.session_state.cfg = ExperimentConfig().to_dict()
    st.session_state.setdefault("signal", None)
    st.session_state.setdefault("run_log", [])
    st.session_state.setdefault("custom_baseline_feats", [])
    st.session_state.setdefault("custom_baseline", None)
    st.session_state.setdefault("approvals", [])
    st.session_state.setdefault("last_logged_key", None)
    st.session_state.setdefault("source_mode", "Simulate")


def _to_widget(name: str, value: Any) -> Any:
    return bool(value > 0) if name == "demo_boost" else value


def _from_widget(name: str, value: Any) -> Any:
    return (DEMO_BOOST_POINTS if value else 0.0) if name == "demo_boost" else value


def sync_widget(name: str) -> None:
    st.session_state.cfg[name] = _from_widget(name, st.session_state[f"w_{name}"])


def seed_widget(name: str) -> str:
    """Ensure the widget key exists (seeded from ``cfg``) and return it."""
    key = f"w_{name}"
    if key not in st.session_state:
        st.session_state[key] = _to_widget(name, st.session_state.cfg[name])
    return key


def current_config() -> ExperimentConfig:
    return ExperimentConfig.from_dict(dict(st.session_state.cfg))


def apply_imported_config(text: str) -> None:
    cfg = ExperimentConfig.from_text(text)
    st.session_state.cfg = cfg.to_dict()
    for name in SIDEBAR_FIELDS:
        key = f"w_{name}"
        if key in st.session_state:
            st.session_state[key] = _to_widget(name, getattr(cfg, name))


def on_config_upload() -> None:
    file = st.session_state.get("config_upload")
    if file is None:
        return
    try:
        apply_imported_config(file.getvalue().decode("utf-8"))
        st.session_state.config_import_msg = ("success", f"Imported configuration from {file.name}.")
    except (ValueError, UnicodeDecodeError) as exc:
        st.session_state.config_import_msg = ("error", f"Could not import configuration: {exc}")


def on_reset_config() -> None:
    apply_imported_config(ExperimentConfig().to_json())
    st.session_state.custom_baseline = None
    st.session_state.custom_baseline_feats = []


def profile_for_sample(entry: SampleEntry, fallback: str) -> str:
    profile = PROFILE_BY_KEY.get(entry.machine_profile)
    return profile.name if profile else fallback


def state_badge(state: str, confidence: float) -> None:
    color = STATE_COLORS.get(state, "gray")
    st.badge(state, icon=STATE_ICONS.get(state), color=color)  # type: ignore[arg-type]
    conf_color: Literal["green", "orange", "red"] = "green" if confidence >= 0.8 else "orange" if confidence >= 0.6 else "red"
    st.badge(
        f"confidence {confidence:.0%}",
        icon=":material/verified:",
        color=conf_color,
        help="Heuristic input-quality factor, not a probability. Reduced by clipping, low sample rate or short captures.",
    )


def log_run(result: AnalysisResult) -> None:
    key = (result.signal.source, config_hash(result.config), result.baseline.source)
    if st.session_state.last_logged_key == key:
        return
    st.session_state.run_log.append(result.summary_row({"baseline": result.baseline.source}))
    st.session_state.last_logged_key = key


# ----------------------------------------------------------------------------------
# Sidebar: Source -> Configure -> Analyse
# ----------------------------------------------------------------------------------

init_state()
manifest = cached_manifest()

with st.sidebar:
    st.header("Acoustic diagnostic agent")
    st.caption(f"v{__version__} · {FEATURE_VERSION}")

    st.subheader("1 · Source", divider="gray")
    mode = st.segmented_control(
        "Signal source",
        ["Simulate", "Upload", "Sample library"],
        default=st.session_state.source_mode,
        label_visibility="collapsed",
        width="stretch",
    )
    if mode:
        st.session_state.source_mode = mode
    mode = st.session_state.source_mode

    if mode == "Simulate":
        st.selectbox(
            "Machine profile",
            list(MACHINE_PROFILES),
            key=seed_widget("profile"),
            on_change=sync_widget,
            args=("profile",),
            help="Sets the tonal signature and the healthy baseline.",
        )
        st.toggle(
            "Inject 22 kHz micro-crack bursts",
            key=seed_widget("inject_bursts"),
            on_change=sync_widget,
            args=("inject_bursts",),
            help="Adds short damped ultrasonic bursts to the synthetic signal. This is a physical change to the waveform, not a score override.",
        )
        st.toggle(
            "Inject bearing outer-race impacts",
            key=seed_widget("inject_bearing_impacts"),
            on_change=sync_widget,
            args=("inject_bearing_impacts",),
            help="Adds periodic impacts at BPFO that ring a 5.2 kHz resonance - invisible above 20 kHz, visible in the envelope spectrum.",
        )
        st.number_input(
            "Seed",
            min_value=0,
            max_value=1_000_000,
            step=1,
            key=seed_widget("seed"),
            on_change=sync_widget,
            args=("seed",),
            help="Change to draw a different noise realisation.",
        )
        if st.button("Generate signal", key="generate", type="primary", icon=":material/play_arrow:", width="stretch"):
            st.session_state.signal = synthesize(current_config())
            st.toast("Synthetic signal generated", icon=":material/check:")
    elif mode == "Upload":
        st.selectbox(
            "Machine profile (for baseline)", list(MACHINE_PROFILES), key=seed_widget("profile"), on_change=sync_widget, args=("profile",)
        )
        upload = st.file_uploader(
            "Acoustic recording", type=["wav", "flac", "ogg"], help="Mono or multi-channel; channels are averaged. Max 50 MB / 120 s."
        )
        if upload is not None:
            try:
                st.session_state.signal = load_audio(upload.getvalue(), name=upload.name)
            except AudioLoadError as exc:
                st.error(str(exc))
    else:
        if manifest:
            labels = {e.file: f"{e.file}  ·  {e.condition}" for e in manifest}
            choice = st.selectbox("Sample", [e.file for e in manifest], key="sample_choice", format_func=labels.__getitem__)
            entry = next(e for e in manifest if e.file == choice)
            st.caption(entry.purpose)
            if st.button("Load sample", key="load_sample", type="primary", icon=":material/library_music:", width="stretch"):
                try:
                    st.session_state.signal = cached_sample(str(entry.path))
                    st.session_state.cfg["profile"] = profile_for_sample(entry, st.session_state.cfg["profile"])
                    st.rerun()
                except (AudioLoadError, OSError) as exc:
                    st.error(str(exc))
        else:
            st.info("No sample library found at data/samples.")

    st.subheader("2 · Configure", divider="gray")
    st.slider(
        "Noise level (std)",
        0.0,
        0.2,
        step=0.002,
        key=seed_widget("noise_std"),
        on_change=sync_widget,
        args=("noise_std",),
        format="%.3f",
        help="Broadband measurement noise in the synthetic model and its healthy baseline.",
    )
    st.slider(
        "Burst amplitude",
        0.0,
        1.0,
        step=0.01,
        key=seed_widget("burst_amplitude"),
        on_change=sync_widget,
        args=("burst_amplitude",),
        help="Strength of injected micro-crack bursts (synthetic only).",
    )
    st.slider(
        "Warning threshold (%)", 0.0, 99.0, step=1.0, key=seed_widget("warn_threshold"), on_change=sync_widget, args=("warn_threshold",)
    )
    st.slider(
        "Critical threshold (%)",
        1.0,
        100.0,
        step=1.0,
        key=seed_widget("critical_threshold"),
        on_change=sync_widget,
        args=("critical_threshold",),
    )
    st.toggle(
        f"Teaching demo boost (+{DEMO_BOOST_POINTS:.0f} points, not a measurement)",
        key=seed_widget("demo_boost"),
        on_change=sync_widget,
        args=("demo_boost",),
        help="Forces the critical path for classroom demonstrations. Flagged in every result and payload.",
    )
    with st.expander("Import / export configuration"):
        st.file_uploader("Import YAML or JSON", type=["yaml", "yml", "json"], key="config_upload", on_change=on_config_upload)
        msg = st.session_state.pop("config_import_msg", None)
        if msg:
            (st.success if msg[0] == "success" else st.error)(msg[1])
        cfg_preview = current_config()
        c1, c2 = st.columns(2)
        c1.download_button("YAML", cfg_preview.to_yaml(), file_name="experiment.yaml", mime="text/yaml", width="stretch")
        c2.download_button("JSON", cfg_preview.to_json(), file_name="experiment.json", mime="application/json", width="stretch")
        st.button("Reset to defaults", on_click=on_reset_config, width="stretch")

    st.subheader("3 · Analyse", divider="gray")

# ----------------------------------------------------------------------------------
# Analysis (runs on every interaction, cached)
# ----------------------------------------------------------------------------------

try:
    config = current_config()
except ValueError as exc:
    st.sidebar.error(f"Configuration invalid: {exc}")
    st.stop()

if st.session_state.signal is None:
    st.session_state.signal = synthesize(config)
    st.session_state.first_run = True

signal: Signal = st.session_state.signal
config_json = config.to_json()
baseline: Baseline = st.session_state.custom_baseline or cached_baseline(config_json)
result = cached_analysis(signal.audio, signal.sample_rate_hz, signal.source, config_json, json.dumps(baseline.to_dict()))
log_run(result)
is_dark = plot_theme().background == PlotTheme().background

with st.sidebar:
    st.caption(
        f"Analysed {result.analysed_at.astimezone().strftime('%H:%M:%S')} · config `{config_hash(config)}` · baseline {baseline.n} refs"
    )
    st.caption(f"Source: {signal.source}")

# ----------------------------------------------------------------------------------
# Main layout
# ----------------------------------------------------------------------------------

st.title("Acoustic diagnostic agent")
st.caption(
    "High-frequency acoustic evidence is compared against a healthy baseline and turned into a "
    "maintenance decision. Educational MVP: nothing is sent to SAP."
)

if st.session_state.pop("first_run", False):
    st.info(
        "A healthy synthetic signal was generated to start. Try **Sample library** in the sidebar to load "
        "labelled test recordings, or toggle a fault injection and press **Generate signal**.",
        icon=":material/lightbulb:",
    )

tab_monitor, tab_experiment, tab_batch, tab_methods = st.tabs(["Monitor", "Experiment", "Batch", "Methods"])

# ---------------------------------------------------------------- Monitor -----------
with tab_monitor:
    decision, detection, validity = result.decision, result.detection, result.validity
    banner = {"HEALTHY": st.success, "WARNING": st.warning, "CRITICAL": st.error, "CRITICAL (unconfirmed)": st.warning, "INVALID": st.info}[
        decision.state
    ]
    banner(f"**{decision.state}** — {decision.explanation}", icon=STATE_ICONS[decision.state])
    for warning in validity.warnings:
        if decision.state != "INVALID":
            st.warning(warning, icon=":material/report:")

    prev_score = st.session_state.run_log[-2]["score"] if len(st.session_state.run_log) >= 2 else None
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "Machine health",
        decision.state,
        help="HEALTHY / WARNING / CRITICAL from the score thresholds; INVALID when input fails validity checks.",
        border=True,
    )
    m2.metric(
        "Anomaly score",
        f"{detection.score:.1f} %",
        delta=None if prev_score is None else f"{detection.score - prev_score:+.1f} vs previous run",
        delta_color="inverse",
        help="Logistic squash of the strongest weighted z-score against the healthy baseline. 3σ = 50 %.",
        border=True,
    )
    m3.metric(
        "Confidence",
        f"{validity.confidence:.0%}",
        help="Input-quality factor in [0, 1]. Below the minimum, critical verdicts are marked unconfirmed.",
        border=True,
    )
    m4.metric(
        "Estimated RUL",
        "—" if decision.rul_days is None else f"{decision.rul_days} days",
        help="Illustrative only: nominal RUL scaled by the score. Not a survival model.",
        border=True,
    )

    viz_col, action_col = st.columns([1.6, 1], gap="large")
    with viz_col:
        st.subheader("Signal analysis")
        view = st.pills(
            "View", ["Spectrogram", "PSD vs baseline", "Envelope spectrum", "Waveform"], default="Spectrogram", label_visibility="collapsed"
        )
        kind = {
            "Spectrogram": "spectrogram",
            "PSD vs baseline": "psd",
            "Envelope spectrum": "envelope",
            "Waveform": "waveform",
            None: "spectrogram",
        }[view]
        st.image(cached_plot(kind, signal.audio, signal.sample_rate_hz, signal.source, config_json, is_dark), width="stretch")
        feats = result.features
        with st.container(border=True):
            st.markdown("**Evidence channels** (value → z-score vs baseline)")
            rows = []
            for ch in CHANNELS:
                value = feats.channels()[ch]
                z = detection.z_by_channel.get(ch, float("nan"))
                rows.append(
                    {
                        "channel": ch,
                        "value": None if not np.isfinite(value) else round(float(value), 3),
                        "baseline mean": round(baseline.mean.get(ch, float("nan")), 3),
                        "z": None if not np.isfinite(z) else round(float(z), 2),
                        "weight": config.weights.get(ch, 0.0),
                        "driver": "◀" if ch == detection.driver else "",
                    }
                )
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            if np.isfinite(feats.envelope_peak_hz):
                st.caption(
                    f"Envelope peak at {feats.envelope_peak_hz:.1f} Hz · residual high-passed above {config.highpass_hz / 1000:.1f} kHz"
                )

    with action_col:
        st.subheader("Recommended action")
        st.image(channel_contributions_png(detection.z_by_channel, config.weights, baseline, config, plot_theme()), width="stretch")
        with st.status("Analysis steps", expanded=False, state="complete"):
            for name, ts in result.steps:
                st.write(f"`{ts.astimezone().strftime('%H:%M:%S.%f')[:-3]}` {name}")
        state_badge(decision.state, validity.confidence)
        st.write(decision.recommended_action)
        if decision.actionable:
            payload = work_order_payload(config.machine(), detection, decision, config, source=signal.source)
            st.markdown("**Proposed SAP S/4HANA PM work order (mock)**")
            st.json(payload, expanded=False)
            approved_ids = {a["ticket_id"] for a in st.session_state.approvals}
            if st.button("Approve work order (simulated planner gate)", key="approve", icon=":material/how_to_reg:", width="stretch"):
                st.session_state.approvals.append(
                    {**payload, "approved_at": datetime.now(UTC).isoformat(timespec="seconds"), "status": "APPROVED (simulated)"}
                )
                st.toast("Work order approved in the simulated audit log", icon=":material/check:")
            if approved_ids:
                st.caption(f"{len(approved_ids)} simulated approval(s) recorded this session.")
        elif decision.state == "CRITICAL (unconfirmed)":
            st.info("No work order is proposed while confidence is below the configured minimum.", icon=":material/info:")

    with st.expander("Export", icon=":material/download:"):
        e1, e2, e3, e4 = st.columns(4)
        e1.download_button(
            "Run log CSV",
            rows_to_csv(st.session_state.run_log),
            file_name="run_log.csv",
            mime="text/csv",
            width="stretch",
            disabled=not st.session_state.run_log,
        )
        e2.download_button(
            "Result JSON",
            json.dumps(result.to_dict(), indent=2, default=str),
            file_name="analysis.json",
            mime="application/json",
            width="stretch",
        )
        e3.download_button(
            "Signal + metadata NPZ",
            result_npz_bytes(signal, result.to_dict()),
            file_name="signal.npz",
            mime="application/octet-stream",
            width="stretch",
        )
        e4.download_button("Signal WAV", audio_to_wav_bytes(signal), file_name="signal.wav", mime="audio/wav", width="stretch")
        p1, p2, p3, p4 = st.columns(4)
        for col, kind_name in zip((p1, p2, p3, p4), ("spectrogram", "psd", "envelope", "waveform"), strict=True):
            col.download_button(
                f"{kind_name} PNG",
                cached_plot(kind_name, signal.audio, signal.sample_rate_hz, signal.source, config_json, is_dark),
                file_name=f"{kind_name}.png",
                mime="image/png",
                width="stretch",
            )
        if st.session_state.approvals:
            st.download_button(
                "Approval audit log JSON",
                json.dumps(st.session_state.approvals, indent=2),
                file_name="approvals.json",
                mime="application/json",
            )

# ---------------------------------------------------------------- Experiment --------
with tab_experiment:
    st.subheader("Advanced parameters")
    st.caption(
        "Sidebar controls cover the common knobs; everything else is here. Changes apply on submit and are reflected in the configuration hash."
    )
    numeric_fields = [
        f
        for f in fields(ExperimentConfig)
        if f.name not in SIDEBAR_FIELDS and f.name not in {"weights", "std_floors", "inject_bursts", "inject_bearing_impacts"}
    ]
    with st.form("advanced_form", border=True):
        cols = st.columns(3)
        new_values: dict[str, Any] = {}
        for i, f in enumerate(numeric_fields):
            current = st.session_state.cfg[f.name]
            with cols[i % 3]:
                if isinstance(current, bool):
                    new_values[f.name] = st.checkbox(f.name, value=current)
                elif isinstance(current, int) and not isinstance(current, bool):
                    new_values[f.name] = st.number_input(f.name, value=int(current), step=1)
                elif isinstance(current, float):
                    new_values[f.name] = st.number_input(f.name, value=float(current), format="%.4f")
                else:
                    new_values[f.name] = st.text_input(f.name, value=str(current))
        st.markdown("**Channel weights** (0 excludes a channel from the verdict) and **baseline std floors**")
        wcols = st.columns(len(CHANNELS))
        weights: dict[str, float] = {}
        floors: dict[str, float] = {}
        for col, ch in zip(wcols, CHANNELS, strict=True):
            with col:
                weights[ch] = st.number_input(
                    f"w · {ch}", min_value=0.0, max_value=2.0, value=float(st.session_state.cfg["weights"][ch]), step=0.1
                )
                floors[ch] = st.number_input(
                    f"floor · {ch}", min_value=1e-3, value=float(st.session_state.cfg["std_floors"][ch]), format="%.3f"
                )
        if st.form_submit_button("Apply advanced parameters", type="primary", icon=":material/tune:"):
            candidate = dict(st.session_state.cfg)
            candidate.update(new_values)
            candidate["weights"] = weights
            candidate["std_floors"] = floors
            try:
                ExperimentConfig.from_dict(candidate)
                st.session_state.cfg = candidate
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    st.subheader("Baseline")
    b1, b2 = st.columns([1.4, 1])
    with b1:
        st.caption(f"Active baseline: `{baseline.source}` from {baseline.n} healthy references.")
        st.dataframe(
            pd.DataFrame(
                {
                    "channel": list(baseline.mean),
                    "mean": list(baseline.mean.values()),
                    "std": list(baseline.std.values()),
                    "floor": [config.std_floors[c] for c in baseline.mean],
                }
            ),
            hide_index=True,
            width="stretch",
        )
    with b2:
        st.write("Build a baseline from recordings you know to be healthy (at least two).")
        n_custom = len(st.session_state.custom_baseline_feats)
        if st.button(f"Add current signal as healthy reference ({n_custom} collected)", icon=":material/add:", width="stretch"):
            st.session_state.custom_baseline_feats.append(extract_features(signal.audio, signal.sample_rate_hz, config))
            if len(st.session_state.custom_baseline_feats) >= 2:
                st.session_state.custom_baseline = Baseline.from_features(
                    st.session_state.custom_baseline_feats, source=f"custom:{len(st.session_state.custom_baseline_feats)}-recordings"
                )
            st.rerun()
        if st.button(
            "Reset to synthetic baseline",
            icon=":material/restart_alt:",
            width="stretch",
            disabled=st.session_state.custom_baseline is None and n_custom == 0,
        ):
            st.session_state.custom_baseline = None
            st.session_state.custom_baseline_feats = []
            st.rerun()

    st.subheader("Parameter sweep")

    @st.fragment
    def sweep_tool(base_config_json: str) -> None:
        base = ExperimentConfig.from_text(base_config_json)
        s1, s2, s3, s4, s5 = st.columns([1.4, 1, 1, 1, 1])
        parameter = s1.selectbox("Parameter", list(sweepable_parameters()), format_func=lambda p: f"{p} — {sweepable_parameters()[p]}")
        current_value = float(getattr(base, parameter))
        lo = s2.number_input("From", value=0.0 if current_value > 0 else current_value - 1.0, format="%.4f")
        hi = s3.number_input("To", value=max(current_value * 2, current_value + 0.1), format="%.4f")
        steps = int(s4.number_input("Steps", min_value=2, max_value=25, value=6))
        seeds = int(s5.number_input("Seeds", min_value=1, max_value=10, value=3))
        fault_mode = st.segmented_control("Fault model", ["bursts", "bearing"], default="bursts")
        if st.button("Run sweep", key="run_sweep", type="primary", icon=":material/stacked_line_chart:"):
            values = [float(v) for v in np.linspace(lo, hi, steps)]
            with st.spinner("Sweeping…"):
                try:
                    points = sweep(base, parameter, values, seeds=seeds, fault_mode=fault_mode or "bursts")
                except ValueError as exc:
                    st.error(str(exc))
                    return
            st.session_state.sweep_rows = [p.row() | {"parameter": parameter} for p in points]
        rows = st.session_state.get("sweep_rows")
        if rows:
            df = pd.DataFrame(rows)
            long = pd.concat(
                [
                    pd.DataFrame(
                        {
                            "value": df["value"],
                            "score": df["fault_mean"],
                            "low": df["fault_min"],
                            "high": df["fault_max"],
                            "condition": "fault",
                        }
                    ),
                    pd.DataFrame(
                        {
                            "value": df["value"],
                            "score": df["healthy_mean"],
                            "low": df["healthy_min"],
                            "high": df["healthy_max"],
                            "condition": "healthy",
                        }
                    ),
                ]
            )
            band = (
                alt.Chart(long)
                .mark_area(opacity=0.2)
                .encode(x=alt.X("value:Q", title=rows[0]["parameter"]), y="low:Q", y2="high:Q", color="condition:N")
            )
            line = (
                alt.Chart(long)
                .mark_line(point=True)
                .encode(x="value:Q", y=alt.Y("score:Q", title="Anomaly score (%)", scale=alt.Scale(domain=[0, 100])), color="condition:N")
            )
            rule = alt.Chart(pd.DataFrame({"y": [base.critical_threshold]})).mark_rule(strokeDash=[4, 4]).encode(y="y:Q")
            st.altair_chart(band + line + rule, width="stretch")
            st.dataframe(df, hide_index=True, width="stretch")
            st.download_button("Sweep CSV", rows_to_csv(rows), file_name="sweep.csv", mime="text/csv")

    sweep_tool(config_json)

    st.subheader("Run log")
    if st.session_state.run_log:
        st.dataframe(pd.DataFrame(st.session_state.run_log), hide_index=True, width="stretch")
        r1, r2 = st.columns([1, 5])
        r1.download_button("Download CSV", rows_to_csv(st.session_state.run_log), file_name="run_log.csv", mime="text/csv", width="stretch")
        if r2.button("Clear log", icon=":material/delete:"):
            st.session_state.run_log = []
            st.session_state.last_logged_key = None
            st.rerun()
    else:
        st.caption("Every distinct (signal, configuration, baseline) analysis is appended here automatically.")

# ---------------------------------------------------------------- Batch -------------
with tab_batch:
    st.subheader("Batch evaluation")
    st.caption(
        "Score many recordings with one shared baseline, then evaluate the detector against ground-truth labels with ROC / precision-recall curves."
    )

    @st.fragment
    def batch_tool(base_config_json: str, baseline_json: str) -> None:
        base = ExperimentConfig.from_text(base_config_json)
        shared_baseline = Baseline.from_dict(json.loads(baseline_json))
        left, right = st.columns([1, 1])
        with left:
            labelled = [e.file for e in manifest]
            chosen = st.multiselect("Sample library files", labelled, default=[e.file for e in manifest if e.label is not None])
        with right:
            uploads = st.file_uploader("Additional recordings", type=["wav", "flac", "ogg"], accept_multiple_files=True)
            manifest_upload = st.file_uploader("Optional labels CSV (file,condition|label)", type=["csv"])

        upload_labels: dict[str, int | None] = {}
        if manifest_upload is not None:
            upload_labels = labels_from_manifest_text(manifest_upload.getvalue().decode("utf-8"))
        label_rows = [{"file": u.name, "label": upload_labels.get(u.name)} for u in uploads or []]
        if label_rows:
            st.caption("Edit labels for uploaded files (1 = fault, 0 = healthy, blank = exclude from metrics).")
            edited = st.data_editor(
                pd.DataFrame(label_rows),
                hide_index=True,
                width="stretch",
                column_config={"label": st.column_config.NumberColumn(min_value=0, max_value=1, step=1)},
            )
            upload_labels = {row["file"]: (None if pd.isna(row["label"]) else int(row["label"])) for _, row in edited.iterrows()}

        if st.button("Run batch", key="run_batch", type="primary", icon=":material/playlist_play:"):
            signals: list[tuple[Signal, int | None]] = []
            for entry in manifest:
                if entry.file in chosen:
                    signals.append((cached_sample(str(entry.path)), entry.label))
            for u in uploads or []:
                try:
                    signals.append((load_audio(u.getvalue(), name=u.name), upload_labels.get(u.name)))
                except AudioLoadError as exc:
                    st.warning(f"Skipped {u.name}: {exc}")
            if not signals:
                st.warning("Select at least one recording.")
                return
            with st.spinner(f"Scoring {len(signals)} recordings…"):
                st.session_state.batch = run_batch(signals, base, shared_baseline)

        batch: BatchResult | None = st.session_state.get("batch")
        if batch is None:
            return
        df = pd.DataFrame(batch.rows)
        show_cols = [
            "source",
            "label",
            "state",
            "score",
            "confidence",
            "driver",
            "flags",
            "feat_band_contrast_db",
            "feat_band_contrast_transient_db",
            "feat_residual_kurtosis",
            "feat_envelope_peak_snr_db",
        ]
        st.dataframe(df[[c for c in show_cols if c in df.columns]], hide_index=True, width="stretch")
        report = batch.report
        if report is not None:
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric(
                "ROC AUC",
                "—" if report.roc is None else f"{report.roc.auc:.3f}",
                help="Area under the ROC curve; 1.0 = perfect ranking.",
                border=True,
            )
            k2.metric("Average precision", "—" if report.pr is None else f"{report.pr.auc:.3f}", border=True)
            k3.metric(f"Precision @ {report.threshold:.0f}", f"{report.precision:.2f}", border=True)
            k4.metric(f"Recall @ {report.threshold:.0f}", f"{report.recall:.2f}", border=True)
            k5.metric("Confusion", f"TP {report.tp} FP {report.fp} TN {report.tn} FN {report.fn}", border=True)
            if report.roc is not None and report.pr is not None:
                c1, c2 = st.columns(2)
                roc_df = pd.DataFrame({"FPR": report.roc.x, "TPR": report.roc.y})
                pr_df = pd.DataFrame({"Recall": report.pr.x, "Precision": report.pr.y})
                roc_chart = (
                    alt.Chart(roc_df)
                    .mark_line(point=True)
                    .encode(x=alt.X("FPR:Q", scale=alt.Scale(domain=[0, 1])), y=alt.Y("TPR:Q", scale=alt.Scale(domain=[0, 1])))
                    .properties(title=f"ROC (AUC {report.roc.auc:.3f})")
                )
                diag = (
                    alt.Chart(pd.DataFrame({"x": [0, 1], "y": [0, 1]})).mark_line(strokeDash=[4, 4], color="gray").encode(x="x:Q", y="y:Q")
                )
                c1.altair_chart(roc_chart + diag, width="stretch")
                pr_chart = (
                    alt.Chart(pr_df)
                    .mark_line(point=True)
                    .encode(x=alt.X("Recall:Q", scale=alt.Scale(domain=[0, 1])), y=alt.Y("Precision:Q", scale=alt.Scale(domain=[0, 1])))
                    .properties(title=f"Precision-recall (AP {report.pr.auc:.3f})")
                )
                c2.altair_chart(pr_chart, width="stretch")
            for note in report.notes:
                st.info(note)
        if batch.skipped:
            st.caption("Excluded from metrics (unlabelled or invalid): " + ", ".join(batch.skipped))
        st.download_button("Batch results CSV", rows_to_csv(batch.rows), file_name="batch_results.csv", mime="text/csv")

    batch_tool(config_json, json.dumps(baseline.to_dict()))

# ---------------------------------------------------------------- Methods -----------
with tab_methods:
    st.markdown(
        f"""
        ### How the verdict is produced

        **1. Signal model.** Synthetic captures are a rotating-machine tone (carrier + third harmonic) in white
        noise at {config.sample_rate_hz / 1000:.0f} kHz. Two fault models can be injected: damped
        {config.burst_frequency_hz / 1000:.0f} kHz micro-crack bursts, and outer-race bearing impacts at
        BPFO ≈ {config.shaft_hz * config.bpfo_ratio:.1f} Hz that ring a {config.resonance_hz / 1000:.1f} kHz resonance.

        **2. Features** (all normalised, so gain and recording length do not matter):

        | Channel | What it measures | Fires on |
        | --- | --- | --- |
        | `band_contrast_db` | Welch PSD in {config.band_low_hz / 1000:.0f}–{config.band_high_hz / 1000:.0f} kHz relative to the {config.reference_band_low_hz / 1000:.0f}–{config.reference_band_high_hz / 1000:.0f} kHz reference band | Narrow-band ultrasonic content; ≈ 0 dB for white noise of any level |
        | `band_contrast_transient_db` | 98th percentile − median of the same contrast computed per ~20 ms STFT frame | Short bursts that whole-capture averaging dilutes, e.g. under heavy noise; ≈ 1–2 dB for stationary noise |
        | `band_power_db` | Diagnostic band relative to total power | Any high-frequency energy, including broadband noise (weight 0 by default) |
        | `residual_kurtosis` | Kurtosis of the residual high-passed above {config.highpass_hz / 1000:.1f} kHz (Gaussian = 3) | Repetitive impacts / clicks |
        | `residual_crest_factor` | Peak ÷ RMS of the residual | Isolated impulses |
        | `envelope_peak_snr_db` | Prominence of the strongest line in the Hilbert-envelope spectrum ({config.envelope_min_hz:.0f}–{config.envelope_max_hz:.0f} Hz) | Periodic bearing defects (BPFO / BPFI / BSF) |

        **3. Baseline.** {config.baseline_seeds} healthy synthetic renders of the selected profile give a mean and
        standard deviation per channel. The standard deviation is floored so near-deterministic baselines do not
        explode z-scores. You can replace it with your own healthy recordings in the Experiment tab.

        **4. Score.** $z_c = \\max(0, (x_c - \\mu_c) / \\max(\\sigma_c, \\mathrm{{floor}}_c))$, then
        $z = \\max_c w_c z_c$ and $\\mathrm{{score}} = 100 / (1 + e^{{-(z - {config.z_center:g}) / {config.z_scale:g}}})$.
        The strongest channel drives the verdict, so a bearing defect that is invisible above 20 kHz can still alarm
        through the envelope spectrum. A {config.z_center:g}σ excursion scores 50 %.

        **5. Validity gating.** Silence invalidates the input. Low sample rate (band above Nyquist), clipping and short
        captures reduce a confidence factor. A critical score with confidence below {config.min_confidence:.0%} is
        reported as *CRITICAL (unconfirmed)* and no work order is proposed.

        **6. Decision.** HEALTHY ≤ {config.warn_threshold:.0f} % < WARNING ≤ {config.critical_threshold:.0f} % < CRITICAL.
        A critical, confident verdict produces a mock SAP S/4HANA PM payload carrying the configuration hash
        (`{config_hash(config)}`), feature version (`{FEATURE_VERSION}`), real timestamps and a UUID-derived ticket id.
        Nothing is transmitted.

        **Teaching demo boost.** The sidebar toggle adds a fixed {DEMO_BOOST_POINTS:.0f} points *after* scoring so a
        lesson can show the critical path on demand. It is flagged in the explanation, run log and payload and must
        never be mistaken for a measurement.
        """
    )
    with st.expander("Glossary"):
        st.markdown(
            """
            - **Nyquist frequency** — half the sample rate; the highest frequency a recording can represent. A 16 kHz file cannot contain a 22 kHz fault.
            - **Welch PSD** — power spectral density estimated by averaging windowed FFTs; smoother and gain-normalised compared with a single FFT.
            - **Kurtosis** — fourth standardised moment; 3 for Gaussian noise, higher when the signal contains sharp impulses.
            - **Crest factor** — peak amplitude divided by RMS; another impulsiveness measure.
            - **Envelope spectrum** — spectrum of the Hilbert envelope; reveals the *repetition rate* of impacts (e.g. BPFO) rather than their carrier frequency.
            - **BPFO** — ball-pass frequency, outer race: how often rolling elements strike an outer-race defect; ≈ 3.585 × shaft speed for the modelled bearing.
            - **z-score** — number of baseline standard deviations a feature is above the healthy mean.
            - **ROC AUC / average precision** — ranking quality of the score over labelled recordings; 1.0 is perfect.
            - **RUL** — remaining useful life. Here purely illustrative.
            """
        )
    st.markdown(
        """
        **Further reading:** [application documentation](https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp/blob/main/docs/application.md) ·
        [architecture](https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp/blob/main/docs/architecture.md) ·
        [student guide](https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp/blob/main/docs/engineering-student-guide.md) ·
        [sample data set](https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp/blob/main/data/samples/README.md) ·
        [source](https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp)
        """
    )
