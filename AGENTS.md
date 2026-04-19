# AGENTS

These instructions apply to the whole repository. Read this file first, then read the nearest nested `AGENTS.md` before editing inside a subsystem.

## Working Rules

- Start by checking `git status --short`.
- Never revert or overwrite unrelated dirty work.
- Prefer targeted reads and existing canonical docs before making assumptions.
- Keep application-code edits out of docs-only tasks unless a broken reference or validation issue makes a minimal fix unavoidable.
- Do not inspect or depend on ignored archival folders such as `archived/` unless the user explicitly asks.
- Prefer updating an existing canonical doc over creating a competing explanation.

## Source Ownership

- Root docs are the fast-start context layer for developers and future agents.
- `docs/developer-guide/*` is canonical for architecture, state ownership, and subsystem contracts.
- `docs/reference/*` is canonical for exact file, manifest, catalog, and schema contracts.
- `docs/user-guide/*` is canonical for operator-facing workflows.
- Nested `AGENTS.md` files are local editing rules, not replacement architecture docs.

## Documentation Maintenance Rules

- Update [CURRENT_STATE.md](CURRENT_STATE.md) when implemented behavior materially changes.
- Update [KNOWN_ISSUES.md](KNOWN_ISSUES.md) when an issue is found, reclassified, or fixed.
- Update [ROADMAP.md](ROADMAP.md) when planned work is completed, removed, or substantially reshaped.
- Update [TESTING.md](TESTING.md) when validation commands, suites, or known test caveats change.
- Update the relevant canonical user/developer/reference doc when subsystem behavior changes.
- Update a local `AGENTS.md` only when local editing rules or boundaries change.

## Runtime State Rules

- Persistent UI preferences belong in `config/preferences.ini`.
- Reopenable workflow/session/UI state belongs in explicitly saved `.framelab` workspace files.
- Legacy `ui_state.ini` may be tolerated only for limited preference migration. Do not reintroduce automatic session restore from it.
- eBUS Config Tools are built-in host-owned tools under `Edit -> Advanced`, not a data-page plugin.

## Generated Output Rules

- Edit Markdown source under `docs/`, not generated HTML under `framelab/assets/help/`.
- Rebuild bundled help through `python scripts/docs/build.py --strict` when generated help must be updated.
- Treat `.docs_build/`, native build folders, pytest caches, and Python bytecode as disposable.

## Validation Defaults

- Docs-only changes: `git diff --check`, targeted `rg` checks, and docs build/check when MkDocs source or nav changes.
- Code changes: run the smallest relevant tests from [TESTING.md](TESTING.md), usually through `scripts/tests.py`.
- Native changes: include native build or backend tests in addition to Python coverage.
- Packaging changes: include docs validation and `tools/build_nuitka_app.py --check` when the package layout or runtime assets change.

## Local AGENTS Files

Current local guidance lives in:

- `framelab/AGENTS.md`
- `framelab/main_window/AGENTS.md`
- `framelab/plugins/AGENTS.md`
- `framelab/workflow/AGENTS.md`
- `framelab/ebus/AGENTS.md`
- `native/AGENTS.md`
- `tests/AGENTS.md`
- `docs/AGENTS.md`
- `tools/AGENTS.md`
