"""
Detection 라우터

HnE Cell Detection API의 엔드포인트를 정의합니다.
  - POST /analyze  : 세포 검출
  - GET  /status   : 현재 상태 확인
  - GET  /models   : 모델 목록
  - GET  /health   : 서비스 헬스 체크
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from api.schemas import (
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
)
from api.services.detection_api_service import get_detection_service

router = APIRouter(prefix="/detection", tags=["detection"])

# 업로드 파일 임시 디렉토리
UPLOAD_DIR = Path(tempfile.gettempdir()) / "pathology_api_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 지원 파일 확장자
ALLOWED_EXTENSIONS = {".svs", ".ndpi", ".tiff", ".tif", ".mrxs", ".scn",
                      ".vms", ".vmu", ".png", ".jpg", ".jpeg"}

# 최대 업로드 크기 (10 GB)
MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024


# ============================================================================
# 분석 상태 추적기
# ============================================================================

import threading
from datetime import datetime

_analysis_lock = threading.Lock()
_analysis_state: Dict = {
    "is_running": False,
    "current": None,      # 현재 진행 중인 분석 정보
    "last_completed": None,  # 마지막 완료된 분석 정보
    "total_analyses": 0,
    "total_cells_detected": 0,
}


def _start_analysis(file_name: str, tissue_type: str):
    """분석 시작 시 호출"""
    with _analysis_lock:
        _analysis_state["is_running"] = True
        _analysis_state["current"] = {
            "file_name": file_name,
            "tissue_type": tissue_type,
            "started_at": datetime.now().isoformat(),
        }


def _finish_analysis(file_name: str, tissue_type: str, total_cells: int,
                     processing_time: float, success: bool, error: Optional[str] = None):
    """분석 완료 시 호출"""
    with _analysis_lock:
        _analysis_state["is_running"] = False
        _analysis_state["current"] = None
        if success:
            _analysis_state["total_analyses"] += 1
            _analysis_state["total_cells_detected"] += total_cells
            _analysis_state["last_completed"] = {
                "file_name": file_name,
                "tissue_type": tissue_type,
                "completed_at": datetime.now().isoformat(),
                "processing_time_sec": round(processing_time, 2),
                "total_cells": total_cells,
            }
        else:
            _analysis_state["last_completed"] = {
                "file_name": file_name,
                "tissue_type": tissue_type,
                "completed_at": datetime.now().isoformat(),
                "status": "failed",
                "error": error,
            }


def _get_analysis_tracker() -> Dict:
    """현재 분석 상태 반환"""
    with _analysis_lock:
        result = {
            "is_running": _analysis_state["is_running"],
            "total_analyses": _analysis_state["total_analyses"],
            "total_cells_detected": _analysis_state["total_cells_detected"],
        }
        if _analysis_state["current"]:
            current = dict(_analysis_state["current"])
            started = datetime.fromisoformat(current["started_at"])
            current["elapsed_sec"] = round((datetime.now() - started).total_seconds(), 1)
            result["current"] = current
        else:
            result["current"] = None
        result["last_completed"] = _analysis_state["last_completed"]
        return result


# ============================================================================
# Helper
# ============================================================================

def _validate_tissue_type(tissue_type: Optional[str]) -> str:
    """Breast/Stomach 이외의 값은 모두 Other로 취급"""
    if tissue_type and tissue_type.strip() in {"Breast", "Stomach"}:
        return tissue_type.strip()
    return "Other"


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
# 1. 세포 검출
# ============================================================================

@router.post(
    "/analyze",
    response_model=DetectionResponse,
    summary="WSI 세포 검출",
    description="업로드된 WSI/이미지에서 세포를 검출하고, Breast/Stomach 조직은 Epithelial 재분류를 수행합니다.",
)
async def analyze(
    file: UploadFile = File(..., description="WSI 파일"),
    tissue_type: Optional[str] = Form(None, description="조직 타입: Breast, Stomach (미입력 시 Other)"),
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
    file_name = file.filename or "unknown"
    _start_analysis(file_name, tissue_type)
    start_time = time.time()

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
        task_id = uuid.uuid4().hex[:12]

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
        _finish_analysis(file_name, tissue_type,
                         result["summary"]["total_cells"],
                         result["processing_time_sec"], success=True)
        return response

    except FileNotFoundError as e:
        _finish_analysis(file_name, tissue_type, 0,
                         time.time() - start_time, success=False, error=str(e))
        raise HTTPException(
            status_code=422,
            detail=ErrorResponse(
                error=ErrorDetail(code="SLIDE_OPEN_FAILED", message=str(e))
            ).model_dump(),
        )
    except RuntimeError as e:
        err_str = str(e)
        _finish_analysis(file_name, tissue_type, 0,
                         time.time() - start_time, success=False, error=err_str)
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
        _finish_analysis(file_name, tissue_type, 0,
                         time.time() - start_time, success=False, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error=ErrorDetail(code="DETECTION_FAILED", message=str(e))
            ).model_dump(),
        )
    finally:
        _cleanup_upload(slide_path)


# ============================================================================
# 2. 현재 상태 확인
# ============================================================================

@router.get(
    "/status",
    summary="현재 서비스 상태 확인",
    description="현재 분석 진행 상태, 마지막 분석 결과, GPU 사용량 등 실시간 정보를 반환합니다.",
)
async def get_status():
    import torch
    from api.main import get_start_time

    service = get_detection_service()

    # GPU 실시간 메모리
    gpu = {}
    if torch.cuda.is_available():
        gpu["device"] = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        total_mem = getattr(props, 'total_memory', None) or getattr(props, 'total_mem', 0)
        gpu["memory_total_gb"] = round(total_mem / (1024**3), 2)
        gpu["memory_allocated_gb"] = round(torch.cuda.memory_allocated(0) / (1024**3), 2)
        gpu["memory_reserved_gb"] = round(torch.cuda.memory_reserved(0) / (1024**3), 2)
        free = total_mem - torch.cuda.memory_reserved(0)
        gpu["memory_free_gb"] = round(free / (1024**3), 2)
        gpu["utilization_percent"] = round(torch.cuda.memory_allocated(0) / total_mem * 100, 1) if total_mem > 0 else 0
    else:
        gpu["device"] = "CPU only"

    # 모델 로드 상태
    models = {
        "detection": {
            "loaded": service.is_detection_model_loaded,
            "file": "HnE_detection.pt",
        },
    }
    project_root = Path(__file__).resolve().parent.parent.parent
    for name, key in [("HnE_BR_segmentation.pt", "segmentation_breast"), ("HnE_ST_segmentation.pt", "segmentation_stomach")]:
        models[key] = {
            "available": (project_root / "model" / name).exists(),
            "file": name,
        }

    # 분석 이력
    analysis_info = _get_analysis_tracker()

    return {
        "server": {
            "status": "running",
            "version": "1.0.0",
            "uptime_sec": round(time.time() - get_start_time(), 1),
        },
        "gpu": gpu,
        "models": models,
        "analysis": analysis_info,
    }


# ============================================================================
# 3. 모델 목록
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
# 4. 헬스 체크
# ============================================================================

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="서비스 상태 확인",
)
async def health_check():
    import torch

    service = get_detection_service()

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
    )
