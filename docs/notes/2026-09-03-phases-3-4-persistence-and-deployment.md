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
| Source / context | Cursor cloud agent Plan B Render free deploy; docs on branch `lalit_cursor/render-free-deploy-docs-b27b` of [github.com/lalitsonawane/acoustic-diagnostic-agent-mvp](https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp). |

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

## Deploy decision (2026-09-03) — practical choice (superseded for public demo)

| Platform | Decision (morning) | Why |
| --- | --- | --- |
| **Streamlit Community Cloud** | Primary live host | Already running; least ops; correct runtime for Streamlit |
| **Vercel** | Keep as redirect only | Git check stays green; does not run Streamlit/Docker |
| **Render / Docker** | Packaged but not activated | Ready if needed later; skip for now to avoid free-tier cold starts |

**Owner manual step:** Streamlit Community Cloud **Reboot done** (2026-09-03, owner confirmed). Expected smoke-test while logged in: Simulate → Generate → History → audit download.

**Verified from agent environment after reboot:** Unauthenticated probes of the Streamlit URL still return `303` to Streamlit login — reachable but **not anonymously public**.

## Plan B — Render free Docker live (2026-09-03)

Owner chose Plan B (Render free plan) and supplied a Render API key for agent provisioning.

| Platform | Decision (Plan B) | Why |
| --- | --- | --- |
| **Render** | **Primary public demo** | Anonymous access; Docker matches repo packaging; free tier |
| **Vercel** | Redirect → Render | Public path without Streamlit login gate |
| **Streamlit Community Cloud** | Alternate / owner login | Still useful; optional Public setting |

**Provisioned service**

- Name: `acoustic-diagnostic-agent`
- URL: https://acoustic-diagnostic-agent.onrender.com
- Dashboard: https://dashboard.render.com/web/srv-dacr9d2d0e5s738977f0
- Runtime: Docker from `main`, Oregon, free plan
- Health: `/_stcore/health` → `200 ok`
- Env: `ACOUSTIC_AGENT_DATA_DIR=/tmp/acoustic_agent`, `PYTHONUNBUFFERED=1`
- First deploy `dep-dacr9did0e5s738978g0` live (~1.5 min) on commit `cbc0b9f`

**Caveats (accepted):** free-tier spin-down after ~15 min idle (cold start); ephemeral FS so History/SQLite is not durable across restarts.

**Security:** API key was shared in chat for provisioning — **rotate** it in the Render dashboard after this session; do not commit keys.

## Open follow-ups

- Rotate the Render API key that was pasted into chat.
- Optional: set Streamlit Cloud app to **Public** if that alternate should also be anonymous.
- Optional: attach a Render persistent disk if durable History on the free host is wanted.
- Trend-based *warnings* (alert when score slope crosses a threshold) still open.
- Real-data loaders (MAFAULDA / CWRU) and learned-detector ROC comparison remain backlog.
