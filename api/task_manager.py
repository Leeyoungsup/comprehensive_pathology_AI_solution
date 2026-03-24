"""
Asynchronous Task Manager

Manages asynchronous detection tasks using threading.Thread instead of PyQt5 QThread.
- Task creation, status query, result retrieval, cancellation
- Concurrent task limit (considering GPU memory)
- Automatic cleanup of task results based on TTL
"""

from __future__ import annotations

import gc
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from api.schemas import TaskStatus, StepStatus, TaskStep


# ============================================================================
# Task Data Model
# ============================================================================

@dataclass
class TaskState:
    """Individual task state"""
    task_id: str
    status: TaskStatus = TaskStatus.QUEUED
    progress: int = 0
    current_step: str = ""
    steps: List[TaskStep] = field(default_factory=list)

    # Timing
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Results
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None

    # Cancellation flag
    is_cancelled: bool = False

    # Request parameters (for metadata composition on result retrieval)
    request_params: Dict[str, Any] = field(default_factory=dict)

    # Worker thread reference
    _thread: Optional[threading.Thread] = field(default=None, repr=False)

    @property
    def elapsed_sec(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.completed_at or datetime.now(timezone.utc)
        return (end - self.started_at).total_seconds()

    def get_default_steps(self) -> List[TaskStep]:
        """Default task step list"""
        return [
            TaskStep(name="Slide loading", status=StepStatus.PENDING),
            TaskStep(name="Tissue region detection", status=StepStatus.PENDING),
            TaskStep(name="Cell detection", status=StepStatus.PENDING),
            TaskStep(name="Segmentation", status=StepStatus.PENDING),
            TaskStep(name="Epithelial reclassification", status=StepStatus.PENDING),
            TaskStep(name="Result finalization", status=StepStatus.PENDING),
        ]


# ============================================================================
# Task Manager
# ============================================================================

class TaskManager:
    """
    Asynchronous task manager

    - Task queuing and execution scheduling
    - Concurrent execution limit (max_concurrent)
    - Task status tracking and result storage
    - TTL-based automatic result cleanup
    """

    def __init__(self, max_concurrent: int = 2, result_ttl_sec: float = 86400):
        """
        Args:
            max_concurrent: Maximum number of concurrent tasks
            result_ttl_sec: Retention time for completed task results (seconds), default 24 hours
        """
        self.max_concurrent = max_concurrent
        self.result_ttl_sec = result_ttl_sec

        self._tasks: OrderedDict[str, TaskState] = OrderedDict()
        self._lock = threading.Lock()
        self._queue: List[str] = []  # List of queued task_ids

        # Task runner function storage (task_id -> callable)
        self._task_runners: Dict[str, Callable] = {}

        # Cleanup timer
        self._cleanup_interval = 300  # Clean up every 5 minutes
        self._start_cleanup_timer()

    def _start_cleanup_timer(self):
        """Start timer for cleaning up expired tasks"""
        def _cleanup_loop():
            while True:
                time.sleep(self._cleanup_interval)
                self._cleanup_expired()

        t = threading.Thread(target=_cleanup_loop, daemon=True)
        t.start()

    def _cleanup_expired(self):
        """Clean up completed/failed/cancelled tasks past TTL"""
        now = datetime.now(timezone.utc)
        expired = []

        with self._lock:
            for task_id, state in self._tasks.items():
                if state.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    if state.completed_at:
                        age = (now - state.completed_at).total_seconds()
                        if age > self.result_ttl_sec:
                            expired.append(task_id)

            for task_id in expired:
                del self._tasks[task_id]
                self._task_runners.pop(task_id, None)

    def generate_task_id(self) -> str:
        """Generate unique Task ID"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = uuid.uuid4().hex[:8]
        return f"det_{timestamp}_{short_uuid}"

    def create_task(
        self,
        runner: Callable[[TaskState], None],
        request_params: Optional[Dict[str, Any]] = None,
    ) -> TaskState:
        """
        Create a new task and register it in the queue

        Args:
            runner: Execution function -- runner(task_state) signature
            request_params: Request parameters (for metadata)

        Returns:
            Created TaskState
        """
        task_id = self.generate_task_id()

        state = TaskState(
            task_id=task_id,
            status=TaskStatus.QUEUED,
            request_params=request_params or {},
        )
        state.steps = state.get_default_steps()

        with self._lock:
            self._tasks[task_id] = state
            self._task_runners[task_id] = runner
            self._queue.append(task_id)

        # Start immediately if possible
        self._try_start_next()

        return state

    def _try_start_next(self):
        """Start next task from queue (check concurrent execution limit)"""
        with self._lock:
            active_count = sum(
                1 for s in self._tasks.values()
                if s.status == TaskStatus.PROCESSING
            )

            while self._queue and active_count < self.max_concurrent:
                task_id = self._queue.pop(0)
                state = self._tasks.get(task_id)

                if state is None or state.is_cancelled:
                    continue

                runner = self._task_runners.get(task_id)
                if runner is None:
                    continue

                state.status = TaskStatus.PROCESSING
                state.started_at = datetime.now(timezone.utc)
                active_count += 1

                # Create and start worker thread
                thread = threading.Thread(
                    target=self._run_task,
                    args=(task_id, runner, state),
                    daemon=True,
                    name=f"task-{task_id}",
                )
                state._thread = thread
                thread.start()

    def _run_task(self, task_id: str, runner: Callable, state: TaskState):
        """Execute in worker thread"""
        try:
            runner(state)

            if state.is_cancelled:
                state.status = TaskStatus.CANCELLED
            elif state.status != TaskStatus.FAILED:
                state.status = TaskStatus.COMPLETED
                state.progress = 100

        except Exception as e:
            import traceback
            state.status = TaskStatus.FAILED
            state.error_message = str(e)
            state.error_code = "DETECTION_FAILED"
            print(f"Task {task_id} failed: {e}\n{traceback.format_exc()}")
        finally:
            state.completed_at = datetime.now(timezone.utc)
            # Start next queued task
            self._try_start_next()

    def get_task(self, task_id: str) -> Optional[TaskState]:
        """Query task status"""
        with self._lock:
            return self._tasks.get(task_id)

    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a task

        Returns:
            True: Cancellation successful, False: Task not found
        """
        with self._lock:
            state = self._tasks.get(task_id)
            if state is None:
                return False

            state.is_cancelled = True

            if state.status == TaskStatus.QUEUED:
                state.status = TaskStatus.CANCELLED
                state.completed_at = datetime.now(timezone.utc)
                if task_id in self._queue:
                    self._queue.remove(task_id)
            elif state.status == TaskStatus.PROCESSING:
                # For in-progress tasks, notify worker via is_cancelled flag
                # Worker checks periodically and interrupts
                pass
            elif state.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                # For already completed tasks, delete result
                state.status = TaskStatus.CANCELLED
                state.result = None

            return True

    def delete_task(self, task_id: str) -> bool:
        """Delete task and results"""
        with self._lock:
            state = self._tasks.get(task_id)
            if state is None:
                return False

            # Cancel first if running
            if state.status == TaskStatus.PROCESSING:
                state.is_cancelled = True

            del self._tasks[task_id]
            self._task_runners.pop(task_id, None)
            if task_id in self._queue:
                self._queue.remove(task_id)

            return True

    @property
    def active_count(self) -> int:
        """Number of currently running tasks"""
        with self._lock:
            return sum(
                1 for s in self._tasks.values()
                if s.status == TaskStatus.PROCESSING
            )

    @property
    def queued_count(self) -> int:
        """Number of queued tasks"""
        with self._lock:
            return len(self._queue)

    @property
    def total_tasks(self) -> int:
        """Total number of tasks"""
        with self._lock:
            return len(self._tasks)
