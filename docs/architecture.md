# Architecture and workflow

## System overview

The application is a UI-agnostic Python package (`acoustic_agent`) with two thin front-ends: the
Streamlit dashboard (`app.py`) and the `acoustic-agent` CLI. Streamlit reruns the script when a
widget changes; one canonical `st.session_state.cfg` dictionary holds the experiment
configuration so that values survive widgets being unmounted (for example when switching the
signal source), and `st.cache_data` memoises baseline calibration, feature extraction, plots and
sample decoding on `(config_hash, signal)`.

```mermaid
flowchart TD
    operator["Operator / student"] --> ui["Streamlit dashboard"]
    script["Scripted study"] --> cli["acoustic-agent CLI"]
    ui --> cfg["ExperimentConfig\n(YAML / JSON, hash)"]
    cli --> cfg
    ui --> src["Signal source\nsimulate | upload | sample library"]
    cli --> src
    cfg --> pipe["pipeline.analyze"]
    src --> pipe
    subgraph acoustic_agent
        pipe --> feat["features\nWelch PSD, band contrast (avg + transient),\nresidual kurtosis / crest, envelope spectrum"]
        pipe --> val["validate\nsilence, Nyquist, clipping, length"]
        base["detect.calibrate_baseline\n8 healthy renders or user recordings"] --> det
        feat --> det["detect.score_features\nz per channel, floors, weighted max, logistic"]
        val --> dec
        det --> dec["decision.decide\nstate, explanation, RUL, action"]
    end
    dec --> result["AnalysisResult\n+ timestamped steps"]
    result --> plots["plots (PNG)"]
    result --> log["run log / exports\nCSV · JSON · NPZ · WAV"]
    result --> gate{"CRITICAL and\nconfidence >= 0.6?"}
    gate -->|"Yes"| wo["Mock SAP S/4HANA PM payload\n+ planner approval gate"]
    gate -->|"No"| none["Monitor / re-capture"]
```

## Event sequence

```mermaid
sequenceDiagram
    participant O as Operator
    participant S as Streamlit (app.py)
    participant C as st.cache_data
    participant P as pipeline.analyze
    participant D as detect / decision

    O->>S: Toggle fault, click Generate signal
    S->>S: cfg -> ExperimentConfig (validated, hashed)
    S->>C: baseline(config_hash)
    C-->>S: Baseline (cached after first call)
    S->>P: analyze(signal, config, baseline)
    P->>D: extract_features -> assess_validity -> score_features -> decide
    D-->>P: Detection, Validity, Decision
    P-->>S: AnalysisResult with real step timestamps
    S->>S: append run-log row (source, config_hash, feature_version)
    alt CRITICAL and confidence >= min_confidence
        S-->>O: Banner, evidence chart, work order, approval button
    else
        S-->>O: Banner, evidence chart, warnings
    end
```

## Signal path

The simulator uses a 48 kHz sample rate because the Nyquist frequency is 24 kHz, which makes a
component above 20 kHz representable:

\[
f_{Nyquist} = \frac{f_s}{2} = \frac{48\,000}{2} = 24\,000\ \text{Hz}
\]

The synthetic signal is

\[
x(t) = A\sin(2\pi f t) + 0.4A\sin(2\pi\,3f t) + n(t) + b(t) + i(t)
\]

where `n(t)` is white noise, `b(t)` is an optional train of short damped 22 kHz bursts
(micro-crack signature) and `i(t)` is an optional train of impacts at the ball-pass frequency of
the outer race (BPFO ≈ 107 Hz) that ring a 5.2 kHz structural resonance (bearing defect). The
two fault models are deliberately different: the first is visible above 20 kHz, the second only
in the impulsiveness of the residual and the envelope spectrum.

## Detection and decision logic

```text
z_c   = max(0, (x_c - mean_c) / max(std_c, floor_c))     per channel c
z     = max_c  w_c * z_c                                 strongest weighted channel
score = 100 / (1 + exp(-(z - z_center) / z_scale))       defaults: 3, 1
```

| Score | Confidence | State | Agent behaviour |
| ---: | --- | --- | --- |
| any | invalid input | `INVALID` | Check sensor / capture chain, no verdict |
| 0-40 % | – | `HEALTHY` | No maintenance action |
| >40-75 % | – | `WARNING` | Increase monitoring frequency |
| >75 % | ≥ 0.6 | `CRITICAL` | Propose P1 work order for planner approval |
| >75 % | < 0.6 | `CRITICAL (unconfirmed)` | Re-capture with valid rate / gain first |

Every result row and work-order payload carries the configuration hash and the
`FEATURE_VERSION` string so stored outputs remain comparable after the feature set changes.

## Quality gates

| Gate | Tool |
| --- | --- |
| Formatting and lint | `ruff format`, `ruff check` (pre-commit + CI) |
| Static types | `mypy --strict`-leaning configuration over `acoustic_agent`, `app.py`, `scripts` |
| Unit tests | `pytest` over every module, including gain-invariance, false-alarm and regression cases |
| UI smoke tests | Streamlit `AppTest` driving the sidebar and verifying the run log |
| Reproducibility | `scripts/generate_sample_wavs.py` must reproduce `data/samples` byte-for-byte |
| Dependencies | `uv.lock` for development, pinned `requirements.txt` for Streamlit Community Cloud |

## Production evolution

```mermaid
flowchart LR
    sensor["Industrial acoustic sensor"] --> edge["Edge capture and filtering"]
    edge --> feature["Windowing, Welch PSD, envelope features"]
    feature --> model["Validated detector\n(asset-specific healthy baseline)"]
    model --> policy["Risk policy and confidence gate"]
    policy --> human["Planner approval"]
    human --> api["SAP S/4HANA PM API"]
    api --> audit["Audit trail and feedback labels"]
    audit -.-> model
```
