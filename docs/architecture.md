# Architecture and workflow

## System overview

The MVP is intentionally a single Python file. Streamlit reruns the script when a widget changes, while `st.session_state` keeps the most recent audio buffer and sample rate available for the current session.

```mermaid
flowchart TD
    operator["Operator"] --> ui["Streamlit dashboard"]
    ui --> select["Machine profile"]
    ui --> source["Synthetic signal or WAV upload"]
    select --> signal["48 kHz acoustic signal"]
    source --> signal
    signal --> features["FFT high-frequency energy"]
    signal --> mel["Mel-spectrogram"]
    features --> detector["calculate_anomaly"]
    detector --> score["Anomaly score 0-100%"]
    score --> health["Health and RUL metrics"]
    score --> gate{"Score > 75%?"}
    gate -->|"No"| normal["No maintenance action"]
    gate -->|"Yes"| agent["Agentic workflow log"]
    agent --> sap["Mock SAP S/4HANA work order JSON"]
    mel --> ui
    health --> ui
    normal --> ui
    sap --> ui
```

## Event sequence

```mermaid
sequenceDiagram
    participant O as Operator
    participant S as Streamlit
    participant G as Generator or Librosa
    participant D as Dummy detector
    participant P as SAP payload builder

    O->>S: Select machine and toggle anomaly
    O->>S: Click Simulate Acoustic Data
    S->>G: Generate 48 kHz signal
    G-->>S: Audio array and sample rate
    S->>D: calculate_anomaly(audio, sample_rate, injected)
    D-->>S: Anomaly score
    S->>S: Derive health and illustrative RUL
    alt score greater than 75%
        S->>P: Build mock maintenance payload
        P-->>S: Ticket ID, part, window, priority
        S-->>O: Critical state, logs, and JSON
    else score at or below 75%
        S-->>O: Healthy or warning state and no-action message
    end
```

## Signal path

The simulator uses a 48 kHz sample rate because the Nyquist frequency is 24 kHz. That makes a synthetic component above 20 kHz representable:

\[
f_{Nyquist} = \frac{f_s}{2} = \frac{48,000}{2} = 24,000\text{ Hz}
\]

The generated signal is:

\[
x(t) = 0.20\sin(2\pi f t) + 0.08\sin(2\pi 3ft) + n(t) + a(t)
\]

where `n(t)` is white noise and `a(t)` is a sequence of short, damped 22 kHz bursts when anomaly injection is enabled.

## Decision logic

`calculate_anomaly` computes an FFT, averages spectral magnitude above 20 kHz, and adds a deterministic demo boost when the toggle is active. The score is clipped to 0–100%.

| Score | State | Agent behavior |
| ---: | --- | --- |
| 0–40% | Healthy | No maintenance action |
| >40–75% | Warning | Continue monitoring |
| >75% | Critical | Show simulated autonomous SAP workflow |

## Production evolution

```mermaid
flowchart LR
    sensor["Industrial acoustic sensor"] --> edge["Edge capture and filtering"]
    edge --> feature["Windowing, FFT, Mel features"]
    feature --> model["Validated anomaly model"]
    model --> policy["Risk policy and confidence gate"]
    policy --> human["Planner approval"]
    human --> api["SAP S/4HANA PM API"]
    api --> audit["Audit trail and feedback labels"]
    audit -.-> model
```
