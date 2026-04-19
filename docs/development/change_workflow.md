# Change Workflow

Use this checklist when implementing changes in FrameLab.

## Before Editing

- Run `git status --short`.
- Identify unrelated dirty files and leave them alone.
- Read `START_HERE.md`, root `AGENTS.md`, and the nearest local `AGENTS.md`.
- Read the canonical docs for the subsystem you will touch.
- Choose the smallest validation set before you change code.

## During Editing

- Keep code changes inside the owning subsystem.
- Prefer controller/state changes over ad hoc widget state when behavior crosses pages.
- Keep long-running dataset work out of the UI thread.
- Preserve plugin discovery/import separation.
- Preserve the preferences versus `.framelab` workspace split.
- Update tests close to the changed behavior.

## Docs Updates

Update docs in the same change when behavior changes:

- `CURRENT_STATE.md` for material current behavior changes.
- `KNOWN_ISSUES.md` for issue discovery, reclassification, or fixes.
- `ROADMAP.md` for completed or reshaped planned work.
- `TESTING.md` for validation workflow changes.
- The relevant user/developer/reference page for public or subsystem contracts.
- The nearest local `AGENTS.md` only when local editing rules change.

## Before Handoff

- Run the selected validation commands.
- Run `git diff --check`.
- Scan for stale docs references with targeted `rg`.
- Summarize what changed, what was validated, and any remaining risks.
- If docs source changed and bundled help is expected to stay current, rebuild through `scripts/docs/build.py`.
