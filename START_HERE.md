# Start Here

This is the first file to read at the start of a FrameLab development session. It routes you to the smallest useful context set so future work does not depend on long chat history.

## First Five Minutes

1. Run `git status --short` and treat existing dirty files as someone else's work unless you know you made them.
2. Read [AGENTS.md](AGENTS.md), then read the nearest nested `AGENTS.md` for the area you will edit.
3. Pick the task routing below and read only the listed context before diving into code.
4. Prefer existing canonical docs over creating parallel explanations.
5. If behavior changes, update the docs listed in [AGENTS.md](AGENTS.md) before finishing.

## Source-Of-Truth Map

- [README.md](README.md): short human-facing landing page.
- [REPO_MAP.md](REPO_MAP.md): top-level folders and where to make common changes.
- [CURRENT_STATE.md](CURRENT_STATE.md): current behavior snapshot.
- [KNOWN_ISSUES.md](KNOWN_ISSUES.md): grounded bug, fragility, and incomplete-area registry.
- [ROADMAP.md](ROADMAP.md): grounded future work.
- [TESTING.md](TESTING.md): validation entry point.
- [BUILD_AND_RUN.md](BUILD_AND_RUN.md): setup, launch, docs, native, and package commands.
- `docs/developer-guide/*`: canonical architecture and subsystem documentation.
- `docs/reference/*`: exact file and payload contracts.
- Local `AGENTS.md` files: directory-specific editing rules.

## Task Routing

### Feature Work

Read:

- [AGENTS.md](AGENTS.md)
- [REPO_MAP.md](REPO_MAP.md)
- [CURRENT_STATE.md](CURRENT_STATE.md)
- the relevant `docs/developer-guide/*` page
- the nearest local `AGENTS.md`
- [TESTING.md](TESTING.md)

Update:

- [CURRENT_STATE.md](CURRENT_STATE.md) if implemented behavior changes.
- the canonical user/developer/reference doc for the feature area.
- [ROADMAP.md](ROADMAP.md) if the feature completes or reshapes a planned item.

### Bugfix Work

Read:

- [AGENTS.md](AGENTS.md)
- [KNOWN_ISSUES.md](KNOWN_ISSUES.md)
- [REPO_MAP.md](REPO_MAP.md)
- the nearest local `AGENTS.md`
- the test file closest to the affected behavior

Update:

- [KNOWN_ISSUES.md](KNOWN_ISSUES.md) when an issue is found, reclassified, or fixed.
- the canonical docs if user-visible behavior or constraints change.

### Performance Work

Read:

- [CURRENT_STATE.md](CURRENT_STATE.md)
- [KNOWN_ISSUES.md](KNOWN_ISSUES.md)
- [ROADMAP.md](ROADMAP.md)
- [docs/developer-guide/architecture.md](docs/developer-guide/architecture.md)
- [docs/maintenance/benchmark_workflow.md](docs/maintenance/benchmark_workflow.md)
- local `AGENTS.md` files for `framelab/`, `framelab/main_window/`, `framelab/native/`, `native/`, or `tools/` as relevant

Update:

- [CURRENT_STATE.md](CURRENT_STATE.md) for shipped performance behavior.
- [KNOWN_ISSUES.md](KNOWN_ISSUES.md) and [ROADMAP.md](ROADMAP.md) for measured bottlenecks or completed optimizations.

### Architecture Or Refactor Work

Read:

- [AGENTS.md](AGENTS.md)
- [REPO_MAP.md](REPO_MAP.md)
- [docs/developer-guide/architecture.md](docs/developer-guide/architecture.md)
- [docs/developer-guide/ui-structure.md](docs/developer-guide/ui-structure.md) for UI refactors
- [docs/development/repo_conventions.md](docs/development/repo_conventions.md)
- nearest local `AGENTS.md`

Update:

- the canonical developer-guide page for changed ownership or data flow.
- local `AGENTS.md` only when local editing rules or boundaries actually change.

### Docs-Only Work

Read:

- [docs/AGENTS.md](docs/AGENTS.md)
- [docs/development/context_strategy.md](docs/development/context_strategy.md)
- [TESTING.md](TESTING.md)
- [BUILD_AND_RUN.md](BUILD_AND_RUN.md)

Update:

- existing canonical docs instead of adding overlapping pages.
- `mkdocs.yml` and `scripts/docs/check.py` when docs pages are added, moved, or promoted into navigation.
- generated help only through `scripts/docs/build.py`.

### Native Or Backend Work

Read:

- [native/AGENTS.md](native/AGENTS.md)
- [tools/AGENTS.md](tools/AGENTS.md) if helper scripts are involved
- [native/README.md](native/README.md)
- [native/PYTHON_EXTENSION_BUILD.md](native/PYTHON_EXTENSION_BUILD.md)
- [docs/maintenance/benchmark_workflow.md](docs/maintenance/benchmark_workflow.md)

Update:

- [CURRENT_STATE.md](CURRENT_STATE.md), [ROADMAP.md](ROADMAP.md), and native docs when ABI, build, or performance behavior changes.

### Testing And Validation Work

Read:

- [TESTING.md](TESTING.md)
- [tests/AGENTS.md](tests/AGENTS.md)
- `scripts/tests.py`
- `pytest.ini`

Update:

- [TESTING.md](TESTING.md) when suite definitions, validation shortcuts, or known test caveats change.

## Workspace And Preferences Rule

FrameLab separates application preferences from reopenable workspace state:

- Persistent preferences live in `config/preferences.ini`.
- Reopenable session state lives in explicit `.framelab` workspace files.
- Unless a workspace file is opened, the app should behave like a fresh session except for preferences.

## After You Change Things

Before final handoff:

- run the smallest meaningful validation from [TESTING.md](TESTING.md)
- check for stale docs links or contradicted claims
- update root context docs when behavior, known issues, roadmap, or validation rules changed
- summarize files created, files updated, local `AGENTS.md` files added, omitted candidates, ambiguous topics, and recommended minimum reading sets when doing documentation-context work
