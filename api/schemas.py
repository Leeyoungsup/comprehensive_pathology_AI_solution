"""
Pydantic schema definitions for the Folder Watcher API (Multi-Instance)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================================================
# Response Models
# ============================================================================

class InstanceConfig(BaseModel):
    """Instance configuration info."""
    watch_folder: str
    output_folder: str
    device: str = "cuda:0"
    tissue_type: str = "Other"
    auto_epithelial_classify: bool = False
    scan_interval_sec: int = 10


class DetectionCurrent(BaseModel):
    """Currently running detection info."""
    slide_path: str
    file_name: str
    started_at: str
    progress: int = 0
    message: str = ""
    elapsed_sec: float = 0.0


class DetectionHistoryItem(BaseModel):
    """Detection history entry."""
    file_name: str
    slide_path: str
    status: str
    total_cells: Optional[int] = None
    error: Optional[str] = None
    processing_time_sec: float = 0.0
    result_path: Optional[str] = None
    completed_at: str = ""


class DetectionInfo(BaseModel):
    """Detection state info."""
    is_running: bool = False
    current: Optional[DetectionCurrent] = None
    recent_history: List[DetectionHistoryItem] = Field(default_factory=list)


class SummaryInfo(BaseModel):
    """Slide processing summary."""
    total_slides: int = 0
    completed: int = 0
    pending: int = 0


class InstanceStatus(BaseModel):
    """Full status of a single watcher instance."""
    instance_id: str
    config: InstanceConfig
    watcher_running: bool = False
    detection: DetectionInfo = Field(default_factory=DetectionInfo)
    summary: SummaryInfo = Field(default_factory=SummaryInfo)


class SlideEntry(BaseModel):
    """Single slide entry from registry."""
    slide_path: str
    file_name: str
    ai_completed: bool = False
    ai_result_path: Optional[str] = None
    registered_at: Optional[str] = None
    completed_at: Optional[str] = None
    last_error: Optional[str] = None
    last_error_at: Optional[str] = None


class SlidesResponse(BaseModel):
    """Slides list response for an instance."""
    instance_id: str
    total: int = 0
    completed: int = 0
    pending: int = 0
    slides: List[SlideEntry] = Field(default_factory=list)


class CreateInstanceResponse(BaseModel):
    """Response after creating an instance."""
    status: str = "success"
    message: str = ""
    instance: InstanceStatus


class MessageResponse(BaseModel):
    """Simple message response."""
    status: str = "success"
    message: str = ""


class AllInstancesResponse(BaseModel):
    """List of all instances."""
    total_instances: int = 0
    instances: List[InstanceStatus] = Field(default_factory=list)
