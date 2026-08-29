# Autonomous Acoustic Diagnostic Agent

An educational Streamlit MVP that demonstrates how acoustic signals can be turned into a machine-health decision for robotic arm bearings.

> This is a simulation for study and prototyping. It does not connect to a real sensor, production ML model, or SAP S/4HANA tenant.

## Live demo

[Open the deployed Streamlit Community Cloud app](https://lalitsonawane-acoustic-diagnostic-agent-mvp-app-5t3rdo.streamlit.app/)

## What the MVP demonstrates

- Select a machine profile: robotic arm bearings, stamping press, or conveyor drive.
- Generate a 48 kHz synthetic signal from sine waves and white noise.
- Inject short ultrasonic impulses above 20 kHz to represent a micro-crack signature.
- Upload a `.wav` sample for visualization.
- Inspect a Mel-spectrogram of the captured signal.
- Calculate a deterministic demo anomaly score from high-frequency energy.
- Cross a 75% threshold to produce an autonomous maintenance decision.
- Display reasoning-style event logs and a mock SAP S/4HANA PM work-order payload.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Then open `http://localhost:8501`.

## How to use the demo

1. Choose **Robotic Arm Bearings** in the sidebar.
2. Turn on **Inject Micro-Crack Anomaly**.
3. Click **Simulate Acoustic Data**.
4. Observe the score move above 75%, the `CRITICAL` state, and the SAP work-order payload.
5. Turn the toggle off and simulate again to compare the healthy path.
6. Optionally upload a mono or stereo `.wav` file. Uploaded audio is decoded with Librosa and rendered defensively with an error message if processing fails.

## Project map

| Path | Purpose |
| --- | --- |
| [`app.py`](app.py) | Single-file Streamlit application and demo logic |
| [`requirements.txt`](requirements.txt) | Python runtime dependencies |
| [`docs/architecture.md`](docs/architecture.md) | System design and Mermaid workflow diagrams |
| [`docs/engineering-student-guide.md`](docs/engineering-student-guide.md) | Learning path, signal-processing notes, exercises, and extension ideas |

## Application documentation

Use [`docs/application.md`](docs/application.md) as the single reference section for the application. It brings together the user workflow, code structure, signal-processing concepts, decision policy, study sequence, exercises, and production-readiness notes. The linked architecture and student-guide documents provide deeper detail.

## Validation

```bash
.venv/bin/python -m py_compile app.py
git diff --check
```

## Important MVP limitations

- `calculate_anomaly` is a dummy rule-based function, not a trained classifier.
- The micro-crack toggle supplies a deterministic score boost for repeatable teaching demos.
- RUL is a simple illustrative estimate, not a survival model or maintenance forecast.
- SAP integration is represented by JSON shown in the UI; no request is sent to SAP.
- A real system needs calibrated sensors, labeled failure data, model evaluation, authentication, audit logs, human approval, and safe maintenance controls.
