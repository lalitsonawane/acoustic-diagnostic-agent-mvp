# Documentation sync: repository ↔ Notion

All documentation for this project exists in **two places** and is kept in sync:

1. This git repository (versioned with the code).
2. The Notion **Project Knowledge Library** — https://app.notion.com/p/7cc641cb90c1408d9419894d90233c7b
   (data source `collection://f0c83c93-62b6-4e7a-a0e3-3f6d687bc220`, Project = `Acoustic Diagnostic Agent`).

Neither side is the single source of truth. A reader who only has GitHub, or only has Notion, must get the same information.

## Mapping

| Repository file | Notion page | Notion type |
| --- | --- | --- |
| [`README.md`](../README.md) | [README (project overview)](https://app.notion.com/p/3cf89f54d2c281cfad00d4f4d008f6df) | Reference |
| [`docs/application.md`](application.md) | [Application documentation](https://app.notion.com/p/3cf89f54d2c2812d9fbed232d2a05b97) | Reference |
| [`docs/architecture.md`](architecture.md) | [Architecture and workflow](https://app.notion.com/p/3cf89f54d2c2817aa5fcedce29187cba) | Reference |
| [`docs/engineering-student-guide.md`](engineering-student-guide.md) | [Engineering student study guide](https://app.notion.com/p/3cf89f54d2c2817c9cc9e741d4fab500) | How-to |
| [`data/samples/README.md`](../data/samples/README.md) | [Sample WAV test set (data/samples)](https://app.notion.com/p/3cf89f54d2c2816b98ead3c25d0e5e15) | Reference |
| [`docs/notes/2026-09-02-professionalization-and-experiment-readiness-plan.md`](notes/2026-09-02-professionalization-and-experiment-readiness-plan.md) | [2026-09-02 — Professionalization & experiment-readiness plan](https://app.notion.com/p/3cf89f54d2c2816aa963e41e353e8fa5) | Research |
| [`docs/notes/2026-09-02-docs-in-repo-and-notion-kept-in-sync.md`](notes/2026-09-02-docs-in-repo-and-notion-kept-in-sync.md) | [2026-09-02 — Documentation lives in repo and Notion, kept in sync](https://app.notion.com/p/3cf89f54d2c281b48659f9441ee42979) | Decision |
| [`docs/notes/2026-09-02-implemented-phases-0-2-and-ui-upgrade.md`](notes/2026-09-02-implemented-phases-0-2-and-ui-upgrade.md) | [2026-09-02 — Implemented phases 0-2 and UI upgrade (v0.2.0)](https://app.notion.com/p/3cf89f54d2c281e58f18da600049ca14) | Session summary |
| [`docs/notes/2026-09-03-phases-3-4-persistence-and-deployment.md`](notes/2026-09-03-phases-3-4-persistence-and-deployment.md) | [2026-09-03 — Phases 3–4 persistence and deployment (v0.3.0)](https://app.notion.com/p/3d089f54d2c281fcab56d6e65fa32fd6) | Session summary |
| [`CHANGELOG.md`](../CHANGELOG.md) | Summarised in the session notes; the changelog itself is repo-only | — |
| `docs/notion-sync.md` (this file) | Each Notion page carries a `Repo mirror:` callout pointing back here | — |

## Sync procedure

Applies to humans and to agents (see [`.cursor/rules/docs-notion-sync.mdc`](../.cursor/rules/docs-notion-sync.mdc)).

### You changed a repository doc

1. Open the matching Notion page from the table above (create it under the library data source if it does not exist, with Project, Type, Status, Session date, Keywords, Source/context and Last reviewed set).
2. Apply the same change. Convert Markdown tables to Notion tables, ` ```mermaid ` blocks to Mermaid code blocks, `\[ … \]` math to `$$ … $$` equation blocks.
3. Make sure the page has a `Repo mirror:` callout with the repo path.
4. Update **Last reviewed** on the Notion page.
5. If you created a new doc, add a row to the mapping table above and commit this file with the change.

### You changed a Notion page

1. Find the repo file in the table above (for a new session/decision/research note, create `docs/notes/YYYY-MM-DD-<subject>.md`).
2. Apply the same change in Markdown. For notes, keep the property block at the top (Notion page URL, Project, Type, Status, dates, Keywords, Source/context) and the same section headings (Outcome, Key decisions, Artifacts/links, Open follow-ups).
3. Add the row to the mapping table if it is a new file.
4. Commit together with any related code change.

### If a sync cannot be completed

Say so explicitly in the summary of the work and record it as an **Open follow-up** on both sides as soon as either is reachable. Do not silently leave one side stale.

## Conventions

- Notion titles for notes: `YYYY-MM-DD — Acoustic Diagnostic Agent — <subject>`; repo file: `docs/notes/YYYY-MM-DD-<subject-slug>.md`.
- Notion titles for reference docs: `Acoustic Diagnostic Agent — <doc title>`.
- Mirrors are content-equivalent, not byte-identical. Dates, numbers and decision wording must not differ.
- Superseded guidance is marked Superseded on Notion and noted at the top of the repo file; nothing is deleted.
