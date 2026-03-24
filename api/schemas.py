"""
Pydantic schema definitions
Request/response models for the HnE Cell Detection API
"""

from __future__ import annotations

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


# ============================================================================
# ROI related
# ============================================================================

class PolygonROI(BaseModel):
    """Polygon-shaped ROI"""
    type: str = "Polygon"
    coordinates: List[List[float]] = Field(..., description="Coordinate array in [[x1,y1],[x2,y2],...] format")


class RectangleROI(BaseModel):
    """Rectangle-shaped ROI"""
    type: str = "Rectangle"
    x: float
    y: float
    width: float
    height: float


ROIItem = Union[PolygonROI, RectangleROI]


# ============================================================================
# Cell results
# ============================================================================

class CellDetectionItem(BaseModel):
    """Individual detected cell"""
    x: float = Field(..., description="WSI level-0 X coordinate")
    y: float = Field(..., description="WSI level-0 Y coordinate")
    cls_id: int = Field(..., ge=0, le=7, description="Class ID (0-7)")
    cls_name: str = Field(..., description="Class name")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Detection confidence")


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
    7: "#00FF00",
}


class EpithelialBreakdown(BaseModel):
    """Epithelial reclassification details"""
    total_original_epithelial: int = 0
    reclassified_to_tumor: int = 0
    reclassified_to_benign: int = 0
    tumor_ratio: float = 0.0


class DetectionSummary(BaseModel):
    """Detection result summary"""
    total_cells: int = 0
    class_counts: Dict[str, int] = Field(
        default_factory=lambda: {name: 0 for name in CLASS_NAMES.values()}
    )
    epithelial_breakdown: Optional[EpithelialBreakdown] = None


class ImageMetadata(BaseModel):
    """Image metadata"""
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
    """Segmentation mask result"""
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
    """Detection success response"""
    status: str = "success"
    task_id: str = ""
    processing_time_sec: float = 0.0
    metadata: ImageMetadata = Field(default_factory=ImageMetadata)
    summary: DetectionSummary = Field(default_factory=DetectionSummary)
    cells: List[CellDetectionItem] = Field(default_factory=list)
    segmentation: Optional[SegmentationResult] = None
    saved_path: Optional[str] = Field(None, description="Result JSON save path (when output_path is specified)")



# ============================================================================
# Model Info
# ============================================================================

class ModelInfo(BaseModel):
    """Model information"""
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
    """Model list response"""
    models: List[ModelInfo] = Field(default_factory=list)


# ============================================================================
# Health
# ============================================================================

class GPUInfo(BaseModel):
    """GPU information"""
    available: bool = False
    device: Optional[str] = None
    memory_total_gb: Optional[float] = None
    memory_used_gb: Optional[float] = None
    cuda_version: Optional[str] = None


class HealthResponse(BaseModel):
    """Service status response"""
    status: str = "healthy"
    version: str = "1.0.0"
    gpu: GPUInfo = Field(default_factory=GPUInfo)
    models: Dict[str, Any] = Field(default_factory=dict)
    uptime_sec: float = 0.0


# ============================================================================
# Error
# ============================================================================

class ErrorDetail(BaseModel):
    """Error details"""
    code: str
    message: str
    detail: Optional[str] = None


class ErrorResponse(BaseModel):
    """Error response"""
    status: str = "error"
    error: ErrorDetail
