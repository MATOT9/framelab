"""Small runtime task state model for user-visible background work."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class RuntimeTaskState(str, Enum):
    """Lifecycle state for one host-owned runtime task."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RuntimeTask:
    """User-visible status payload for one runtime task."""

    task_id: str
    label: str
    state: RuntimeTaskState
    target: str = ""
    progress_done: int | None = None
    progress_total: int | None = None
    status: str = ""
    updated_sequence: int = 0


class RuntimeTaskController:
    """Track compact runtime task state independently from Qt widgets."""

    def __init__(self) -> None:
        self._tasks: dict[str, RuntimeTask] = {}
        self._sequence = 0

    @staticmethod
    def _state(state: RuntimeTaskState | str) -> RuntimeTaskState:
        if isinstance(state, RuntimeTaskState):
            return state
        return RuntimeTaskState(str(state))

    @staticmethod
    def _normalize_progress(value: int | None) -> int | None:
        if value is None:
            return None
        return max(0, int(value))

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def begin(
        self,
        task_id: str,
        label: str,
        *,
        target: str = "",
        status: str = "",
        progress_done: int | None = None,
        progress_total: int | None = None,
    ) -> RuntimeTask:
        """Create or replace one running task."""

        task = RuntimeTask(
            task_id=str(task_id),
            label=str(label or "Task"),
            state=RuntimeTaskState.RUNNING,
            target=str(target or ""),
            progress_done=self._normalize_progress(progress_done),
            progress_total=self._normalize_progress(progress_total),
            status=str(status or ""),
            updated_sequence=self._next_sequence(),
        )
        self._tasks[task.task_id] = task
        return task

    def update(
        self,
        task_id: str,
        *,
        status: str | None = None,
        progress_done: int | None = None,
        progress_total: int | None = None,
    ) -> RuntimeTask | None:
        """Update one existing task and return it."""

        key = str(task_id)
        task = self._tasks.get(key)
        if task is None:
            return None
        task = replace(
            task,
            status=task.status if status is None else str(status or ""),
            progress_done=(
                task.progress_done
                if progress_done is None
                else self._normalize_progress(progress_done)
            ),
            progress_total=(
                task.progress_total
                if progress_total is None
                else self._normalize_progress(progress_total)
            ),
            updated_sequence=self._next_sequence(),
        )
        self._tasks[key] = task
        return task

    def finish(
        self,
        task_id: str,
        *,
        state: RuntimeTaskState | str = RuntimeTaskState.SUCCEEDED,
        status: str = "",
    ) -> RuntimeTask | None:
        """Mark one task complete, failed, or cancelled."""

        key = str(task_id)
        task = self._tasks.get(key)
        if task is None:
            return None
        final_state = self._state(state)
        task = replace(
            task,
            state=final_state,
            status=str(status or task.status or final_state.value.replace("_", " ")),
            updated_sequence=self._next_sequence(),
        )
        self._tasks[key] = task
        return task

    def task(self, task_id: str) -> RuntimeTask | None:
        """Return one task by id."""

        return self._tasks.get(str(task_id))

    def active_tasks(self) -> tuple[RuntimeTask, ...]:
        """Return active tasks in most-recently-updated order."""

        return tuple(
            sorted(
                (
                    task
                    for task in self._tasks.values()
                    if task.state
                    in {RuntimeTaskState.QUEUED, RuntimeTaskState.RUNNING}
                ),
                key=lambda task: task.updated_sequence,
                reverse=True,
            ),
        )

    def latest_task(self) -> RuntimeTask | None:
        """Return the most recently updated task, if any."""

        if not self._tasks:
            return None
        return max(self._tasks.values(), key=lambda task: task.updated_sequence)

    @staticmethod
    def task_text(task: RuntimeTask) -> str:
        """Return compact user-facing text for one task."""

        parts = [task.label]
        if task.target:
            parts.append(task.target)
        if task.status:
            parts.append(task.status)
        if (
            task.progress_done is not None
            and task.progress_total is not None
            and task.progress_total > 0
        ):
            parts.append(f"{task.progress_done}/{task.progress_total}")
        return " - ".join(parts)

    def summary_text(self) -> str:
        """Return a compact summary for status surfaces."""

        active = self.active_tasks()
        if active:
            text = self.task_text(active[0])
            if len(active) > 1:
                text = f"{text} (+{len(active) - 1})"
            return text
        latest = self.latest_task()
        if latest is None:
            return ""
        if latest.state in {RuntimeTaskState.FAILED, RuntimeTaskState.CANCELLED}:
            return self.task_text(latest)
        return ""
