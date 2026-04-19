# Development Troubleshooting

Use this page for maintainer-facing issues that are not normal operator troubleshooting.

## Dirty Worktree Confusion

If many files are already modified:

- run `git status --short`
- inspect only files relevant to the task
- do not revert unrelated work
- mention unrelated dirty state in the handoff if it affects validation confidence

## Docs Build Fails

Check:

- `mkdocs.yml` includes every promoted Markdown page in the intended navigation
- `scripts/docs/check.py` required files match the docs source set
- local docs dependencies are installed
- MathJax assets are available or `FRAMELAB_MATHJAX_DIR` is set
- generated help was rebuilt through `scripts/docs/build.py`, not hand-edited

## Plugin Does Not Load

Check:

- manifest exists under the correct page directory
- manifest `page` matches its directory
- `plugin_id` is unique
- dependencies refer to discovered plugin ids
- entrypoint module imports cleanly
- entrypoint registers the expected class
- startup selection enabled the plugin after dependency closure

## Workspace State Restores Unexpectedly

Check:

- whether a `.framelab` workspace file was opened
- whether the state belongs to preferences or session restore
- whether code accidentally reads session-like state from legacy UI state config
- whether tests cover both fresh launch and workspace-open paths

## UI Or Worker Hangs

Check:

- long-running work is off the UI thread
- workers operate on snapshots, not live mutable host state
- signal handlers validate job identity before applying results
- UI tests use offscreen Qt and targeted fixtures

## Native Backend Issues

Check:

- the active Python interpreter matches the extension build target
- NumPy headers are available
- CMake can find the target compiler
- Python fallback behavior still works when the native extension is unavailable
- native changes include relevant decode or metric tests
