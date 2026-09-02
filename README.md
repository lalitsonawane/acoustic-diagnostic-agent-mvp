# Autonomous Acoustic Diagnostic Agent

An educational, experiment-ready Streamlit application that turns an acoustic capture into a
machine-health decision for rotating equipment (robotic arm bearings, stamping press, conveyor
drive). Version 0.2.0 replaces the original single-file demo with a tested Python package, a
baseline-calibrated detector, validity gating, configuration management and batch evaluation.

> This is a simulation for study and prototyping. It does not connect to a real sensor, a
> production ML model or an SAP S/4HANA tenant. Every synthetic fault is a physical change to
> the waveform, and every score is a measurement against a healthy baseline - except the
> clearly labelled teaching *demo boost*, which is flagged wherever it is applied.

## Live demo

[Open the deployed Streamlit Community Cloud app](https://lalitsonawane-acoustic-diagnostic-agent-mvp-app-5t3rdo.streamlit.app/)

## What it does

- **Three signal sources**: simulate a 48 kHz rotating-machine tone with optional 22 kHz
  micro-crack bursts or outer-race bearing impacts; upload a WAV/FLAC/OGG; or pick from the
  15 labelled files in the bundled sample library.
- **Honest detector**: six normalised evidence channels (Welch band contrast, time-resolved
  band contrast, band power, residual kurtosis, crest factor, envelope-spectrum prominence)
  are standardised against a healthy baseline and squashed to a 0-100 % score. The strongest
  weighted channel drives the verdict, so a bearing defect that is invisible above 20 kHz is
  still caught through the envelope spectrum.
- **Validity gating**: silence, low sample rate (diagnostic band above Nyquist), clipping and
  short captures reduce a confidence factor with plain-language warnings. A critical score
  with low confidence becomes *CRITICAL (unconfirmed)* and never proposes a work order.
- **Experiment workflow**: typed `ExperimentConfig` with YAML/JSON import/export and a config
  hash, custom baseline from your own healthy recordings, one-parameter sweeps, batch scoring
  with ROC / precision-recall metrics, a session run log and full export (CSV, JSON, NPZ, WAV,
  PNG).
- **Decision integrity**: mock SAP S/4HANA PM payload with UUID-derived ticket id, real
  timestamps, configuration hash, feature version and a simulated planner-approval gate.
- **Headless CLI** for scripted studies: `acoustic-agent analyze | batch | sweep | config | calibrate`.

## Run locally

```bash
# with uv (recommended)
uv sync --extra dev
uv run streamlit run app.py

# or with pip
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Then open `http://localhost:8501`.

### Command line

```bash
uv run acoustic-agent analyze --synthetic --inject-bursts
uv run acoustic-agent analyze data/samples/bearing_outer_race_fault_48k.wav --json
uv run acoustic-agent batch data/samples --out results.csv
uv run acoustic-agent sweep --parameter noise_std --values 0.01,0.05,0.1,0.2
uv run acoustic-agent config --export my_experiment.yaml
```

## How to use the app

1. **Source**: keep *Simulate*, choose a machine profile and turn on *Inject 22 kHz micro-crack
   bursts*. Click **Generate signal**.
2. **Monitor tab**: read the verdict banner, the score and confidence metrics, the spectrogram
   with the shaded diagnostic band, the evidence-channel chart and the step timeline. A
   confident CRITICAL verdict shows the proposed work order and an approval button.
3. Turn the toggle off and generate again to compare the healthy path; try *Inject bearing
   outer-race impacts* to see a fault that only the envelope spectrum catches.
4. **Experiment tab**: edit every parameter, import/export a configuration, calibrate a custom
   baseline from healthy recordings, run a sweep, inspect the run log.
5. **Batch tab**: score the sample library or your own labelled folder and read ROC / PR curves.
6. **Methods tab**: the full scoring rule, channel definitions and glossary.

## Project map

| Path | Purpose |
| --- | --- |
| [`app.py`](app.py) | Streamlit front-end (thin layer over the package) |
| [`acoustic_agent/`](acoustic_agent/) | UI-agnostic package: `config`, `synth`, `features`, `validate`, `detect`, `decision`, `io`, `metrics`, `pipeline`, `plots`, `cli` |
| [`tests/`](tests/) | Unit tests for every module plus Streamlit `AppTest` smoke tests |
| [`scripts/generate_sample_wavs.py`](scripts/generate_sample_wavs.py) | Deterministic generator for the labelled sample WAV test set |
| [`data/samples/`](data/samples/README.md) | 15 labelled test WAVs, `manifest.csv`, and a survey of public bearing/machine-sound datasets |
| [`pyproject.toml`](pyproject.toml) / [`uv.lock`](uv.lock) / [`requirements.txt`](requirements.txt) | Project metadata, lockfile, pinned runtime dependencies for Streamlit Cloud |
| [`.streamlit/config.toml`](.streamlit/config.toml) | Theme and server settings |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | Lint, type-check, tests, sample-set reproducibility |
| [`docs/application.md`](docs/application.md) | Single reference for workflow, code structure, method and study path |
| [`docs/architecture.md`](docs/architecture.md) | System design and Mermaid workflow diagrams |
| [`docs/engineering-student-guide.md`](docs/engineering-student-guide.md) | Learning path, signal-processing notes, exercises, and extension ideas |
| [`docs/notes/`](docs/notes/) | Markdown mirrors of the Notion session, decision and research notes |
| [`docs/notion-sync.md`](docs/notion-sync.md) | Index mapping every repo document to its Notion page |
| [`CHANGELOG.md`](CHANGELOG.md) / [`CITATION.cff`](CITATION.cff) | Release history and citation metadata |

## Validation

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy acoustic_agent app.py scripts
uv run pytest
uv run python scripts/generate_sample_wavs.py --out /tmp/samples && diff -r /tmp/samples data/samples
```

Pre-commit hooks for ruff and mypy are configured in `.pre-commit-config.yaml`
(`uv run pre-commit install`).

## Documentation policy

All documentation lives in both this repository and the Notion Project Knowledge Library and is
kept in sync. See [`docs/notion-sync.md`](docs/notion-sync.md) for the mapping and the sync procedure.

## Important limitations

- The detector is a calibrated rule-based system, not a trained classifier, and the baseline is
  synthetic unless you supply healthy recordings. Real deployments need real healthy data.
- The bundled faults are synthetic. The sample set exercises the detector's behaviour (noise,
  weak faults, aliasing, clipping, silence) but is not evidence of field performance.
- Confidence is a heuristic input-quality factor in [0, 1], not a probability.
- RUL is an illustrative estimate, not a survival model or maintenance forecast.
- SAP integration is a JSON payload shown in the UI; nothing is transmitted.
- A production system needs calibrated sensors, labelled failure data, model evaluation,
  authentication, audit logs, human approval and safe maintenance controls.

## License

This project is released under the [MIT License](LICENSE).
