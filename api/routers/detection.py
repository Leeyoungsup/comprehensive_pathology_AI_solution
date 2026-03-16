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
    TissueType,
)
from api.services.detection_api_service import get_detection_service

router = APIRouter(prefix="/detection", tags=["detection"])

# 업로드 파일 임시 디렉토리
UPLOAD_DIR = Path(tempfile.gettempdir()) / "pathology_api_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# OpenSlide 지원 파일 확장자
ALLOWED_EXTENSIONS = {
    ".svs", ".ndpi", ".vms", ".vmu", ".scn", ".mrxs",
    ".tiff", ".tif", ".svslide", ".bif",
    ".png", ".jpg", ".jpeg",
}
# Swagger UI 파일 선택 필터용
_ACCEPT_WSI = ",".join(sorted(ALLOWED_EXTENSIONS))

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


def _parse_roi_file(roi_file: Optional[UploadFile]) -> Optional[List[dict]]:
    """ROI JSON 파일 파싱"""
    if roi_file is None or roi_file.filename is None or roi_file.filename == "":
        return None
    try:
        content = roi_file.file.read().decode("utf-8")
        if not content.strip():
            return None
        roi = json.loads(content)
        # JSON 최상위가 dict이고 annotations 키가 있으면 추출
        if isinstance(roi, dict) and "annotations" in roi:
            roi = roi["annotations"]
        if not isinstance(roi, list):
            raise ValueError("ROI는 JSON 배열이어야 합니다.")
        return roi
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="INVALID_ROI",
                    message=f"ROI 파일 파싱 오류: {str(e)}",
                )
            ).model_dump(),
        )


def _save_result_json(response, output_path: str, file_name: str) -> str:
    """검출 결과를 데스크톱 앱 호환 JSON 포맷으로 저장

    데스크톱 앱의 load_detection_results()가 읽을 수 있는
    {"metadata": {...}, "result": {...}} 형식으로 저장합니다.

    Args:
        response: DetectionResponse 객체
        output_path: 폴더 경로 또는 .json 파일 경로
        file_name: 원본 슬라이드 파일명 (자동 파일명 생성용)

    Returns:
        실제 저장된 파일 경로 문자열
    """
    from datetime import datetime

    out = Path(output_path)

    # 폴더 지정인 경우 자동 파일명 생성
    if out.suffix.lower() != ".json":
        out.mkdir(parents=True, exist_ok=True)
        stem = Path(file_name).stem if file_name else "result"
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        out = out / f"{stem}_{timestamp}.json"
    else:
        out.parent.mkdir(parents=True, exist_ok=True)

    resp_data = response.model_dump()

    # 데스크톱 앱 호환 포맷으로 변환
    # cells: cls_name 제거 (데스크톱 앱은 cls_id만 사용)
    cells = [
        {"x": c["x"], "y": c["y"], "cls_id": c["cls_id"], "confidence": c["confidence"]}
        for c in resp_data.get("cells", [])
    ]

    data = {
        "metadata": {
            "model_type": "detection",
            "model_name": "HnE Cell Detection",
            "version": "1.0",
            "timestamp": datetime.now().isoformat(),
            "image_name": resp_data.get("metadata", {}).get("image_name"),
        },
        "result": {
            "status": "success",
            "num_cells": resp_data.get("summary", {}).get("total_cells", 0),
            "class_counts": resp_data.get("summary", {}).get("class_counts", {}),
            "cells": cells,
            "message": f"총 {resp_data.get('summary', {}).get('total_cells', 0)}개 세포 검출 완료",
        },
    }

    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return str(out)


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
    file: UploadFile = File(
        ...,
        description=f"WSI 파일 (지원 형식: {', '.join(sorted(ALLOWED_EXTENSIONS))})",
        media_type="application/octet-stream",
        openapi_extra={"accept": _ACCEPT_WSI},
    ),
    tissue_type: TissueType = Form(TissueType.OTHER, description="조직 타입 선택"),
    roi_file: Optional[UploadFile] = File(
        None,
        description="ROI JSON 파일 (.json)",
        openapi_extra={"accept": ".json"},
    ),
    confidence_threshold: float = Form(0.01, description="전역 confidence 임계값"),
    iou_threshold: float = Form(0.3, description="NMS IoU 임계값"),
    auto_epithelial_classify: bool = Form(True, description="Epithelial 자동 재분류 여부"),
    include_segmentation: bool = Form(False, description="Segmentation 마스크 포함 여부"),
    output_path: str = Form(
        ...,
        description="결과 JSON 저장 경로 (필수). 폴더 경로(예: C:\\results) 또는 파일 경로(예: C:\\results\\output.json). 폴더 지정 시 자동 파일명 생성",
    ),
    include_cells: bool = Form(False, description="API 응답에 cells 배열 포함 여부 (기본: summary만 반환, 파일에는 항상 전체 저장)"),
):
    # 입력 검증
    tissue_type = tissue_type.value
    confidence_threshold = _validate_threshold(confidence_threshold, "confidence_threshold")
    iou_threshold = _validate_threshold(iou_threshold, "iou_threshold")
    roi_list = _parse_roi_file(roi_file)

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
        # 결과 JSON 저장 (파일에는 항상 전체 cells 포함)
        try:
            saved = _save_result_json(response, output_path.strip(), file_name)
            response.saved_path = saved
        except OSError as e:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    error=ErrorDetail(
                        code="OUTPUT_PATH_ERROR",
                        message=f"결과 저장 실패: {e}",
                    )
                ).model_dump(),
            )

        # API 응답에서 cells 제외 (파일 저장 후 제거)
        if not include_cells:
            response.cells = []

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
