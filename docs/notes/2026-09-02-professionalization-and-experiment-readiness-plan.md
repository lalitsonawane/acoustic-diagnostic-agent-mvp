# 2026-09-02 — Acoustic Diagnostic Agent — Professionalization & experiment-readiness plan

| Property | Value |
| --- | --- |
| Notion page | https://app.notion.com/p/3cf89f54d2c2816aa963e41e353e8fa5 |
| Project | Acoustic Diagnostic Agent |
| Type | Research |
| Status | Active |
| Session date | 2026-09-02 |
| Last reviewed | 2026-09-02 |
| Keywords | Architecture, GitHub, Cursor |
| Source / context | Cursor cloud agent review of [github.com/lalitsonawane/acoustic-diagnostic-agent-mvp](https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp) (main @ 4797d2e). Recommendation only; no code changed pending approval. |

## Outcome

Reviewed the single-file Streamlit MVP (`app.py`, ~265 lines, no tests/CI) and produced a phased plan to make it professional and usable for scientific experiments. Awaiting owner approval before implementing.

## Key findings

- Anomaly score is not a function of the signal: `calculate_anomaly` adds a fixed +76 when the toggle is on. Unusable for experiments as-is.
- Feature (mean rFFT magnitude > 20 kHz) is un-normalized; depends on amplitude and recording length, so scores are not comparable across files.
- Mel-spectrogram compresses the 20–24 kHz diagnostic band; a linear STFT/PSD view is more appropriate.
- No parameterization (seed 42, duration, SNR, burst frequency, thresholds all hard-coded), no export, no batch mode, no run log → no reproducibility.
- No `st.cache_data`; spectrogram recomputed on every widget interaction.
- No input validation for uploads (sample rate < 40 kHz silently yields an empty band and a constant score).
- Repo hygiene gaps: unpinned deps, no lockfile, no pyproject, no lint/type/test tooling, no CI, hard-coded log timestamps and ticket id, theme via ~30 lines of `unsafe_allow_html` CSS.

## Recommended plan (phased)

1. **Phase 0 — Engineering baseline**: package layout (`acoustic_agent/` with synth, features, detect, decision, io, ui), `pyproject.toml` + lockfile, ruff/mypy/pytest/pre-commit, GitHub Actions CI, `.streamlit/config.toml` theme, `st.testing.AppTest` smoke tests, CHANGELOG, CITATION.cff.
2. **Phase 1 — Honest detector**: remove the demo boost; Welch PSD band-power ratio in dB, kurtosis/crest factor, envelope spectrum; baseline-calibrated z-score → logistic 0–100; validity gating (fs, duration, clipping, silence) with a confidence value; linear spectrogram + PSD plot with band shading.
3. **Phase 2 — Experiment efficiency**: typed `ExperimentConfig` with YAML/JSON import/export; `st.cache_data`/`st.fragment`; session run log with CSV/Parquet/NPZ/PNG downloads; batch upload with manifest labels and ROC/PR metrics; parameter sweeps; headless CLI sharing the same core.
4. **Phase 3 — Decision integrity**: real timestamps, UUID work-order ids, config hash + feature version in payload, human-approval gate, audit log export.
5. **Phase 4 — Deployment**: pinned deps, upload size/duration limits, optional Dockerfile/render.yaml (bind 0.0.0.0:$PORT; ephemeral FS → downloads only).

## Key decisions (pending)

- Owner to choose scope: minimal (Phase 0+1), recommended (0–2), or full (0–4).
- Proposed: keep Streamlit; keep matplotlib by default, Plotly optional; keep the teaching mode as a separate, clearly-labelled "demo boost" toggle rather than in the scored path.

## Artifacts / links

- Repo: https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp
- Live demo: https://lalitsonawane-acoustic-diagnostic-agent-mvp-app-5t3rdo.streamlit.app/

## Open follow-ups

- Await approval and chosen scope; then implement as a sequence of small PRs (one per phase or sub-step).
- Confirm whether real recorded WAV datasets exist to calibrate the baseline detector.

---

## Update 2026-09-02 (later session) — test data and UI plan

### Decision: synthetic, committed test set; real datasets stay external

- Owner has no recorded WAVs. Public candidates surveyed: MAFAULDA (UFRJ, mic + accelerometers, 50 kHz, CSV, **no upstream licence** → research use only, do not redistribute; SM81 mic rolls off at 20 kHz), ToyADMOS2 (48 kHz WAV, NTT evaluation licence; DCASE subsets CC BY-NC-SA 4.0), DCASE Task 2 (16 kHz), CWRU (48 kHz vibration .mat, no stated licence, not redistributable), Paderborn KAt (64 kHz .mat, CC BY-NC 4.0).
- Therefore committed a deterministic synthetic set instead: [PR #1](https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp/pull/1) — `scripts/generate_sample_wavs.py` + `data/samples/` (15 WAVs, 2.9 MB, `manifest.csv`, README with dataset survey).
- Set covers healthy/fault pairs for 3 profiles, weak/noisy detection-floor cases, validation cases (stereo, clipped, 16 kHz, silence) and a physically motivated outer-race fault (BPFO 107.4 Hz impacts ringing 5.2 kHz).

### Measured finding (quantifies the detector problem)

- Current `calculate_anomaly` (boost off) returns **29.0 for every 48 kHz upload**, healthy or faulty — un-normalised FFT magnitude saturates the +22 cap. 16 kHz file silently returns 7.0.
- Normalised 20–24 kHz band-power ratio separates healthy (−26 dB) from fault (−17 dB); fails on noisy pairs and on silence (−7.7 dB) as expected → confidence gating needed.
- Bearing-impact file is invisible to the >20 kHz band (−22 dB, same as healthy) but envelope peak = 105 Hz vs BPFO 107.4 Hz → envelope analysis required for real bearing faults.

### UI upgrade recommendation (added to Phase 1/2)

1. Guided 3-step sidebar: Source (Simulate / Upload / Sample library from `data/samples`) → Configure → Analyse.
2. Tabs: Monitor (simple default), Experiment (parameters, sweeps, run log), Batch (multi-file + ROC), Methods (docs).
3. Single verdict banner with plain-language explanation + confidence badge; inline validity warnings (e.g. sample rate too low).
4. Plots: linear spectrogram with diagnostic band shaded, PSD current-vs-baseline overlay, waveform with detected impulses; Plotly optional.
5. Native `st.metric` with deltas and `help=` tooltips; replace fake terminal timestamps with `st.status` steps using real timestamps; rename "Agentic response" → "Recommended action".
6. Theme via `.streamlit/config.toml`, minimal custom CSS, colour + icon + text for states (accessibility).
7. `st.cache_data` / `st.fragment` for instant interaction; grouped Export expander (CSV/NPZ/PNG/JSON config).
8. First-run hint pointing to the sample library; glossary expander.

### Open follow-ups

- Owner to review/merge PR #1 and approve scope for Phases 0–2 + UI upgrade.
- Follow-up idea: `.mat`/CSV → WAV converter and MAFAULDA loader so real recordings can be scored.

---

## Decision 2026-09-02 — Vercel check on PR #1

- **Root cause:** repo is linked to Vercel project `apptonics-projects/acoustic-diagnostic-agent-mvp` (auto-imported, framework preset `python`). Vercel's Python runtime requires `app.py` to export `app`/`application`/`handler`; Streamlit does not, so every deployment failed with `PYTHON_ENTRYPOINT_NOT_FOUND` — including `main` (4797d2e). Not caused by the PR; Streamlit cannot run as a Vercel function.
- **Fix (commit 32a89c9):** `vercel.json` with `framework: null`, `installCommand: ""`, `outputDirectory: public`, and a redirect of `/(.*)` to the Streamlit Community Cloud URL; `public/index.html` as fallback. Deployment READY; preview returns 307 to the Streamlit app; GitHub checks green.
- **Rationale:** keeps the Vercel URL useful rather than just silencing the check. Alternative if Vercel is unwanted: `{"git": {"deploymentEnabled": false}}` or disconnect the project.
- Note: preview deployments are behind Vercel deployment protection (SSO); production alias will be public once merged.
