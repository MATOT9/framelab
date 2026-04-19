# AGENTS

These rules apply inside `docs/`.

## Source Ownership

- Edit Markdown source here, not generated HTML under `framelab/assets/help/`.
- Keep `docs/developer-guide/*` canonical for architecture and subsystem contracts.
- Keep `docs/reference/*` canonical for exact schemas, file paths, and manifest/catalog fields.
- Keep `docs/user-guide/*` operator-facing.
- Keep `docs/development/*`, `docs/handoffs/*`, and `docs/maintenance/*` concise and developer-facing.

## Navigation And Validation

- Update `mkdocs.yml` when adding promoted Markdown pages.
- Update `scripts/docs/check.py` when docs validation should require new pages.
- Run a strict docs build for navigation/source changes.
- Rebuild bundled help through `scripts/docs/build.py` when generated help should be refreshed.

## Style

- Prefer short, scannable sections.
- Link to canonical pages instead of duplicating long explanations.
- Distinguish current behavior, known limitations, and future work.
- Mark uncertain claims explicitly.
