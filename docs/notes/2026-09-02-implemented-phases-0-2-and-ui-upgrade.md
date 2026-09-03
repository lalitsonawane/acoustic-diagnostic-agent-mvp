# 2026-09-02 — Acoustic Diagnostic Agent — Implemented phases 0-2 and UI upgrade (v0.2.0)

| Property | Value |
| --- | --- |
| Notion page | https://app.notion.com/p/3cf89f54d2c281e58f18da600049ca14 |
| Project | Acoustic Diagnostic Agent |
| Type | Session summary |
| Status | Active |
| Session date | 2026-09-02 |
| Last reviewed | 2026-09-03 |
| Keywords | Streamlit, Signal processing, Testing, CI, Cursor |
| Source / context | Cursor agent session implementing the [professionalization plan](2026-09-02-professionalization-and-experiment-readiness-plan.md) on branch `feat/professionalize-phases-0-2` of [github.com/lalitsonawane/acoustic-diagnostic-agent-mvp](https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp). |

## Outcome

The single-file MVP became a tested package (`acoustic_agent`, 11 modules, 96 % line coverage,
86 tests including Streamlit `AppTest` smoke tests) with a thin Streamlit front-end and a headless
CLI. Phases 0, 1 and 2 of the plan and the UI upgrade are complete; the decision-integrity items
from Phase 3 that were cheap to include (UUID ticket, real timestamps, config hash, feature
version, approval gate) are also in. Version bumped to 0.2.0; `CHANGELOG.md` is the release
record.

On the shipped 15-file sample set the detector reaches ROC AUC 1.000 with precision 1.00 and
recall 1.00 at the default 75 % threshold; edge cases behave as designed (clipping lowers
confidence, 16 kHz is *unconfirmed*, silence is *INVALID*).

## Key decisions

- **Strongest weighted channel drives the verdict** (max, not sum). Rationale: a bearing defect
  with zero ultrasonic energy must still alarm, and the explanation can name one concrete cause.
- **`band_power_db` computed but weight 0.** Rationale: it is ~20σ high on any noisy-but-healthy
  recording. It stays visible for teaching; the Methods tab says why.
- **Std floors per channel.** Rationale: eight near-identical synthetic renders give a raw
  standard deviation of ~0.01, which would turn trivial deviations into 100σ. Floors encode the
  smallest physically plausible spread per unit.
- **Added `band_contrast_transient_db` (98th percentile − median of per-frame band contrast).**
  Rationale: found during testing – `robotic_arm_fault_noisy_48k.wav` scored HEALTHY (36.7)
  because 2 s Welch averaging dilutes 12 ms bursts under 16 dB more noise, while the averaged
  contrast differed from the noisy-healthy file by only 0.5 dB. The per-frame spread separates
  them by 5.5 dB and is ~1.2–1.6 dB for stationary noise of any level. `FEATURE_VERSION` bumped
  to `features-v3-welch-transient-envelope`.
- **Canonical `st.session_state.cfg` dict, widgets seeded from it with `on_change` sync.**
  Rationale: Streamlit drops widget keys when a widget is not rendered (e.g. switching source
  mode), which silently reset parameters. Covered by `test_widget_values_survive_mode_switch`.
- **Python ≥ 3.12.** Rationale: pinned NumPy 2.5 / SciPy 1.18 require it; dev container updated.
- **`librosa` dropped for `soundfile` + `scipy`.** Rationale: smaller install, no numba, linear
  spectrogram is what the diagnostic band needs.
- **Weak-burst sample may legitimately be WARNING.** The batch test allows WARNING or CRITICAL
  for `robotic_arm_fault_weak_48k` because it exists to sit near the detection floor. (With the
  transient channel it is currently CRITICAL at 99.7.)

## Artifacts / links

- Branch `feat/professionalize-phases-0-2` → PR on GitHub (see repo).
- `acoustic_agent/` package, `tests/`, `pyproject.toml`, `uv.lock`, `requirements.txt`,
  `.github/workflows/ci.yml`, `.pre-commit-config.yaml`, `.streamlit/config.toml`,
  `CHANGELOG.md`, `CITATION.cff`.
- Updated docs: `README.md`, `docs/application.md`, `docs/architecture.md`,
  `docs/engineering-student-guide.md`, `data/samples/README.md` (new reference-value table).
- Validation: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`;
  sample set byte-identical to `scripts/generate_sample_wavs.py` output.

## Open follow-ups

- ~~Phase 3 remainder: persistent run history / trends / audit export.~~ Done in v0.3.0 — see [2026-09-03 phases 3–4 note](2026-09-03-phases-3-4-persistence-and-deployment.md).
- ~~Phase 4: deployment packaging (Docker / Render / `0.0.0.0:$PORT`).~~ Done in v0.3.0; Streamlit Cloud redeploy from `main` still pending after merge.
- Real-data loaders (MAFAULDA CSV, CWRU `.mat`) so the Batch tab can score public datasets.
- Consider a learned detector on the same feature vector for an ROC comparison.
- ~~Merge PR #2 after CI is green.~~ Merged.

Notion mirrors of the five changed docs (README, application, architecture, student guide,
samples README) were refreshed in this session and the plan page carries an "Implemented" banner.
