"""
Pydantic 스키마 정의
HnE Cell Detection API의 요청/응답 모델
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


# ============================================================================
# Enums
# ============================================================================

class TissueType(str, Enum):
    BREAST = "Breast"
    STOMACH = "Stomach"
    OTHER = "Other"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


# ============================================================================
# ROI 관련
# ============================================================================

class PolygonROI(BaseModel):
    """폴리곤 형태의 ROI"""
    type: str = "Polygon"
    coordinates: List[List[float]] = Field(..., description="[[x1,y1],[x2,y2],...] 형태의 좌표 배열")


class RectangleROI(BaseModel):
    """사각형 형태의 ROI"""
    type: str = "Rectangle"
    x: float
    y: float
    width: float
    height: float


ROIItem = Union[PolygonROI, RectangleROI]


# ============================================================================
# Cell 결과
# ============================================================================

class CellDetectionItem(BaseModel):
    """개별 검출 세포"""
    x: float = Field(..., description="WSI level-0 X 좌표")
    y: float = Field(..., description="WSI level-0 Y 좌표")
    cls_id: int = Field(..., ge=0, le=7, description="클래스 ID (0-7)")
    cls_name: str = Field(..., description="클래스명")
    confidence: float = Field(..., ge=0.0, le=1.0, description="검출 confidence")


# ============================================================================
# Summary
# ============================================================================

CLASS_NAMES = {
    0: "Neutrophil",
    1: "Epithelial",
    2: "Lymphocyte",
    3: "Plasma",
    4: "Eosinophil",
    5: "Connective tissue",
    6: "Tumor Epithelial",
    7: "Benign Epithelial",
}

CLASS_COLORS = {
    0: "#FF4500",
    1: "#00FF00",
    2: "#0000FF",
    3: "#FFFF00",
    4: "#8A2BE2",
    5: "#808080",
    6: "#FF0000",
    7: "#00BFFF",
}


class EpithelialBreakdown(BaseModel):
    """Epithelial 재분류 상세"""
    total_original_epithelial: int = 0
    reclassified_to_tumor: int = 0
    reclassified_to_benign: int = 0
    tumor_ratio: float = 0.0


class DetectionSummary(BaseModel):
    """검출 결과 요약"""
    total_cells: int = 0
    class_counts: Dict[str, int] = Field(
        default_factory=lambda: {name: 0 for name in CLASS_NAMES.values()}
    )
    epithelial_breakdown: Optional[EpithelialBreakdown] = None


class ImageMetadata(BaseModel):
    """이미지 메타데이터"""
    image_name: str = ""
    image_dimensions: List[int] = Field(default_factory=lambda: [0, 0])
    mpp: float = 0.25
    tissue_type: str = ""
    model_name: str = "HnE_detection"
    model_version: str = "YOLOv11m"
    auto_epithelial_classify: bool = True
    roi_applied: bool = False


# ============================================================================
# Segmentation
# ============================================================================

class SegmentationResult(BaseModel):
    """Segmentation 마스크 결과"""
    mask_shape: List[int] = Field(default_factory=list)
    output_mpp: float = 4.0
    wsi_mpp: float = 0.25
    region_offset: List[int] = Field(default_factory=lambda: [0, 0])
    class_names: List[str] = Field(
        default_factory=lambda: ["Background", "Stroma", "Non_Tumor", "Tumor"]
    )
    class_polygons: Optional[Dict[str, Any]] = None
    polygon_coordinate_system: str = "wsi_level0"


# ============================================================================
# Response Models
# ============================================================================

class DetectionResponse(BaseModel):
    """동기 검출 성공 응답"""
    status: str = "success"
    task_id: str = ""
    processing_time_sec: float = 0.0
    metadata: ImageMetadata = Field(default_factory=ImageMetadata)
    summary: DetectionSummary = Field(default_factory=DetectionSummary)
    cells: List[CellDetectionItem] = Field(default_factory=list)
    segmentation: Optional[SegmentationResult] = None


class AsyncAcceptedResponse(BaseModel):
    """비동기 작업 접수 응답"""
    status: str = "accepted"
    task_id: str = ""
    message: str = "작업이 큐에 등록되었습니다."
    estimated_time_sec: Optional[float] = None
    poll_url: str = ""
    result_url: str = ""


# ============================================================================
# Task Status
# ============================================================================

class TaskStep(BaseModel):
    """작업 단계"""
    name: str
    status: StepStatus = StepStatus.PENDING
    progress: Optional[int] = None


class TaskStatusResponse(BaseModel):
    """작업 상태 조회 응답"""
    task_id: str
    status: TaskStatus
    progress: int = 0
    current_step: str = ""
    steps: List[TaskStep] = Field(default_factory=list)
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    elapsed_sec: float = 0.0
    estimated_remaining_sec: Optional[float] = None


class TaskCancelResponse(BaseModel):
    """작업 취소 응답"""
    status: str = "cancelled"
    task_id: str = ""
    message: str = "작업이 취소되었습니다."


# ============================================================================
# Model Info
# ============================================================================

class ModelInfo(BaseModel):
    """모델 정보"""
    id: str
    name: str
    version: str
    file: str
    num_classes: int
    classes: List[str]
    input_size: Optional[int] = None
    patch_size_level0: Optional[int] = None
    output_mpp: Optional[float] = None
    loaded: bool = False
    device: Optional[str] = None


class ModelsResponse(BaseModel):
    """모델 목록 응답"""
    models: List[ModelInfo] = Field(default_factory=list)


# ============================================================================
# Health
# ============================================================================

class GPUInfo(BaseModel):
    """GPU 정보"""
    available: bool = False
    device: Optional[str] = None
    memory_total_gb: Optional[float] = None
    memory_used_gb: Optional[float] = None
    cuda_version: Optional[str] = None


class HealthResponse(BaseModel):
    """서비스 상태 응답"""
    status: str = "healthy"
    version: str = "1.0.0"
    gpu: GPUInfo = Field(default_factory=GPUInfo)
    models: Dict[str, Any] = Field(default_factory=dict)
    uptime_sec: float = 0.0
    active_tasks: int = 0
    queued_tasks: int = 0


# ============================================================================
# Error
# ============================================================================

class ErrorDetail(BaseModel):
    """에러 상세"""
    code: str
    message: str
    detail: Optional[str] = None


class ErrorResponse(BaseModel):
    """에러 응답"""
    status: str = "error"
    error: ErrorDetail
