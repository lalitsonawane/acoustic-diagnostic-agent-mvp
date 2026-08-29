"""Autonomous Acoustic Diagnostic Agent - Streamlit MVP."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import librosa
import librosa.display
import matplotlib.pyplot as plt
import numpy as np
import streamlit as st


st.set_page_config(
    page_title="Acoustic Diagnostic Agent",
    page_icon="◌",
    layout="wide",
    initial_sidebar_state="expanded",
)


MACHINE_PROFILES: dict[str, dict[str, Any]] = {
    "Robotic Arm Bearings": {
        "part": "RB-6204-2RS",
        "base_frequency": 440.0,
        "rul": 86,
        "accent": "Bearing race / micro-crack",
    },
    "Stamping Press": {
        "part": "SP-ROLLER-18",
        "base_frequency": 220.0,
        "rul": 142,
        "accent": "Drive train resonance",
    },
    "Conveyor Drive": {
        "part": "CV-MOTOR-07",
        "base_frequency": 330.0,
        "rul": 119,
        "accent": "Motor / gearbox harmonic",
    },
}


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Space+Grotesk:wght@400;500;600;700&display=swap');
        :root { --ink:#e8f0f2; --muted:#829397; --line:#253538; --panel:#10191b; --cyan:#62f4d6; --amber:#ffbd68; }
        .stApp { background:#081012; color:var(--ink); font-family:'Space Grotesk', sans-serif; }
        [data-testid="stSidebar"] { background:#0b1517; border-right:1px solid var(--line); }
        [data-testid="stSidebar"] > div:first-child { padding-top:2.2rem; }
        h1,h2,h3,p,span,label { font-family:'Space Grotesk',sans-serif; }
        h1 { font-size:clamp(2rem, 4vw, 4rem)!important; letter-spacing:-.06em; line-height:.95!important; margin-bottom:.8rem!important; }
        h2 { letter-spacing:-.04em; }
        .eyebrow { color:var(--cyan); font:500 .72rem 'DM Mono', monospace; letter-spacing:.16em; text-transform:uppercase; }
        .subtle { color:var(--muted); font-size:.92rem; }
        .metric { border-top:1px solid var(--line); padding:1rem 0 1.2rem; }
        .metric-label { color:var(--muted); font:500 .68rem 'DM Mono', monospace; letter-spacing:.11em; text-transform:uppercase; }
        .metric-value { color:var(--ink); font-size:2rem; font-weight:600; letter-spacing:-.05em; margin-top:.25rem; }
        .metric-value.cyan { color:var(--cyan); }
        .metric-value.amber { color:var(--amber); }
        .signal-line { height:1px; background:linear-gradient(90deg, var(--cyan), transparent); margin:1.4rem 0 2rem; opacity:.7; }
        .section-rule { border-top:1px solid var(--line); padding-top:1rem; margin-top:2rem; }
        .terminal { background:#071011; border:1px solid var(--line); padding:1rem 1.1rem; min-height:190px; font:400 .78rem/1.8 'DM Mono',monospace; color:#a8babc; }
        .terminal .ok { color:var(--cyan); } .terminal .warn { color:var(--amber); }
        .sap-json { background:#0c1719; border-left:2px solid var(--cyan); padding:1rem; }
        .tag { display:inline-block; padding:.25rem .55rem; border:1px solid var(--line); color:var(--muted); font:500 .65rem 'DM Mono',monospace; text-transform:uppercase; letter-spacing:.08em; }
        div.stButton > button { border:1px solid var(--cyan); background:var(--cyan); color:#071011; border-radius:2px; font-weight:700; min-height:2.7rem; }
        div.stButton > button:hover { background:#a0ffe9; border-color:#a0ffe9; color:#071011; }
        .stProgress > div > div > div > div { background:var(--cyan); }
        [data-testid="stFileUploader"] { border:1px dashed var(--line); padding:.25rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def generate_acoustic_data(profile: dict[str, Any], inject_anomaly: bool, duration: float = 2.0) -> tuple[np.ndarray, int]:
    """Generate a 48 kHz signal so injected content can exist above 20 kHz."""
    sample_rate = 48_000
    time = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    rng = np.random.default_rng(42)
    carrier = 0.20 * np.sin(2 * np.pi * profile["base_frequency"] * time)
    harmonic = 0.08 * np.sin(2 * np.pi * profile["base_frequency"] * 3 * time)
    signal = carrier + harmonic + rng.normal(0, 0.018, time.shape)
    if inject_anomaly:
        # Short ultrasonic bursts simulate impulsive energy from a damaged race.
        for start in np.arange(0.25, duration, 0.37):
            index = int(start * sample_rate)
            burst_time = np.arange(min(int(.012 * sample_rate), len(signal) - index)) / sample_rate
            envelope = np.exp(-burst_time * 260)
            signal[index : index + len(burst_time)] += 0.42 * envelope * np.sin(2 * np.pi * 22_000 * burst_time)
    return np.clip(signal, -1, 1).astype(np.float32), sample_rate


def calculate_anomaly(audio_data: np.ndarray, sample_rate: int, injected: bool = False) -> float:
    """Dummy detector: score high-frequency energy plus a deterministic demo boost."""
    if audio_data.size == 0:
        return 0.0
    spectrum = np.abs(np.fft.rfft(audio_data))
    frequencies = np.fft.rfftfreq(audio_data.size, 1 / sample_rate)
    high_band = spectrum[frequencies > 20_000].mean() if np.any(frequencies > 20_000) else 0.0
    score = 7.0 + min(float(high_band) * 5.0, 22.0)
    if injected:
        score += 76.0
    return float(np.clip(score, 0, 100))


def health_for(score: float) -> tuple[str, str]:
    if score > 75:
        return "CRITICAL", "amber"
    if score > 40:
        return "WARNING", "amber"
    return "HEALTHY", "cyan"


def render_spectrogram(audio: np.ndarray, sample_rate: int) -> None:
    try:
        mel = librosa.feature.melspectrogram(y=audio, sr=sample_rate, n_mels=96, fmax=sample_rate // 2)
        db = librosa.power_to_db(mel, ref=np.max)
        fig, ax = plt.subplots(figsize=(12, 4.4), facecolor="#10191b")
        ax.set_facecolor("#10191b")
        image = librosa.display.specshow(db, sr=sample_rate, x_axis="time", y_axis="mel", fmax=sample_rate // 2, cmap="magma", ax=ax)
        ax.set_title("MEL-SPECTROGRAM / 0—24 KHZ", color="#e8f0f2", loc="left", fontsize=10, pad=12, fontfamily="DejaVu Sans")
        ax.tick_params(colors="#829397", labelsize=8)
        for spine in ax.spines.values(): spine.set_color("#253538")
        fig.colorbar(image, ax=ax, pad=.012, fraction=.02).ax.tick_params(colors="#829397", labelsize=7)
        fig.tight_layout()
        st.pyplot(fig, use_container_width=True)
        plt.close(fig)
    except Exception as exc:  # pragma: no cover - defensive UI boundary
        st.error(f"Unable to render acoustic visualization: {exc}")


def sap_payload(profile: dict[str, Any], score: float) -> dict[str, str]:
    return {
        "ticket_id": f"WO-{datetime.now():%Y%m%d}-0842",
        "material_part_number": profile["part"],
        "suggested_window": (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d 22:00–23:30 IST"),
        "priority": "P1 - Immediate maintenance",
        "anomaly_score": f"{score:.1f}%",
        "system": "SAP S/4HANA PM",
    }


inject_styles()

with st.sidebar:
    st.markdown('<div class="eyebrow">ACOUSTIC / OPS 01</div>', unsafe_allow_html=True)
    st.markdown("### Diagnostic scope")
    machine = st.selectbox("Machine", list(MACHINE_PROFILES), label_visibility="collapsed")
    profile = MACHINE_PROFILES[machine]
    st.markdown(f'<span class="tag">{profile["accent"]}</span>', unsafe_allow_html=True)
    st.markdown("\n")
    inject_anomaly = st.toggle("Inject Micro-Crack Anomaly", value=False, help="Adds ultrasonic impulses above 20 kHz.")
    uploaded = st.file_uploader("Upload acoustic sample", type=["wav"])
    simulate = st.button("Simulate Acoustic Data", use_container_width=True)
    st.markdown('<div class="subtle" style="margin-top:2rem">Demo environment · sensor stream nominal</div>', unsafe_allow_html=True)

if "audio" not in st.session_state:
    st.session_state.audio, st.session_state.sample_rate = generate_acoustic_data(profile, False)
if simulate:
    st.session_state.audio, st.session_state.sample_rate = generate_acoustic_data(profile, inject_anomaly)
if uploaded is not None:
    try:
        st.session_state.audio, st.session_state.sample_rate = librosa.load(uploaded, sr=None, mono=True)
        st.toast("WAV sample loaded", icon="✓")
    except Exception as exc:
        st.error(f"Could not process this WAV file: {exc}")

audio = st.session_state.audio
sample_rate = st.session_state.sample_rate
score = calculate_anomaly(audio, sample_rate, inject_anomaly and uploaded is None)
health, health_color = health_for(score)
rul = max(3, int(profile["rul"] * (1 - score / 125)))

st.markdown('<div class="eyebrow">LIVE CONDITION MONITORING · SAP CONNECTED</div>', unsafe_allow_html=True)
st.title("Autonomous Acoustic\nDiagnostic Agent")
st.markdown('<div class="subtle">Listen for what the machine cannot report. High-frequency vibration patterns are converted into a maintenance decision.</div>', unsafe_allow_html=True)
st.markdown('<div class="signal-line"></div>', unsafe_allow_html=True)

metric_cols = st.columns(3)
metrics = [("Machine health status", health, health_color), ("Anomaly score", f"{score:.1f}%", "amber" if score > 40 else "cyan"), ("Estimated RUL", f"{rul} days", "cyan")]
for col, (label, value, color) in zip(metric_cols, metrics):
    with col:
        st.markdown(f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value {color}">{value}</div></div>', unsafe_allow_html=True)

st.markdown('<div class="section-rule"></div>', unsafe_allow_html=True)
viz_col, action_col = st.columns([1.55, 1], gap="large")
with viz_col:
    st.markdown('<div class="eyebrow">01 / SIGNAL ANALYSIS</div>', unsafe_allow_html=True)
    st.subheader("Acoustic fingerprint")
    st.caption(f"{machine} · {sample_rate / 1000:.1f} kHz sample rate · {len(audio) / sample_rate:.2f}s capture")
    render_spectrogram(audio, sample_rate)
with action_col:
    st.markdown('<div class="eyebrow">02 / AGENTIC RESPONSE</div>', unsafe_allow_html=True)
    st.subheader("Maintenance decision")
    if score > 75:
        logs = [
            ("ok", "[01:14:02] Signal received from edge sensor"),
            ("ok", "[01:14:03] Ultrasonic band isolated: 20—24 kHz"),
            ("warn", f"[01:14:03] Micro-crack signature confirmed · {score:.1f}%"),
            ("ok", "[01:14:04] Risk threshold exceeded (>75%)"),
            ("ok", "[01:14:04] Creating SAP S/4HANA maintenance request..."),
            ("ok", "[01:14:05] Work order queued for planner approval"),
        ]
        terminal = "\n".join(f'<div class="{tone}">{line}</div>' for tone, line in logs)
        st.markdown(f'<div class="terminal">{terminal}</div>', unsafe_allow_html=True)
        st.markdown("\n")
        st.markdown("**SAP S/4HANA work order**")
        st.json(sap_payload(profile, score), expanded=True)
    else:
        st.markdown('<div class="terminal"><div class="ok">[01:14:02] Signal received from edge sensor</div><div>[01:14:03] No abnormal ultrasonic energy detected</div><div>[01:14:04] Asset remains within operating envelope</div><div class="ok">[01:14:04] No maintenance action required</div></div>', unsafe_allow_html=True)
        st.markdown("\n")
        st.info("Autonomous workflow arms when the anomaly score exceeds 75%.")

st.markdown('<div class="section-rule"></div>', unsafe_allow_html=True)
st.markdown('<div class="eyebrow">03 / APPLICATION REFERENCE</div>', unsafe_allow_html=True)
st.subheader("Learn how the diagnostic loop works")
st.caption("Use this section as a compact study reference while experimenting with the live dashboard.")
with st.expander("Open application guide", expanded=False):
    st.markdown(
        """
        ### Application purpose

        This MVP demonstrates how an acoustic signal can become a machine-health decision. It is an educational simulation: the detector is rule-based, the RUL is illustrative, and the SAP S/4HANA work order is mock JSON rather than a real API request.

        ### Signal-processing concepts

        - The simulator uses a **48 kHz** sample rate, giving a **24 kHz Nyquist frequency**.
        - A base sine wave and third harmonic approximate rotating-machine sound.
        - White noise approximates measurement and environmental noise.
        - The anomaly toggle adds damped **22 kHz** bursts above the 20 kHz diagnostic band.
        - Librosa renders a Mel-spectrogram so energy can be inspected across time and frequency.
        - The dummy detector uses the mean FFT magnitude above 20 kHz and a deterministic demo boost.

        ### Study workflow

        1. Run the healthy path with anomaly injection off.
        2. Run the fault path with injection on.
        3. Compare the score, health state, RUL, and spectrogram.
        4. Change a machine base frequency and explain the visual difference.
        5. Replace the demo boost with measured features and add confidence scoring.
        6. Add human approval before any real maintenance action.

        ### Engineering questions

        - Why would a 16 kHz recording be unsuitable for studying a 22 kHz fault?
        - Why does a spectrogram reveal intermittent events better than an average spectrum?
        - What false-positive and false-negative costs exist in predictive maintenance?
        - Which metadata should be stored with a real model decision?
        - Why must a production SAP request be authenticated, auditable, and verified?

        ### Full references

        - [Central application documentation](https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp/blob/main/docs/application.md)
        - [Architecture and Mermaid workflows](https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp/blob/main/docs/architecture.md)
        - [Engineering student study guide](https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp/blob/main/docs/engineering-student-guide.md)
        - [Source code on GitHub](https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp/blob/main/app.py)

        > Production note: never treat the demo score or mock SAP payload as a certified diagnosis or proof that a work order exists.
        """
    )
