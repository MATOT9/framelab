# Context Strategy

FrameLab keeps durable context in Markdown so future sessions can start cheaply and accurately.

## Reading Strategy

- Start with `START_HERE.md`.
- Use `REPO_MAP.md` to find the owning subsystem.
- Use `CURRENT_STATE.md` to understand current behavior.
- Use `KNOWN_ISSUES.md` and `ROADMAP.md` to understand known gaps.
- Use local `AGENTS.md` files for edit-time rules.
- Use `docs/developer-guide/*` for architecture and subsystem contracts.

## Writing Strategy

- Keep root docs compact and high-signal.
- Do not paste long architecture narratives into root files.
- Prefer links to canonical docs.
- Add or update local `AGENTS.md` files only when they change future editing decisions.
- Avoid creating new docs trees that duplicate existing `docs/developer-guide` pages.

## Handoff Strategy

Use the templates under `docs/handoffs/` for multi-step work. A useful handoff should include:

- exact user goal
- current repo state and dirty-file cautions
- files changed or likely to change
- validation already run
- known blockers or uncertainty
- next recommended reading set

## Decay Prevention

Context files decay when they become aspirational instead of factual. Keep these rules:

- update current-state docs only for implemented behavior
- update roadmap docs only for grounded planned work
- update known issues only when there is evidence
- mark uncertainty explicitly
- prefer deleting stale claims over adding caveats around them
