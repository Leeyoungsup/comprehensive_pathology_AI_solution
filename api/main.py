"""
FastAPI main app

HnE Cell Detection REST API server
Run: uvicorn api.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Add project root to sys.path (ensure import paths for ai modules, etc.)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# OpenSlide DLL path (Windows)
_openslide_lib = PROJECT_ROOT / "libs" / "openslide_lib"
if _openslide_lib.exists():
    import os
    os.add_dll_directory(str(_openslide_lib))
    os.environ["PATH"] = str(_openslide_lib) + os.pathsep + os.environ.get("PATH", "")
    # If DLLs are in a bin/ subdirectory
    _openslide_bin = _openslide_lib / "bin"
    if _openslide_bin.exists():
        os.add_dll_directory(str(_openslide_bin))
        os.environ["PATH"] = str(_openslide_bin) + os.pathsep + os.environ.get("PATH", "")

from api.services.detection_api_service import get_detection_service
from api.routers.detection import router as detection_router

# ============================================================================
# Server start time (for uptime calculation)
# ============================================================================
_start_time: float = 0.0


def get_start_time() -> float:
    return _start_time


# ============================================================================
# Lifespan (startup / shutdown)
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage resources on app startup/shutdown"""
    global _start_time
    _start_time = time.time()

    print("=" * 60)
    print("  HnE Cell Detection API Server Starting...")
    print("=" * 60)

    # Pre-load detection model
    service = get_detection_service()
    print(f"Device: {service.get_device_str()}")

    model_path = PROJECT_ROOT / "model" / "HnE_detection.pt"
    if model_path.exists():
        success = service.load_detection_model(str(model_path))
        if success:
            print(f"Detection model loaded: {model_path.name}")
        else:
            print(f"Failed to load detection model: {model_path}")
    else:
        print(f"Detection model file not found: {model_path}")
        print("  -> Will attempt auto-load on /detection/analyze call")

    # Check segmentation model file existence
    for name in ["HnE_BR_segmentation.pt", "HnE_ST_segmentation.pt"]:
        seg_path = PROJECT_ROOT / "model" / name
        status = "✓" if seg_path.exists() else "✗"
        print(f"  {status} {name}")

    print("=" * 60)
    print("  Server ready!")
    print("  Docs: http://localhost:8000/docs")
    print("=" * 60)

    yield  # App running

    # Shutdown
    print("Server shutting down...")
    service.unload_detection_model()
    print("Models unloaded")


# ============================================================================
# FastAPI App
# ============================================================================

app = FastAPI(
    title="HnE Cell Detection API",
    description=(
        "REST API for detecting cells in H&E-stained pathology images (WSI) "
        "and automatically reclassifying Epithelial cells as Tumor/Benign "
        "for Breast/Stomach tissue"
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register router (prefix: /api/v1)
app.include_router(detection_router, prefix="/api/v1")


# ============================================================================
# Root
# ============================================================================

@app.get("/", tags=["root"])
async def root():
    return {
        "name": "HnE Cell Detection API",
        "version": "1.0.0",
        "docs": "/docs",
        "api_prefix": "/api/v1",
    }


# ============================================================================
# CLI execution
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
