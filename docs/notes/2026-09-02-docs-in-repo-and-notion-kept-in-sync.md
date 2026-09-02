# 2026-09-02 — Acoustic Diagnostic Agent — Documentation lives in repo and Notion, kept in sync

| Property | Value |
| --- | --- |
| Notion page | https://app.notion.com/p/3cf89f54d2c281b48659f9441ee42979 |
| Project | Acoustic Diagnostic Agent |
| Type | Decision |
| Status | Active |
| Session date | 2026-09-02 |
| Last reviewed | 2026-09-02 |
| Keywords | Notion, Workflow, Cursor, GitHub |
| Source / context | Owner instruction in Cursor session 2026-09-02: "always keep all documentation in repository along with notion. always keep both in sync." |

## Outcome

All project documentation now exists in both the git repository and the Notion Project Knowledge Library, with a bidirectional sync obligation enforced by rules at two levels.

## Key decisions (+ rationale)

- **Two copies, one truth.** Every doc lives in the repo (`README.md`, `docs/*.md`, `data/samples/README.md`, `docs/notes/*.md`) and as a page in the Notion library. Rationale: reviewers who only see GitHub, and collaborators who only see Notion, must get identical information; the repo copy is versioned with the code, the Notion copy is searchable across projects.
- **Sync in the same turn.** Whoever edits one side (agent or human) updates the other side before finishing. Rationale: deferred syncs are never done.
- **Mapping is explicit.** [`docs/notion-sync.md`](../notion-sync.md) lists each doc and its Notion URL; each Notion page carries a `Repo mirror:` callout. Rationale: makes drift detectable at a glance.
- **Enforcement.** (1) Global Cursor user rule "Notion Project Knowledge Library + repo docs mirror" updated with a Repository-mirror section, so the policy applies to every project. (2) Project rule [`.cursor/rules/docs-notion-sync.mdc`](../../.cursor/rules/docs-notion-sync.mdc) (alwaysApply) in this repo with the concrete file layout.
- **Content-equivalent, not byte-identical.** Notion tables/callouts/equations are converted to Markdown and back; section structure, dates and decision wording stay unchanged.

## Artifacts / links

- Repo: https://github.com/lalitsonawane/acoustic-diagnostic-agent-mvp — branch `feat/professionalize-phases-0-2`
- Sync index: [`docs/notion-sync.md`](../notion-sync.md)
- Notion mirrors created today: [README](https://app.notion.com/p/3cf89f54d2c281cfad00d4f4d008f6df), [Application documentation](https://app.notion.com/p/3cf89f54d2c2812d9fbed232d2a05b97), [Architecture and workflow](https://app.notion.com/p/3cf89f54d2c2817aa5fcedce29187cba), [Engineering student study guide](https://app.notion.com/p/3cf89f54d2c2817c9cc9e741d4fab500), [Sample WAV test set](https://app.notion.com/p/3cf89f54d2c2816b98ead3c25d0e5e15).
- Existing session note mirrored to the repo: [Professionalization & experiment-readiness plan](https://app.notion.com/p/3cf89f54d2c2816aa963e41e353e8fa5) → [`docs/notes/2026-09-02-professionalization-and-experiment-readiness-plan.md`](2026-09-02-professionalization-and-experiment-readiness-plan.md)

## Open follow-ups

- ~~Commit and push the new `docs/` files and `.cursor/rules/docs-notion-sync.mdc`~~ Done: commit `a0daca6` pushed to `origin/feat/professionalize-phases-0-2`.
- When the professionalization work adds new docs (CHANGELOG, CITATION.cff, ADRs), add them to both sides and to `docs/notion-sync.md`.
