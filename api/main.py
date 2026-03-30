"""
FastAPI main app (v3 - Multi-Instance)

Multiple folder watchers with per-instance GPU assignment.
Run: uvicorn api.main:app --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import torch
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# OpenSlide DLL path (Windows)
_openslide_lib = PROJECT_ROOT / "libs" / "openslide_lib"
if _openslide_lib.exists():
    import os

    os.add_dll_directory(str(_openslide_lib))
    os.environ["PATH"] = str(_openslide_lib) + os.pathsep + os.environ.get("PATH", "")
    _openslide_bin = _openslide_lib / "bin"
    if _openslide_bin.exists():
        os.add_dll_directory(str(_openslide_bin))
        os.environ["PATH"] = str(_openslide_bin) + os.pathsep + os.environ.get("PATH", "")

from api.folder_watcher import get_watcher_manager
from api.routers.detection import router as detection_router

# ============================================================================
# Server start time
# ============================================================================
_start_time: float = 0.0


def get_start_time() -> float:
    return _start_time


# ============================================================================
# Lifespan
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _start_time
    _start_time = time.time()

    print("=" * 60)
    print("  Pathology AI - Multi-Instance Watcher API")
    print("=" * 60)

    # GPU info
    if torch.cuda.is_available():
        n_gpus = torch.cuda.device_count()
        print(f"  GPUs available: {n_gpus}")
        for i in range(n_gpus):
            name = torch.cuda.get_device_name(i)
            props = torch.cuda.get_device_properties(i)
            total = getattr(props, "total_memory", 0) or getattr(props, "total_mem", 0)
            print(f"    cuda:{i} - {name} ({total / (1024**3):.1f} GB)")
    else:
        print("  GPU: Not available (CPU mode)")

    # Check model files
    model_dir = PROJECT_ROOT / "model"
    for name in ["HnE_detection.pt", "HnE_BR_segmentation.pt", "HnE_ST_segmentation.pt"]:
        path = model_dir / name
        status = "OK" if path.exists() else "NOT FOUND"
        print(f"  {name}: {status}")

    print("=" * 60)
    print("  Server ready! Docs: http://localhost:8001/docs")
    print()
    print("  Quick start:")
    print("    POST /api/v1/detection/instances")
    print("      instance_id=my_watcher")
    print("      watch_folder=C:/path/to/slides")
    print("      device=cuda:0")
    print("      tissue_type=Breast")
    print("=" * 60)

    yield

    # Shutdown
    print("Shutting down all instances...")
    manager = get_watcher_manager()
    manager.stop_all()
    print("Shutdown complete.")


# ============================================================================
# FastAPI App
# ============================================================================

app = FastAPI(
    title="Pathology AI - Multi-Instance Watcher API",
    description=(
        "Run multiple independent folder watchers, each with its own GPU device "
        "and tissue type. Automatically detects cells in WSI slides and saves results."
    ),
    version="3.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(detection_router, prefix="/api/v1")


@app.get("/", tags=["root"])
async def root():
    return {
        "name": "Pathology AI - Multi-Instance Watcher API",
        "version": "3.0.0",
        "docs": "/docs",
        "endpoints": {
            "create_instance": "POST /api/v1/detection/instances",
            "list_instances": "GET  /api/v1/detection/instances",
            "instance_status": "GET  /api/v1/detection/instances/{id}/status",
            "instance_slides": "GET  /api/v1/detection/instances/{id}/slides",
            "start_instance": "POST /api/v1/detection/instances/{id}/start",
            "stop_instance": "POST /api/v1/detection/instances/{id}/stop",
            "delete_instance": "DELETE /api/v1/detection/instances/{id}",
            "health": "GET  /api/v1/detection/health",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8002,
        reload=False,
        log_level="info",
    )
