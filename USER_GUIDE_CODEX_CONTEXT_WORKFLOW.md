# User Guide — Token-Saving Codex Workflow

The goal of this method is to make each new Codex session **small, scoped, and doc-driven**.

Instead of re-explaining your whole app every time, start by telling the agent to read only the routing docs and only the subsystem docs relevant to the task.

## Core workflow

For almost every task, use this pattern:

1. Tell the agent to read `START_HERE.md`
2. Tell it which task type this is
3. Tell it which docs to read next
4. Restrict code inspection to relevant folders/files first
5. Ask for diagnosis/plan before implementation when the task is non-trivial

A good prompt has five parts:

- **task type**
- **goal**
- **docs to read**
- **code scope**
- **expected output**

## Universal starter prompt

Use this as your default opener:

```text
Read START_HERE.md and follow the routing for this task type: [BUGFIX / FEATURE / PERFORMANCE / REFACTOR / DOCS / NATIVE].

Then read only the minimum required docs for that route.

After that, inspect only the relevant files first, not the whole repo.

Task:
[describe the task]

Deliverables:
1. brief diagnosis
2. implementation plan
3. code changes
4. summary of files changed
5. any docs that should be updated
```

## 1) Bugfix prompt

Use this when something is broken and you want a focused repair.

```text
Read START_HERE.md and follow the routing for a bugfix task.

Then read:
- CURRENT_STATE.md
- KNOWN_ISSUES.md
- the most relevant subsystem docs
- the nearest local AGENTS.md for the files you inspect

Inspect only the files related to [preview switching / dataset loading / metrics table / plugin loading].

Bug:
[describe the bug clearly]

First give:
1. probable root cause
2. files that should be changed
3. a minimal fix plan

Then implement the fix and update any relevant docs if behavior changed.
```

### Example

```text
Read START_HERE.md and follow the routing for a bugfix task.

Then read:
- CURRENT_STATE.md
- KNOWN_ISSUES.md
- docs/developer-guide/preview_pipeline.md
- framelab/main_window/AGENTS.md

Inspect only the preview-related files first.

Bug:
When switching images quickly, the preview lags and the histogram updates several times before settling.

First give:
1. probable root cause
2. files to change
3. minimal fix plan

Then implement the fix.
```

## 2) Feature prompt

Use this when you want to add a new capability.

```text
Read START_HERE.md and follow the routing for a feature task.

Then read:
- CURRENT_STATE.md
- ROADMAP.md
- the relevant feature and architecture docs
- the nearest local AGENTS.md files

Inspect only the files relevant to this feature first.

Feature:
[describe the new feature]

Constraints:
- do not widen scope beyond this feature
- preserve existing behavior unless required
- keep architecture aligned with current subsystem boundaries

First provide:
1. fit with current architecture
2. implementation plan
3. files to modify
4. risks / edge cases

Then implement phase 1 only.
```

### Example

```text
Read START_HERE.md and follow the routing for a feature task.

Then read:
- CURRENT_STATE.md
- ROADMAP.md
- docs/developer-guide/plugin_system.md
- framelab/plugins/AGENTS.md

Inspect only the plugin discovery and plugin host files first.

Feature:
Add a plugin capability flag so plugins can declare whether they support batch processing, live preview, or export-only workflows.

Constraints:
- keep backward compatibility for existing plugins
- avoid changing unrelated UI code

First provide:
1. architectural fit
2. implementation plan
3. files to modify
4. migration notes for old plugins

Then implement phase 1 only.
```

## 3) Performance prompt

Use this when the app is too slow, too memory-hungry, or blocking the UI.

```text
Read START_HERE.md and follow the routing for a performance task.

Then read:
- CURRENT_STATE.md
- KNOWN_ISSUES.md
- the relevant performance / caching / threading docs
- the nearest local AGENTS.md files

Inspect only the performance-critical files first.

Performance problem:
[describe symptom]

Goal:
[state measurable improvement target if known]

First provide:
1. likely bottlenecks
2. whether the issue is compute, memory, I/O, threading, or UI churn
3. a ranked fix plan from least invasive to most invasive

Do not implement everything at once. Start with the highest-value low-risk change.
```

### Example

```text
Read START_HERE.md and follow the routing for a performance task.

Then read:
- CURRENT_STATE.md
- KNOWN_ISSUES.md
- docs/developer-guide/caching.md
- docs/developer-guide/threading.md
- framelab/main_window/AGENTS.md

Inspect only the dataset loading, preview cache, and histogram update files first.

Performance problem:
The app uses too much RAM on large TIFF datasets and preview switching becomes sluggish after long sessions.

Goal:
Reduce memory growth and remove UI lag without changing visible behavior.

First provide:
1. likely bottlenecks
2. whether the problem is memory, I/O, threading, or UI churn
3. a ranked fix plan

Then implement only the first high-value change.
```

## 4) Refactor / architecture prompt

Use this when code works but structure is getting messy.

```text
Read START_HERE.md and follow the routing for an architecture/refactor task.

Then read:
- CURRENT_STATE.md
- ROADMAP.md
- the relevant architecture docs
- the nearest local AGENTS.md files

Inspect only the subsystem under refactor first.

Refactor goal:
[describe cleanup objective]

Constraints:
- preserve external behavior
- avoid broad rewrites unless justified
- improve boundaries, readability, and maintainability

First provide:
1. current structural problems
2. proposed target structure
3. migration steps
4. risks to avoid

Then implement only the first refactor step.
```

### Example

```text
Read START_HERE.md and follow the routing for an architecture/refactor task.

Then read:
- CURRENT_STATE.md
- ROADMAP.md
- docs/developer-guide/main_window_architecture.md
- framelab/main_window/AGENTS.md

Inspect only the main window orchestration files first.

Refactor goal:
Reduce main-window responsibility by moving dataset-load orchestration into a controller/service layer.

Constraints:
- preserve behavior
- do not break current signals/slots behavior
- keep the change incremental

First provide:
1. current structural problems
2. target structure
3. stepwise migration plan
4. risks

Then implement only the first step.
```

## 5) Docs-only prompt

Use this when you want documentation updates without code churn.

```text
Read START_HERE.md and follow the routing for a docs-only task.

Then read the docs relevant to the topic and inspect code only as needed to verify accuracy.

Docs task:
[describe what should be documented or corrected]

Constraints:
- do not modify application code
- keep docs concise
- avoid duplicating existing canonical docs
- update links/cross-references if needed

Provide:
1. docs to update
2. gaps or contradictions found
3. proposed changes

Then apply the documentation updates.
```

### Example

```text
Read START_HERE.md and follow the routing for a docs-only task.

Then read:
- REPO_MAP.md
- CURRENT_STATE.md
- docs/developer-guide/*
- docs/development/context_strategy.md

Docs task:
Update the documentation to explain how datacard templates work and where they live in the repo.

Constraints:
- do not modify code
- reuse existing canonical docs where possible
- avoid duplicate explanations
```

## 6) Native/backend prompt

Use this for C/C++ backend, ABI, bindings, decoding kernels, build system, and performance-critical low-level work.

```text
Read START_HERE.md and follow the routing for a native/backend task.

Then read:
- BUILD_AND_RUN.md
- CURRENT_STATE.md
- the native backend docs
- native/AGENTS.md
- any relevant testing docs

Inspect only the native/backend files related to the task first.

Task:
[describe native/backend work]

First provide:
1. current boundary between Python and native code
2. implementation impact
3. build/test implications
4. migration or compatibility risks

Then implement the smallest correct change.
```

### Example

```text
Read START_HERE.md and follow the routing for a native/backend task.

Then read:
- BUILD_AND_RUN.md
- CURRENT_STATE.md
- docs/developer-guide/native_backend.md
- native/AGENTS.md

Inspect only the Mono12 packed decode path first.

Task:
Add a native fast path for Mono12p decoding with stride support, without changing the Python-facing API.

First provide:
1. boundary impact
2. files to modify
3. build/test implications
4. risks
```

## 7) Testing / validation prompt

Use this when the main task is to add, improve, or run validation.

```text
Read START_HERE.md and follow the routing for a testing/validation task.

Then read:
- TESTING.md
- CURRENT_STATE.md
- the relevant subsystem docs
- tests/AGENTS.md if present

Inspect only the relevant test files and touched implementation files first.

Testing task:
[describe desired validation]

Provide:
1. current coverage situation
2. best validation approach
3. tests to add or update
4. any risky blind spots

Then implement the test changes.
```

## Best practices that save the most tokens

### 1. Start fresh often
Use a new session for a new problem.

Do not keep one giant conversation for the whole app.

### 2. Route first, inspect second
Always begin with `START_HERE.md`, then the minimum relevant docs, then only relevant code.

### 3. Ask for plan first on complex work
For non-trivial tasks, do:
- diagnosis
- plan
- phase 1 implementation

That prevents expensive wrong turns.

### 4. Restrict file scope
Say things like:
- “Inspect only preview-related files first”
- “Do not scan the whole repo yet”
- “Start with plugin discovery files only”

### 5. Ask for phased work
Instead of:
- “Implement the full new subsystem”

Use:
- “Implement phase 1 only”
- “Do the minimal correct fix first”
- “Stop after the first refactor step”

### 6. Require doc updates when behavior changes
That keeps the repo memory accurate, which is the whole point of this method.

## Very short prompt versions

For fast use, these are enough.

### Bugfix

```text
Read START_HERE.md and follow the bugfix route. Then read only the minimum relevant docs and nearest AGENTS.md files. Inspect only the files related to [X]. First give diagnosis and fix plan, then implement.
```

### Feature

```text
Read START_HERE.md and follow the feature route. Then read only the relevant docs and local AGENTS.md files. Inspect only the subsystem for [X]. First give plan and risks, then implement phase 1 only.
```

### Performance

```text
Read START_HERE.md and follow the performance route. Then read the caching/threading/current-state docs and nearest AGENTS.md files. Inspect only the files related to [X]. First rank bottlenecks and propose fixes, then implement the highest-value low-risk change.
```

### Refactor

```text
Read START_HERE.md and follow the architecture/refactor route. Then read the relevant architecture docs and local AGENTS.md files. Inspect only the target subsystem first. Propose a stepwise refactor plan, then implement step 1 only.
```

## Practical rule of thumb

For each new task, ask yourself:

**What is the minimum set of docs and files the agent must read to do this correctly?**

That is the whole token-saving method.
