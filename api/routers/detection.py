"""
Detection 라우터

HnE Cell Detection API의 모든 엔드포인트를 정의합니다.
  - POST /analyze          : 동기 검출
  - POST /analyze/async    : 비동기 검출
  - GET  /tasks/{task_id}  : 작업 상태 조회
  - GET  /tasks/{task_id}/result : 작업 결과 조회
  - DELETE /tasks/{task_id}      : 작업 취소/삭제
  - GET  /models           : 모델 목록
  - GET  /health           : 서비스 상태
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from api.schemas import (
    AsyncAcceptedResponse,
    CellDetectionItem,
    CLASS_NAMES,
    DetectionResponse,
    DetectionSummary,
    EpithelialBreakdown,
    ErrorDetail,
    ErrorResponse,
    GPUInfo,
    HealthResponse,
    ImageMetadata,
    ModelInfo,
    ModelsResponse,
    SegmentationResult,
    StepStatus,
    TaskCancelResponse,
    TaskStatus,
    TaskStatusResponse,
    TaskStep,
    TissueType,
)
from api.task_manager import TaskManager, TaskState
from api.services.detection_api_service import get_detection_service

router = APIRouter(prefix="/detection", tags=["detection"])

# 전역 TaskManager — app lifespan에서 설정
_task_manager: Optional[TaskManager] = None

# 업로드 파일 임시 디렉토리
UPLOAD_DIR = Path(tempfile.gettempdir()) / "pathology_api_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 지원 파일 확장자
ALLOWED_EXTENSIONS = {".svs", ".ndpi", ".tiff", ".tif", ".mrxs", ".scn",
                      ".vms", ".vmu", ".png", ".jpg", ".jpeg"}

# 최대 업로드 크기 (10 GB)
MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024


def set_task_manager(tm: TaskManager):
    global _task_manager
    _task_manager = tm


def get_task_manager() -> TaskManager:
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager


# ============================================================================
# Helper
# ============================================================================

def _validate_tissue_type(tissue_type: str) -> str:
    valid = {"Breast", "Stomach", "Other"}
    if tissue_type not in valid:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="INVALID_TISSUE_TYPE",
                    message=f"잘못된 tissue_type: '{tissue_type}'. 허용: {valid}",
                )
            ).model_dump(),
        )
    return tissue_type


def _validate_threshold(value: float, name: str) -> float:
    if not (0.0 <= value <= 1.0):
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="INVALID_THRESHOLD",
                    message=f"{name} 값은 0.0~1.0 사이여야 합니다: {value}",
                )
            ).model_dump(),
        )
    return value


def _save_upload_file(file: UploadFile) -> Path:
    """업로드 파일을 임시 디렉토리에 저장"""
    ext = Path(file.filename or "uploaded").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="INVALID_FILE_FORMAT",
                    message=f"지원하지 않는 파일 형식: {ext}. 지원: {ALLOWED_EXTENSIONS}",
                )
            ).model_dump(),
        )

    tmp_dir = UPLOAD_DIR / f"upload_{int(time.time() * 1000)}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dest = tmp_dir / (file.filename or f"slide{ext}")

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    return dest


def _parse_roi(roi_str: Optional[str]) -> Optional[List[dict]]:
    """ROI JSON 문자열 파싱"""
    if not roi_str:
        return None
    try:
        roi = json.loads(roi_str)
        if not isinstance(roi, list):
            raise ValueError("ROI는 JSON 배열이어야 합니다.")
        return roi
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="INVALID_ROI",
                    message=f"ROI 파싱 오류: {str(e)}",
                )
            ).model_dump(),
        )


def _parse_class_thresholds(ct_str: Optional[str]) -> Optional[Dict[int, float]]:
    """클래스별 threshold JSON 파싱"""
    if not ct_str:
        return None
    try:
        raw = json.loads(ct_str)
        return {int(k): float(v) for k, v in raw.items()}
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="INVALID_THRESHOLD",
                    message=f"class_thresholds 파싱 오류: {str(e)}",
                )
            ).model_dump(),
        )


def _cleanup_upload(slide_path: Path):
    """업로드 임시 파일 정리"""
    try:
        parent = slide_path.parent
        if parent.exists() and str(UPLOAD_DIR) in str(parent):
            shutil.rmtree(parent, ignore_errors=True)
    except Exception:
        pass


# ============================================================================
# 1. 동기 검출
# ============================================================================

@router.post(
    "/analyze",
    response_model=DetectionResponse,
    summary="WSI 세포 검출 (동기)",
    description="ROI가 지정되었거나 소규모 이미지인 경우, 결과를 즉시 반환합니다.",
)
async def analyze_sync(
    file: UploadFile = File(..., description="WSI 파일"),
    tissue_type: str = Form(..., description="조직 타입: Breast, Stomach, Other"),
    roi: Optional[str] = Form(None, description="ROI JSON 배열"),
    confidence_threshold: float = Form(0.01, description="전역 confidence 임계값"),
    class_thresholds: Optional[str] = Form(None, description="클래스별 confidence 임계값 JSON"),
    iou_threshold: float = Form(0.35, description="NMS IoU 임계값"),
    auto_epithelial_classify: bool = Form(True, description="Epithelial 자동 재분류 여부"),
    include_segmentation: bool = Form(False, description="Segmentation 마스크 포함 여부"),
):
    # 입력 검증
    tissue_type = _validate_tissue_type(tissue_type)
    confidence_threshold = _validate_threshold(confidence_threshold, "confidence_threshold")
    iou_threshold = _validate_threshold(iou_threshold, "iou_threshold")
    roi_list = _parse_roi(roi)
    ct = _parse_class_thresholds(class_thresholds)

    # 파일 저장
    slide_path = _save_upload_file(file)

    try:
        service = get_detection_service()
        result = service.run_detection(
            slide_path=str(slide_path),
            tissue_type=tissue_type,
            roi_list=roi_list,
            confidence_threshold=confidence_threshold,
            class_thresholds=ct,
            iou_threshold=iou_threshold,
            auto_epithelial_classify=auto_epithelial_classify,
            include_segmentation=include_segmentation,
        )

        # 응답 구성
        tm = get_task_manager()
        task_id = tm.generate_task_id()

        response = DetectionResponse(
            status="success",
            task_id=task_id,
            processing_time_sec=result["processing_time_sec"],
            metadata=ImageMetadata(**result["metadata"]),
            summary=DetectionSummary(
                total_cells=result["summary"]["total_cells"],
                class_counts=result["summary"]["class_counts"],
                epithelial_breakdown=(
                    EpithelialBreakdown(**result["summary"]["epithelial_breakdown"])
                    if result["summary"].get("epithelial_breakdown")
                    else None
                ),
            ),
            cells=[CellDetectionItem(**c) for c in result["cells"]],
            segmentation=(
                SegmentationResult(**result["segmentation"])
                if result.get("segmentation")
                else None
            ),
        )
        return response

    except FileNotFoundError as e:
        raise HTTPException(
            status_code=422,
            detail=ErrorResponse(
                error=ErrorDetail(code="SLIDE_OPEN_FAILED", message=str(e))
            ).model_dump(),
        )
    except RuntimeError as e:
        err_str = str(e)
        if "out of memory" in err_str.lower():
            raise HTTPException(
                status_code=503,
                detail=ErrorResponse(
                    error=ErrorDetail(code="GPU_OUT_OF_MEMORY", message=err_str)
                ).model_dump(),
            )
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error=ErrorDetail(code="DETECTION_FAILED", message=err_str)
            ).model_dump(),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error=ErrorDetail(code="DETECTION_FAILED", message=str(e))
            ).model_dump(),
        )
    finally:
        _cleanup_upload(slide_path)


# ============================================================================
# 2. 비동기 검출
# ============================================================================

@router.post(
    "/analyze/async",
    response_model=AsyncAcceptedResponse,
    status_code=202,
    summary="WSI 세포 검출 (비동기)",
    description="대용량 WSI의 경우, 작업을 큐에 등록하고 task_id를 즉시 반환합니다.",
)
async def analyze_async(
    file: UploadFile = File(..., description="WSI 파일"),
    tissue_type: str = Form(..., description="조직 타입: Breast, Stomach, Other"),
    roi: Optional[str] = Form(None, description="ROI JSON 배열"),
    confidence_threshold: float = Form(0.01, description="전역 confidence 임계값"),
    class_thresholds: Optional[str] = Form(None, description="클래스별 confidence 임계값 JSON"),
    iou_threshold: float = Form(0.35, description="NMS IoU 임계값"),
    auto_epithelial_classify: bool = Form(True, description="Epithelial 자동 재분류 여부"),
    include_segmentation: bool = Form(False, description="Segmentation 마스크 포함 여부"),
    callback_url: Optional[str] = Form(None, description="완료 시 결과를 POST할 webhook URL"),
    priority: str = Form("normal", description="작업 우선순위: low, normal, high"),
):
    # 입력 검증
    tissue_type = _validate_tissue_type(tissue_type)
    confidence_threshold = _validate_threshold(confidence_threshold, "confidence_threshold")
    iou_threshold = _validate_threshold(iou_threshold, "iou_threshold")
    roi_list = _parse_roi(roi)
    ct = _parse_class_thresholds(class_thresholds)

    # 파일 저장 (비동기용 — 작업 완료 시 정리)
    slide_path = _save_upload_file(file)

    # 작업 실행 함수 정의
    def runner(state: TaskState):
        """백그라운드 스레드에서 실행"""
        try:
            service = get_detection_service()

            def progress_cb(pct: int, msg: str):
                if pct >= 0:
                    state.progress = pct
                state.current_step = msg
                # 단계 상태 업데이트
                _update_step_status(state, pct)

            def cancel_check() -> bool:
                return state.is_cancelled

            result = service.run_detection(
                slide_path=str(slide_path),
                tissue_type=tissue_type,
                roi_list=roi_list,
                confidence_threshold=confidence_threshold,
                class_thresholds=ct,
                iou_threshold=iou_threshold,
                auto_epithelial_classify=auto_epithelial_classify,
                include_segmentation=include_segmentation,
                progress_callback=progress_cb,
                cancel_check=cancel_check,
            )

            state.result = result

            # Webhook 콜백
            if callback_url:
                _send_webhook(callback_url, state)

        except InterruptedError:
            state.status = TaskStatus.CANCELLED
        except Exception as e:
            state.status = TaskStatus.FAILED
            state.error_message = str(e)
            state.error_code = "DETECTION_FAILED"

            if callback_url:
                _send_webhook_error(callback_url, state)
        finally:
            _cleanup_upload(slide_path)

    # 작업 등록
    tm = get_task_manager()
    task_state = tm.create_task(
        runner=runner,
        request_params={
            "tissue_type": tissue_type,
            "slide_name": file.filename,
            "priority": priority,
        },
    )

    base_url = "/api/v1/detection"
    return AsyncAcceptedResponse(
        status="accepted",
        task_id=task_state.task_id,
        message="작업이 큐에 등록되었습니다.",
        estimated_time_sec=120,
        poll_url=f"{base_url}/tasks/{task_state.task_id}",
        result_url=f"{base_url}/tasks/{task_state.task_id}/result",
    )


def _update_step_status(state: TaskState, pct: int):
    """진행률에 따라 step 상태 업데이트"""
    if not state.steps:
        return

    step_thresholds = [
        (1, 0),    # 슬라이드 로딩
        (5, 1),    # 조직 영역 감지
        (50, 2),   # 세포 검출
        (85, 3),   # Segmentation
        (95, 4),   # Epithelial 재분류
        (100, 5),  # 결과 정리
    ]

    current_idx = 0
    for threshold, idx in step_thresholds:
        if pct >= threshold:
            current_idx = idx

    for i, step in enumerate(state.steps):
        if i < current_idx:
            step.status = StepStatus.COMPLETED
        elif i == current_idx:
            step.status = StepStatus.PROCESSING
        else:
            step.status = StepStatus.PENDING


def _send_webhook(callback_url: str, state: TaskState):
    """완료 Webhook 전송"""
    try:
        import httpx
        payload = {
            "event": "task.completed",
            "task_id": state.task_id,
            "result_url": f"/api/v1/detection/tasks/{state.task_id}/result",
            "summary": {
                "total_cells": state.result.get("summary", {}).get("total_cells", 0)
                if state.result else 0,
                "processing_time_sec": state.result.get("processing_time_sec", 0)
                if state.result else 0,
            },
        }
        httpx.post(callback_url, json=payload, timeout=10)
    except Exception as e:
        print(f"Webhook 전송 실패: {e}")


def _send_webhook_error(callback_url: str, state: TaskState):
    """실패 Webhook 전송"""
    try:
        import httpx
        payload = {
            "event": "task.failed",
            "task_id": state.task_id,
            "error": {
                "code": state.error_code or "DETECTION_FAILED",
                "message": state.error_message or "Unknown error",
            },
        }
        httpx.post(callback_url, json=payload, timeout=10)
    except Exception as e:
        print(f"Webhook 전송 실패: {e}")


# ============================================================================
# 3. 작업 상태 조회
# ============================================================================

@router.get(
    "/tasks/{task_id}",
    response_model=TaskStatusResponse,
    summary="비동기 작업 상태 조회",
)
async def get_task_status(task_id: str):
    tm = get_task_manager()
    state = tm.get_task(task_id)

    if state is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error=ErrorDetail(code="TASK_NOT_FOUND", message="작업을 찾을 수 없습니다.")
            ).model_dump(),
        )

    elapsed = state.elapsed_sec
    # 예상 잔여 시간 계산
    estimated_remaining = None
    if state.progress > 0 and state.status == TaskStatus.PROCESSING:
        estimated_remaining = (elapsed / state.progress) * (100 - state.progress)

    return TaskStatusResponse(
        task_id=state.task_id,
        status=state.status,
        progress=state.progress,
        current_step=state.current_step,
        steps=state.steps,
        created_at=state.created_at.isoformat() if state.created_at else None,
        started_at=state.started_at.isoformat() if state.started_at else None,
        elapsed_sec=round(elapsed, 1),
        estimated_remaining_sec=round(estimated_remaining, 1) if estimated_remaining else None,
    )


# ============================================================================
# 4. 작업 결과 조회
# ============================================================================

@router.get(
    "/tasks/{task_id}/result",
    summary="비동기 작업 결과 조회",
)
async def get_task_result(task_id: str):
    tm = get_task_manager()
    state = tm.get_task(task_id)

    if state is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error=ErrorDetail(code="TASK_NOT_FOUND", message="작업을 찾을 수 없습니다.")
            ).model_dump(),
        )

    if state.status == TaskStatus.PROCESSING or state.status == TaskStatus.QUEUED:
        return JSONResponse(
            status_code=202,
            content={
                "status": "processing",
                "task_id": state.task_id,
                "progress": state.progress,
                "message": "작업이 아직 처리 중입니다.",
            },
        )

    if state.status == TaskStatus.FAILED:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code=state.error_code or "DETECTION_FAILED",
                    message=state.error_message or "검출 중 오류 발생",
                )
            ).model_dump(),
        )

    if state.status == TaskStatus.CANCELLED:
        return JSONResponse(
            status_code=200,
            content={
                "status": "cancelled",
                "task_id": state.task_id,
                "message": "작업이 취소되었습니다.",
            },
        )

    # COMPLETED
    if state.result is None:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error=ErrorDetail(code="DETECTION_FAILED", message="결과가 없습니다.")
            ).model_dump(),
        )

    result = state.result
    response_data = {
        "status": "success",
        "task_id": state.task_id,
        "processing_time_sec": result.get("processing_time_sec", 0),
        "metadata": result.get("metadata", {}),
        "summary": result.get("summary", {}),
        "cells": result.get("cells", []),
        "segmentation": result.get("segmentation"),
    }

    return JSONResponse(status_code=200, content=response_data)


# ============================================================================
# 5. 작업 취소/삭제
# ============================================================================

@router.delete(
    "/tasks/{task_id}",
    response_model=TaskCancelResponse,
    summary="작업 취소 / 결과 삭제",
)
async def cancel_task(task_id: str):
    tm = get_task_manager()
    success = tm.cancel_task(task_id)

    if not success:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error=ErrorDetail(code="TASK_NOT_FOUND", message="작업을 찾을 수 없습니다.")
            ).model_dump(),
        )

    return TaskCancelResponse(
        status="cancelled",
        task_id=task_id,
        message="작업이 취소되었습니다.",
    )


# ============================================================================
# 6. 모델 목록
# ============================================================================

@router.get(
    "/models",
    response_model=ModelsResponse,
    summary="사용 가능한 모델 목록",
)
async def list_models():
    service = get_detection_service()
    models = service.get_model_info()
    return ModelsResponse(models=[ModelInfo(**m) for m in models])


# ============================================================================
# 7. 서비스 상태
# ============================================================================

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="서비스 상태 확인",
)
async def health_check():
    import torch

    service = get_detection_service()
    tm = get_task_manager()

    # GPU 정보
    gpu_info = GPUInfo(available=torch.cuda.is_available())
    if torch.cuda.is_available():
        gpu_info.device = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        total_mem = getattr(props, 'total_memory', None) or getattr(props, 'total_mem', 0)
        gpu_info.memory_total_gb = round(total_mem / (1024**3), 1)
        gpu_info.memory_used_gb = round(torch.cuda.memory_allocated(0) / (1024**3), 1)
        gpu_info.cuda_version = torch.version.cuda

    # 모델 상태
    from pathlib import Path
    project_root = Path(__file__).resolve().parent.parent.parent
    models_status = {
        "detection_loaded": service.is_detection_model_loaded,
        "segmentation_breast_available": (project_root / "model" / "HnE_BR_segmentation.pt").exists(),
        "segmentation_stomach_available": (project_root / "model" / "HnE_ST_segmentation.pt").exists(),
    }

    # Uptime
    from api.main import get_start_time
    uptime = time.time() - get_start_time()

    return HealthResponse(
        status="healthy",
        version="1.0.0",
        gpu=gpu_info,
        models=models_status,
        uptime_sec=round(uptime, 1),
        active_tasks=tm.active_count,
        queued_tasks=tm.queued_count,
    )
