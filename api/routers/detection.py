"""
Detection Router (v3 - Multi-Instance)

Manages multiple independent folder watcher instances.
Each instance has its own folder, GPU device, and tissue type.

  - POST   /instances              : Create a new watcher instance
  - GET    /instances              : List all instances
  - GET    /instances/{id}/status  : Instance status (detection progress)
  - GET    /instances/{id}/slides  : Instance slide list (AI results)
  - POST   /instances/{id}/start   : Start instance watcher
  - POST   /instances/{id}/stop    : Stop instance watcher
  - DELETE /instances/{id}         : Delete instance (free GPU)
  - GET    /health                 : Server health check
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.folder_watcher import get_watcher_manager
from api.schemas import (
    AllInstancesResponse,
    CreateInstanceResponse,
    InstanceStatus,
    MessageResponse,
    SlideEntry,
    SlidesResponse,
)

router = APIRouter(prefix="/detection", tags=["detection"])


# ============================================================================
# Helper
# ============================================================================

def _get_instance_or_404(instance_id: str):
    manager = get_watcher_manager()
    instance = manager.get_instance(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found.")
    return instance


# ============================================================================
# 1. Create instance
# ============================================================================

@router.post(
    "/instances",
    response_model=CreateInstanceResponse,
    summary="Create a new watcher instance",
    description=(
        "Create an independent folder watcher with its own GPU and tissue type.\n\n"
        "**Examples:**\n"
        "- Breast on GPU 0: `instance_id=breast_gpu0, device=cuda:0, tissue_type=Breast`\n"
        "- Stomach on GPU 1: `instance_id=stomach_gpu1, device=cuda:1, tissue_type=Stomach`\n"
        "- CPU-only: `device=cpu`"
    ),
)
async def create_instance(
    instance_id: str = Query(
        ..., description="Unique instance ID (e.g. 'breast_gpu0', 'stomach_gpu1')",
    ),
    watch_folder: str = Query(
        ..., description="Folder path to watch (e.g. C:/slides/breast)",
    ),
    output_folder: str = Query(
        None, description="Result output folder (default: watch_folder/ai_results)",
    ),
    device: str = Query(
        "cuda:0", description="GPU device (cuda:0, cuda:1, cpu, ...)",
    ),
    tissue_type: str = Query(
        "Other", description="Tissue type: Breast / Stomach / Other",
    ),
    auto_epithelial_classify: bool = Query(
        False, description="Auto-reclassify Epithelial as Tumor/Benign (requires Breast or Stomach)",
    ),
    scan_interval: int = Query(
        10, ge=5, le=3600, description="Scan interval in seconds",
    ),
    auto_start: bool = Query(
        True, description="Start watching immediately",
    ),
):
    manager = get_watcher_manager()

    # Auto-enable epithelial classify for Breast/Stomach
    if tissue_type in ("Breast", "Stomach"):
        auto_epithelial_classify = True

    try:
        watcher = manager.create_instance(
            instance_id=instance_id,
            watch_folder=watch_folder,
            output_folder=output_folder,
            device=device,
            tissue_type=tissue_type,
            auto_epithelial_classify=auto_epithelial_classify,
            scan_interval=scan_interval,
            auto_start=auto_start,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return CreateInstanceResponse(
        status="success",
        message=f"Instance '{instance_id}' created (device={device}, tissue={tissue_type})"
                + (" - watching" if auto_start else ""),
        instance=watcher.get_status(),
    )


# ============================================================================
# 2. List all instances
# ============================================================================

@router.get(
    "/instances",
    response_model=AllInstancesResponse,
    summary="List all watcher instances",
)
async def list_instances():
    manager = get_watcher_manager()
    statuses = manager.list_instances()
    return AllInstancesResponse(
        total_instances=len(statuses),
        instances=statuses,
    )


# ============================================================================
# 3. Instance status
# ============================================================================

@router.get(
    "/instances/{instance_id}/status",
    response_model=InstanceStatus,
    summary="Get instance status",
    description="Returns watcher state, detection progress, and slide summary.",
)
async def get_instance_status(instance_id: str):
    watcher = _get_instance_or_404(instance_id)
    return watcher.get_status()


# ============================================================================
# 4. Instance slides
# ============================================================================

@router.get(
    "/instances/{instance_id}/slides",
    response_model=SlidesResponse,
    summary="List slides for an instance",
    description="Returns all registered slides with AI completion status and result paths.",
)
async def get_instance_slides(instance_id: str):
    watcher = _get_instance_or_404(instance_id)
    slides = watcher.get_slides()
    completed = sum(1 for s in slides if s.get("ai_completed"))
    return SlidesResponse(
        instance_id=instance_id,
        total=len(slides),
        completed=completed,
        pending=len(slides) - completed,
        slides=[SlideEntry(**s) for s in slides],
    )


# ============================================================================
# 5. Start instance
# ============================================================================

@router.post(
    "/instances/{instance_id}/start",
    response_model=MessageResponse,
    summary="Start instance watcher",
)
async def start_instance(instance_id: str):
    watcher = _get_instance_or_404(instance_id)
    if watcher.is_running:
        return MessageResponse(message=f"Instance '{instance_id}' is already running.")
    watcher.start()
    return MessageResponse(message=f"Instance '{instance_id}' started.")


# ============================================================================
# 6. Stop instance
# ============================================================================

@router.post(
    "/instances/{instance_id}/stop",
    response_model=MessageResponse,
    summary="Stop instance watcher",
)
async def stop_instance(instance_id: str):
    watcher = _get_instance_or_404(instance_id)
    if not watcher.is_running:
        return MessageResponse(message=f"Instance '{instance_id}' is already stopped.")
    watcher.stop()
    return MessageResponse(message=f"Instance '{instance_id}' stopped.")


# ============================================================================
# 7. Delete instance
# ============================================================================

@router.delete(
    "/instances/{instance_id}",
    response_model=MessageResponse,
    summary="Delete instance (stop + free GPU memory)",
)
async def delete_instance(instance_id: str):
    manager = get_watcher_manager()
    if not manager.delete_instance(instance_id):
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found.")
    return MessageResponse(message=f"Instance '{instance_id}' deleted. GPU memory released.")


# ============================================================================
# 8. Health check
# ============================================================================

@router.get(
    "/health",
    summary="Server health check",
)
async def health_check():
    import time

    import torch

    from api.main import get_start_time

    manager = get_watcher_manager()

    # GPU info
    gpus = []
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            total_mem = getattr(props, "total_memory", None) or getattr(props, "total_mem", 0)
            gpus.append({
                "device": f"cuda:{i}",
                "name": torch.cuda.get_device_name(i),
                "memory_total_gb": round(total_mem / (1024**3), 2),
                "memory_allocated_gb": round(torch.cuda.memory_allocated(i) / (1024**3), 2),
                "memory_free_gb": round(
                    (total_mem - torch.cuda.memory_reserved(i)) / (1024**3), 2
                ),
            })
    else:
        gpus.append({"device": "cpu", "name": "CPU only"})

    return {
        "status": "healthy",
        "version": "3.0.0",
        "uptime_sec": round(time.time() - get_start_time(), 1),
        "gpus": gpus,
        "total_instances": manager.instance_count,
        "instances": [
            {
                "id": s["instance_id"],
                "device": s["config"]["device"],
                "tissue_type": s["config"]["tissue_type"],
                "running": s["watcher_running"],
                "detecting": s["detection"]["is_running"],
                "slides": s["summary"],
            }
            for s in manager.list_instances()
        ],
    }
