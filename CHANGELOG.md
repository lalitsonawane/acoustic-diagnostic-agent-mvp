# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-09-02

Professionalisation and experiment-readiness release (plan phases 0-2 plus the UI upgrade).

### Added
- `acoustic_agent` package: `config`, `synth`, `features`, `validate`, `detect`, `decision`,
  `io`, `metrics`, `pipeline`, `plots`, `cli`. The Streamlit app is now a thin front-end.
- Honest detector: Welch band-power and band-contrast (dB), time-resolved band contrast
  (98th percentile minus median across ~20 ms STFT frames, which catches short bursts under
  heavy broadband noise that whole-capture averaging dilutes), residual kurtosis and crest
  factor, Hilbert envelope-spectrum prominence; baseline-calibrated z-scores with std floors;
  logistic 0-100 score driven by the strongest weighted channel. The old fixed +76 demo
  offset is gone from the scored path. On the shipped sample set the detector ranks all
  labelled files perfectly (ROC AUC 1.0) with zero false alarms at the default threshold.
- Validity gating with a confidence factor and plain-language warnings (silence, low sample
  rate / band above Nyquist, clipping, short capture). Critical verdicts below the minimum
  confidence are reported as *CRITICAL (unconfirmed)* and do not propose a work order.
- Typed `ExperimentConfig` with YAML/JSON import/export and a short configuration hash.
- Guided sidebar (Source -> Configure -> Analyse) with Simulate / Upload / Sample-library
  sources; tabs Monitor / Experiment / Batch / Methods; verdict banner with confidence badge;
  native `st.metric` cards; `st.status` steps with real timestamps; export expander
  (run-log CSV, result JSON, NPZ, WAV, PNG plots, approval audit log).
- Linear spectrogram with shaded diagnostic band, PSD-vs-baseline overlay, envelope spectrum,
  waveform with detected impulses, per-channel evidence chart.
- Session run log, custom baseline from user-supplied healthy recordings, parameter sweeps,
  batch evaluation with ROC / precision-recall metrics (NumPy implementation).
- Headless CLI `acoustic-agent` (`analyze`, `batch`, `sweep`, `config`, `calibrate`).
- Mock work order now carries a UUID-derived ticket id, real timestamps, configuration hash,
  feature version and a simulated planner-approval gate.
- Engineering baseline: `pyproject.toml`, `uv.lock`, pinned `requirements.txt`, ruff, mypy,
  pytest (unit + `AppTest` smoke tests), pre-commit, GitHub Actions CI, `.streamlit/config.toml`
  theme, `CITATION.cff`, this changelog.

### Changed
- `scripts/generate_sample_wavs.py` imports its signal primitives from `acoustic_agent.synth`;
  output remains byte-identical to the committed `data/samples` set (verified in CI).
- Mel-spectrogram replaced by a linear STFT spectrogram so the 20-24 kHz band is not compressed.
- Dev container uses Python 3.12 (required by the pinned NumPy / SciPy).
- `librosa` dependency dropped in favour of `soundfile` + `scipy`.

### Removed
- Hard-coded log timestamps, fixed ticket id and the `unsafe_allow_html` CSS theme.

## [0.1.0] - 2026-08-29

- Initial single-file Streamlit MVP with synthetic signal, Mel-spectrogram, demo score and
  mock SAP payload; documentation set; MIT license; labelled synthetic sample WAV set (#1).
