# 2026-09-03 — Acoustic Diagnostic Agent — Phases 3–4 persistence and deployment (v0.3.0)

| Property | Value |
| --- | --- |
| Notion page | https://app.notion.com/p/3d089f54d2c281fcab56d6e65fa32fd6 |
| Project | Acoustic Diagnostic Agent |
| Type | Session summary |
| Status | Active |
| Session date | 2026-09-03 |
| Last reviewed | 2026-09-03 |
| Keywords | Architecture, Cursor, GitHub |
| Source / context | Cursor cloud agent implementing remaining plan phases on branch `lalit_cursor/phases-3-4-decision-deploy-b27b` of [github.com/lalitsonawane/acoustic-diagnostic-agent-mvp](https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp). |

## Outcome

Completed the Phase 3 remainder and Phase 4 from the professionalization plan. Version
**0.3.0** adds a SQLite `RunStore` (persistent runs + structured audit events), a **History**
tab with per-asset score trends and JSONL/CSV audit export, CLI `history` / `audit` /
`analyze --persist`, and deployment packaging (`Dockerfile`, `scripts/run_server.sh`,
`render.yaml`) that binds Streamlit to `0.0.0.0:$PORT` with an ephemeral-FS note.

## Key decisions

- **SQLite under `ACOUSTIC_AGENT_DATA_DIR`**, default `~/.cache/acoustic_agent/history.sqlite3`.
  Rationale: zero new runtime dependencies; same file for UI and CLI; easy to relocate onto a
  Render disk later.
- **Ephemeral hosts treat exports as durable.** Streamlit Cloud / Render free disks lose local
  writes on restart. Documented clearly; History still works within a process lifetime.
- **Approvals write both session list and `audit_events`.** Session JSON remains for the
  current tab; JSONL audit is the cross-session trail.
- **Docker runtime on Render Blueprint** (not native Python) so `libsndfile` and the exact
  entrypoint script are reproducible.

## Artifacts / links

- Branch `lalit_cursor/phases-3-4-decision-deploy-b27b` → [PR #4](https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp/pull/4) (**merged** into `main` @ `df57ff2`).
- Package: `acoustic_agent/store.py`; UI History tab; CLI `history` / `audit`.
- Deploy: `Dockerfile`, `scripts/run_server.sh`, `render.yaml`, `.dockerignore`.
- Docs: README Deploy section, `CHANGELOG.md` 0.3.0, architecture / application / student guide.
- Validation: `uv run ruff check && ruff format --check && mypy && pytest` (all green).
- Notion: https://app.notion.com/p/3d089f54d2c281fcab56d6e65fa32fd6

## Deploy decision (2026-09-03) — practical choice

| Platform | Decision | Why |
| --- | --- | --- |
| **Streamlit Community Cloud** | Primary live host | Already running; least ops; correct runtime for Streamlit |
| **Vercel** | Keep as redirect only | Git check stays green; does not run Streamlit/Docker |
| **Render / Docker** | Packaged but not activated | Ready if needed later; skip for now to avoid free-tier cold starts |

**Owner manual step (required):** in [Streamlit Community Cloud](https://share.streamlit.io/), open this app → confirm branch `main`, entry file `app.py`, Python **3.12**, then **Reboot** (or wait for the auto-deploy from the merge). Smoke-test Simulate → Generate → History → audit download.

**Verified from agent environment:** Vercel production responds with `307` to the Streamlit URL. Unauthenticated probes of the Streamlit URL returned `303` to Streamlit auth — if the public demo should be open, set the app to **Public** in Streamlit Cloud settings.

## Open follow-ups

- Owner: Streamlit Cloud reboot / public-access check (see above).
- Render left optional; activate only if a second Docker host or persistent disk is wanted.
- Trend-based *warnings* (alert when score slope crosses a threshold) still open.
- Real-data loaders (MAFAULDA / CWRU) and learned-detector ROC comparison remain backlog.
