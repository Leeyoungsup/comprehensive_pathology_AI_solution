"""
Detection Router

Defines endpoints for the HnE Cell Detection API.
  - POST /analyze  : Cell detection
  - GET  /status   : Current status check
  - GET  /models   : Model list
  - GET  /health   : Service health check
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

# Temporary directory for uploaded files
UPLOAD_DIR = Path(tempfile.gettempdir()) / "pathology_api_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# OpenSlide supported file extensions
ALLOWED_EXTENSIONS = {
    ".svs", ".ndpi", ".vms", ".vmu", ".scn", ".mrxs",
    ".tiff", ".tif", ".svslide", ".bif",
    ".png", ".jpg", ".jpeg",
}
# Swagger UI file selection filter
_ACCEPT_WSI = ",".join(sorted(ALLOWED_EXTENSIONS))

# Maximum upload size (10 GB)
MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024


# ============================================================================
# Analysis status tracker
# ============================================================================

import threading
from datetime import datetime

_analysis_lock = threading.Lock()
_analysis_state: Dict = {
    "is_running": False,
    "current": None,      # Currently running analysis info
    "last_completed": None,  # Last completed analysis info
    "total_analyses": 0,
    "total_cells_detected": 0,
}


def _start_analysis(file_name: str, tissue_type: str):
    """Called when analysis starts"""
    with _analysis_lock:
        _analysis_state["is_running"] = True
        _analysis_state["current"] = {
            "file_name": file_name,
            "tissue_type": tissue_type,
            "started_at": datetime.now().isoformat(),
        }


def _finish_analysis(file_name: str, tissue_type: str, total_cells: int,
                     processing_time: float, success: bool, error: Optional[str] = None):
    """Called when analysis completes"""
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
    """Return current analysis status"""
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
                    message=f"{name} must be between 0.0 and 1.0: {value}",
                )
            ).model_dump(),
        )
    return value


def _save_upload_file(file: UploadFile) -> Path:
    """Save uploaded file to temporary directory"""
    ext = Path(file.filename or "uploaded").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="INVALID_FILE_FORMAT",
                    message=f"Unsupported file format: {ext}. Supported: {ALLOWED_EXTENSIONS}",
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
    """Parse ROI JSON file"""
    if roi_file is None or roi_file.filename is None or roi_file.filename == "":
        return None
    try:
        content = roi_file.file.read().decode("utf-8")
        if not content.strip():
            return None
        roi = json.loads(content)
        # If top-level JSON is dict with annotations key, extract it
        if isinstance(roi, dict) and "annotations" in roi:
            roi = roi["annotations"]
        if not isinstance(roi, list):
            raise ValueError("ROI must be a JSON array.")
        return roi
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="INVALID_ROI",
                    message=f"ROI file parsing error: {str(e)}",
                )
            ).model_dump(),
        )


def _save_result_json(response, output_path: str, file_name: str) -> str:
    """Save detection results in desktop app compatible JSON format

    Saves in {"metadata": {...}, "result": {...}} format that can be
    read by the desktop app's load_detection_results().

    Args:
        response: DetectionResponse object
        output_path: Folder path or .json file path
        file_name: Original slide file name (for auto filename generation)

    Returns:
        Actual saved file path string
    """
    from datetime import datetime

    out = Path(output_path)

    # Auto-generate filename if folder is specified
    if out.suffix.lower() != ".json":
        out.mkdir(parents=True, exist_ok=True)
        stem = Path(file_name).stem if file_name else "result"
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        out = out / f"{stem}_{timestamp}.json"
    else:
        out.parent.mkdir(parents=True, exist_ok=True)

    resp_data = response.model_dump()

    # Convert to desktop app compatible format
    # cells: remove cls_name (desktop app uses cls_id only)
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
            "message": f"Detection complete: {resp_data.get('summary', {}).get('total_cells', 0)} cells detected",
        },
    }

    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return str(out)


def _cleanup_upload(slide_path: Path):
    """Clean up temporary uploaded files"""
    try:
        parent = slide_path.parent
        if parent.exists() and str(UPLOAD_DIR) in str(parent):
            shutil.rmtree(parent, ignore_errors=True)
    except Exception:
        pass


# ============================================================================
# 1. Cell detection
# ============================================================================

@router.post(
    "/analyze",
    response_model=DetectionResponse,
    summary="WSI cell detection",
    description="Detects cells from uploaded WSI/images and performs Epithelial reclassification for Breast/Stomach tissue.",
)
async def analyze(
    file: UploadFile = File(
        ...,
        description=f"WSI file (supported formats: {', '.join(sorted(ALLOWED_EXTENSIONS))})",
        media_type="application/octet-stream",
        openapi_extra={"accept": _ACCEPT_WSI},
    ),
    tissue_type: TissueType = Form(TissueType.OTHER, description="Tissue type selection"),
    roi_file: Optional[UploadFile] = File(
        None,
        description="ROI JSON file (.json)",
        openapi_extra={"accept": ".json"},
    ),
    confidence_threshold: float = Form(0.01, description="Global confidence threshold"),
    iou_threshold: float = Form(0.3, description="NMS IoU threshold"),
    auto_epithelial_classify: bool = Form(True, description="Whether to auto-reclassify Epithelial cells"),
    include_segmentation: bool = Form(False, description="Whether to include segmentation mask"),
    output_path: str = Form(
        ...,
        description="Result JSON save path (required). Folder path (e.g., C:\\results) or file path (e.g., C:\\results\\output.json). Auto filename generated for folder paths",
    ),
    include_cells: bool = Form(False, description="Whether to include cells array in API response (default: summary only, full data always saved to file)"),
):
    # Input validation
    tissue_type = tissue_type.value
    confidence_threshold = _validate_threshold(confidence_threshold, "confidence_threshold")
    iou_threshold = _validate_threshold(iou_threshold, "iou_threshold")
    roi_list = _parse_roi_file(roi_file)

    # Save file
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

        # Build response
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
        # Save result JSON (file always includes full cells)
        try:
            saved = _save_result_json(response, output_path.strip(), file_name)
            response.saved_path = saved
        except OSError as e:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    error=ErrorDetail(
                        code="OUTPUT_PATH_ERROR",
                        message=f"Failed to save results: {e}",
                    )
                ).model_dump(),
            )

        # Exclude cells from API response (remove after file save)
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
# 2. Current status check
# ============================================================================

@router.get(
    "/status",
    summary="Check current service status",
    description="Returns real-time information including current analysis progress, last analysis results, GPU usage, etc.",
)
async def get_status():
    import torch
    from api.main import get_start_time

    service = get_detection_service()

    # Real-time GPU memory
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

    # Model load status
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

    # Analysis history
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
# 3. Model list
# ============================================================================

@router.get(
    "/models",
    response_model=ModelsResponse,
    summary="Available model list",
)
async def list_models():
    service = get_detection_service()
    models = service.get_model_info()
    return ModelsResponse(models=[ModelInfo(**m) for m in models])


# ============================================================================
# 4. Health check
# ============================================================================

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check",
)
async def health_check():
    import torch

    service = get_detection_service()

    # GPU information
    gpu_info = GPUInfo(available=torch.cuda.is_available())
    if torch.cuda.is_available():
        gpu_info.device = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        total_mem = getattr(props, 'total_memory', None) or getattr(props, 'total_mem', 0)
        gpu_info.memory_total_gb = round(total_mem / (1024**3), 1)
        gpu_info.memory_used_gb = round(torch.cuda.memory_allocated(0) / (1024**3), 1)
        gpu_info.cuda_version = torch.version.cuda

    # Model status
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
