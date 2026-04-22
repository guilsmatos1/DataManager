"""In-memory task progress tracker for background operations."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskState:
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    total: float = 0.0
    current: float = 0.0
    description: str = ""
    message: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class TaskTracker:
    """Thread-safe in-memory task registry with TTL-based cleanup."""

    def __init__(self, ttl_seconds: float = 300.0):
        self._tasks: dict[str, TaskState] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def create_task(self, description: str = "") -> str:
        task_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._tasks[task_id] = TaskState(task_id=task_id, description=description)
        return task_id

    def get(self, task_id: str) -> TaskState | None:
        with self._lock:
            return self._tasks.get(task_id)

    def update(self, task_id: str, **kwargs: object) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                for key, value in kwargs.items():
                    setattr(task, key, value)
                task.updated_at = time.time()

    def list_active(self) -> list[TaskState]:
        with self._lock:
            self._cleanup()
            return [
                t
                for t in self._tasks.values()
                if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
            ]

    def _cleanup(self) -> None:
        now = time.time()
        expired = [
            tid
            for tid, t in self._tasks.items()
            if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
            and (now - t.updated_at) > self._ttl
        ]
        for tid in expired:
            del self._tasks[tid]


tracker = TaskTracker()


class ProgressAdapter:
    """Duck-type tqdm replacement that writes progress to TaskTracker.

    Implements the subset of tqdm's interface used by fetchers:
    .update(n), .set_description(desc), .total, context manager protocol.
    """

    def __init__(
        self,
        task_id: str,
        total: float = 0,
        desc: str = "",
        **_kwargs: object,
    ) -> None:
        self.task_id = task_id
        self._total = total
        self.n: float = 0.0
        tracker.update(
            task_id,
            status=TaskStatus.RUNNING,
            total=total,
            description=desc,
        )

    @property
    def total(self) -> float:
        return self._total

    @total.setter
    def total(self, value: float) -> None:
        self._total = value
        tracker.update(self.task_id, total=value)

    def update(self, n: float = 1) -> None:
        self.n += n
        progress = min(self.n / self._total, 1.0) if self._total > 0 else 0.0
        tracker.update(self.task_id, current=self.n, progress=progress)

    def set_description(self, desc: str, **_kwargs: object) -> None:
        tracker.update(self.task_id, description=desc)

    def close(self) -> None:
        pass

    def __enter__(self) -> ProgressAdapter:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
