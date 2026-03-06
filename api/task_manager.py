"""
비동기 작업 관리자 (Task Manager)

PyQt5 QThread 대신 threading.Thread 기반으로 비동기 검출 작업을 관리합니다.
- 작업 생성, 상태 조회, 결과 조회, 취소 기능
- 동시 작업 수 제한 (GPU 메모리 고려)
- 작업 결과 TTL 기반 자동 정리
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
    """개별 작업 상태"""
    task_id: str
    status: TaskStatus = TaskStatus.QUEUED
    progress: int = 0
    current_step: str = ""
    steps: List[TaskStep] = field(default_factory=list)
    
    # 타이밍
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # 결과
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    
    # 취소 플래그
    is_cancelled: bool = False
    
    # 요청 파라미터 (결과 조회 시 metadata 구성용)
    request_params: Dict[str, Any] = field(default_factory=dict)
    
    # 워커 스레드 참조
    _thread: Optional[threading.Thread] = field(default=None, repr=False)

    @property
    def elapsed_sec(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.completed_at or datetime.now(timezone.utc)
        return (end - self.started_at).total_seconds()

    def get_default_steps(self) -> List[TaskStep]:
        """기본 작업 단계 목록"""
        return [
            TaskStep(name="슬라이드 로딩", status=StepStatus.PENDING),
            TaskStep(name="조직 영역 감지", status=StepStatus.PENDING),
            TaskStep(name="세포 검출", status=StepStatus.PENDING),
            TaskStep(name="Segmentation", status=StepStatus.PENDING),
            TaskStep(name="Epithelial 재분류", status=StepStatus.PENDING),
            TaskStep(name="결과 정리", status=StepStatus.PENDING),
        ]


# ============================================================================
# Task Manager
# ============================================================================

class TaskManager:
    """
    비동기 작업 관리자
    
    - 작업 큐잉 및 실행 스케줄링
    - 동시 실행 제한 (max_concurrent)
    - 작업 상태 추적 및 결과 저장
    - TTL 기반 결과 자동 정리
    """

    def __init__(self, max_concurrent: int = 2, result_ttl_sec: float = 86400):
        """
        Args:
            max_concurrent: 최대 동시 실행 작업 수
            result_ttl_sec: 완료된 작업 결과 보관 시간(초), 기본 24시간
        """
        self.max_concurrent = max_concurrent
        self.result_ttl_sec = result_ttl_sec
        
        self._tasks: OrderedDict[str, TaskState] = OrderedDict()
        self._lock = threading.Lock()
        self._queue: List[str] = []  # 대기 중인 task_id 목록
        
        # 작업 실행 함수 저장 (task_id → callable)
        self._task_runners: Dict[str, Callable] = {}
        
        # 정리 타이머
        self._cleanup_interval = 300  # 5분마다 정리
        self._start_cleanup_timer()

    def _start_cleanup_timer(self):
        """만료된 작업 정리 타이머 시작"""
        def _cleanup_loop():
            while True:
                time.sleep(self._cleanup_interval)
                self._cleanup_expired()
        
        t = threading.Thread(target=_cleanup_loop, daemon=True)
        t.start()

    def _cleanup_expired(self):
        """TTL이 지난 완료/실패/취소 작업 정리"""
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
        """고유 Task ID 생성"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = uuid.uuid4().hex[:8]
        return f"det_{timestamp}_{short_uuid}"

    def create_task(
        self,
        runner: Callable[[TaskState], None],
        request_params: Optional[Dict[str, Any]] = None,
    ) -> TaskState:
        """
        새 작업 생성 및 큐 등록
        
        Args:
            runner: 실행 함수 — runner(task_state) 시그니처
            request_params: 요청 파라미터 (metadata용)
        
        Returns:
            생성된 TaskState
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
        
        # 실행 가능하면 바로 시작
        self._try_start_next()
        
        return state

    def _try_start_next(self):
        """큐에서 다음 작업 시작 (동시 실행 제한 확인)"""
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
                
                # 워커 스레드 생성 및 시작
                thread = threading.Thread(
                    target=self._run_task,
                    args=(task_id, runner, state),
                    daemon=True,
                    name=f"task-{task_id}",
                )
                state._thread = thread
                thread.start()

    def _run_task(self, task_id: str, runner: Callable, state: TaskState):
        """워커 스레드에서 실행"""
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
            # 다음 대기 작업 시작
            self._try_start_next()

    def get_task(self, task_id: str) -> Optional[TaskState]:
        """작업 상태 조회"""
        with self._lock:
            return self._tasks.get(task_id)

    def cancel_task(self, task_id: str) -> bool:
        """
        작업 취소
        
        Returns:
            True: 취소 성공, False: 작업 없음
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
                # 처리 중인 경우 is_cancelled 플래그로 워커에게 알림
                # 워커가 주기적으로 체크하여 중단
                pass
            elif state.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                # 이미 완료된 작업이면 결과 삭제
                state.status = TaskStatus.CANCELLED
                state.result = None
            
            return True

    def delete_task(self, task_id: str) -> bool:
        """작업 및 결과 삭제"""
        with self._lock:
            state = self._tasks.get(task_id)
            if state is None:
                return False
            
            # 실행 중이면 먼저 취소
            if state.status == TaskStatus.PROCESSING:
                state.is_cancelled = True
            
            del self._tasks[task_id]
            self._task_runners.pop(task_id, None)
            if task_id in self._queue:
                self._queue.remove(task_id)
            
            return True

    @property
    def active_count(self) -> int:
        """현재 실행 중인 작업 수"""
        with self._lock:
            return sum(
                1 for s in self._tasks.values()
                if s.status == TaskStatus.PROCESSING
            )

    @property
    def queued_count(self) -> int:
        """대기 중인 작업 수"""
        with self._lock:
            return len(self._queue)

    @property
    def total_tasks(self) -> int:
        """전체 작업 수"""
        with self._lock:
            return len(self._tasks)
