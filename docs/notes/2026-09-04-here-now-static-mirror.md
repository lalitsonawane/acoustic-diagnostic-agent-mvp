# 2026-09-04 — Acoustic Diagnostic Agent — here.now static mirror of the Render demo

| Property | Value |
| --- | --- |
| Notion page | https://app.notion.com/p/3d189f54d2c28132a1e5d645bd83e264 |
| Project | Acoustic Diagnostic Agent |
| Type | Session summary |
| Status | Active |
| Session date | 2026-09-04 |
| Last reviewed | 2026-09-04 |
| Keywords | Cursor, GitHub, Workflow, Architecture |
| Source / context | Owner request in Cursor cloud agent session 2026-09-04: "This application is already deployed on Render. Additionally deploy it to here.now." Branch `lalit_cursor/here-now-static-mirror-09d1` of [github.com/lalitsonawane/acoustic-diagnostic-agent-mvp](https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp). |

## Outcome

The app now has a **here.now** entry point in addition to Render, Streamlit Community Cloud
and Vercel. [here.now](https://here.now) is static-file hosting built for agents (no
server-side compute), so — exactly like Vercel — it serves the `public/index.html` page that
redirects to the Streamlit app on Render. The Streamlit server itself keeps running on Render.

- Live Site: https://flowing-bamboo-pz9j.here.now/ (slug `flowing-bamboo-pz9j`), verified
  `HTTP 200` serving the redirect page.
- Published **anonymously** (no here.now credentials exist in the agent environment), so it
  **expires 2026-09-05 05:48 UTC** unless claimed. Claim URL was given to the owner in the
  session summary; it is single-use secret material and is **not** recorded here.
- Repo additions: `scripts/publish_herenow.sh` (self-contained curl + jq implementation of
  the create/update → presigned upload → finalize flow, with `HERENOW_API_KEY`,
  `HERENOW_SLUG`, `HERENOW_CLAIM_TOKEN` and a local `.herenow/state.json`, git-ignored),
  `.github/workflows/deploy-herenow.yml` (republish on push to `main` touching `public/`,
  skipped until the `HERENOW_API_KEY` secret exists), README Deploy section, CHANGELOG.

## Key decisions (+ rationale)

- **Static redirect, not the Streamlit server.** here.now explicitly excludes server-side
  compute and long-running processes; a Streamlit app needs a websocket server. Publishing
  the same `public/` redirect page as Vercel gives a here.now URL without a second runtime
  to maintain. Render stays the single place the app actually runs.
- **Own small script instead of vendoring the 500-line official `publish.sh`.** The repo
  only needs the create/update/upload/finalize path; a focused script is easier to review
  and depends only on `curl`, `jq`, `sha256sum`.
- **Anonymous publish now, permanent later.** No API key was available and the agent must
  not sign the owner up for an account. The claim URL lets the owner adopt the Site into a
  free here.now account; alternatively `HERENOW_API_KEY` + `HERENOW_SLUG` as GitHub secrets
  turn the workflow into a continuous deploy.
- **Workflow is a no-op without secrets.** An unauthenticated CI publish would mint a new
  24-hour slug on every push, which is useless for a stable link, so the job exits early.

## Artifacts / links

- Branch `lalit_cursor/here-now-static-mirror-09d1` → PR on
  [github.com/lalitsonawane/acoustic-diagnostic-agent-mvp](https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp/pulls).
- Live: https://flowing-bamboo-pz9j.here.now/ → https://acoustic-diagnostic-agent.onrender.com/
- Script: `scripts/publish_herenow.sh`; workflow: `.github/workflows/deploy-herenow.yml`.
- here.now API reference: https://here.now/docs (OpenAPI: https://here.now/openapi.json).
- Notion: https://app.notion.com/p/3d189f54d2c28132a1e5d645bd83e264

## Open follow-ups

- **Owner:** open the claim URL from the session summary (or create a here.now API key at
  https://here.now/dashboard) before 2026-09-05 05:48 UTC, otherwise the anonymous Site
  expires and the README link goes dead. After claiming, set `HERENOW_API_KEY` and
  `HERENOW_SLUG=flowing-bamboo-pz9j` as repository secrets so the workflow keeps it fresh.
- If the Site expires before it is claimed, re-run `scripts/publish_herenow.sh public` with an
  API key and update the URL in README, CHANGELOG, this note and the Notion mirrors.
- Earlier follow-ups (rotate Render API key, optional Render disk, Streamlit Cloud Public
  setting, trend warnings, real-data loaders) remain open in the 2026-09-03 note.
