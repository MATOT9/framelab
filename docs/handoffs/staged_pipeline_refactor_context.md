# Staged-Pipeline Refactor Context + Codex Task Prompts

This file is meant to be **given to Codex first** so the task prompts below have the required context.

---

# Part 1 — Context Codex must read first

## Objective

Refactor the app away from a policy where scan completion and UI changes implicitly trigger broad downstream computation.

The target is a **staged pipeline** where:
- scan-time work stays light and scalable
- later computations are explicit
- plugins are explicit consumers, not hidden compute triggers
- tab/scope changes are treated as view changes unless inputs actually changed

## Problem Summary

The current bottleneck is largely a **policy problem**, not just one slow loop.

Known problem patterns include:
- scan completion still triggers downstream live-update behavior
- broad dynamic recomputation starts too eagerly
- analysis refresh behavior is still too tied to live context refresh
- workflow structure edits can still lead to unnecessary dataset reloading/scanning
- tab/scope changes can still trigger work that should be deferred or cached

This makes the app feel acceptable on a fresh start, then fragile after one large scope.

## Target Model

### Pass 0 — Scope discovery
This owns only:
- workflow scope selection
- file discovery
- path metadata
- selected image preview readiness
- no analysis-specific computation

### Pass 1 — Scan-time metrics
These are light metrics computed only if selected for scan-time use.

Typical families:
- `max_pixel`
- `min_non_zero`
- `elapsed_time_s` if timestamps exist
- saturation count only if explicitly applied
- metadata-derived values when appropriate

### Pass 2 — Advanced / mode-specific metrics
These are explicitly triggered later.

Typical families:
- Top-K metrics
- ROI dataset-wide metrics
- ROI + Top-K metrics
- background-sensitive recomputes
- plugin-specific derived values

### Pass 3 — Plugin actions
Plugins should:
- consume already-available data where possible
- declare missing requirements clearly
- expose explicit actions like Compute / Run / Build Plot
- never silently expand scan-time work

## Intended UX Defaults

### On scan
Default scan-time behavior should remain light. Good defaults are:
- paths
- metadata
- `max_pixel`
- `min_non_zero`
- `elapsed_time_s` when available

No broad ROI, Top-K, or plugin-driven compute by default.

### On Measure page
- threshold changes do nothing until **Apply Threshold**
- low-signal threshold changes do nothing until **Apply**
- Top-K changes do nothing until **Apply Top-K**
- ROI drawing should affect local preview, but dataset-wide ROI compute should be explicit

### On Analyze page
- plugin context refresh should be cheap/passive
- plugin computation should happen through an explicit action
- plugin host should expose missing requirements clearly

## Recommended Rollout Order

Do **not** implement the full refactor in one pass.

Use this rollout order:

1. Quick stability win
   - stop automatic post-scan downstream recompute
   - do not let analysis/plugins silently add compute on scan
   - stop workflow rename/renumber/create from causing unnecessary rescans

2. State model
   - add explicit metric families
   - add explicit metric-family readiness/staleness states
   - separate pending UI values from last applied values

3. Data-tab scan setup
   - make scan-time metric selection explicit
   - persist selection in workspace state

4. Targeted workers/jobs
   - replace broad dynamic worker logic with targeted metric requests/jobs

5. Plugin contract
   - make plugins explicit consumers with declared requirements

6. Task/status UX and cache cleanup
   - show runtime tasks explicitly
   - make tab/scope revisits cheap
   - treat tab changes as view events, not compute events

## Important Constraints

- Keep each task narrow.
- Preserve existing numerical behavior unless the task explicitly changes policy.
- Prefer incremental migration over broad rewrites.
- Update docs whenever behavior changes.
- Avoid introducing hidden recomputation through new code paths.
