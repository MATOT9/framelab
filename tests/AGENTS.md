# AGENTS

These rules apply inside `tests/`.

## Test Placement

- Put behavior tests close to the owning subsystem.
- Prefer pure state/controller tests when widget interaction is not required.
- Use UI tests for signal wiring, menu/action availability, and actual widget behavior.
- Keep fixtures small and deterministic.

## Suite Awareness

- `scripts/tests.py` defines named suites and changed-file mapping.
- Update root `TESTING.md` when suite behavior changes.
- Avoid adding tests that require a visible desktop unless the task explicitly needs it.

## Qt

- The repo test helper sets `QT_QPA_PLATFORM=offscreen`.
- Be careful with timers, modal dialogs, and worker-thread cleanup.
- Prefer explicit waits and cleanup over assumptions about event-loop timing.

## Dirty Worktree

- Do not update tests by weakening expectations just to match unrelated dirty code.
- If behavior changed intentionally, update the closest tests and the relevant docs together.
