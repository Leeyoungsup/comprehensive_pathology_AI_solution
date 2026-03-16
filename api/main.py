"""
FastAPI 메인 앱

HnE Cell Detection REST API 서버
실행: uvicorn api.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 프로젝트 루트를 sys.path에 추가 (ai 모듈 등 import 경로 보장)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# OpenSlide DLL 경로 (Windows)
_openslide_lib = PROJECT_ROOT / "libs" / "openslide_lib"
if _openslide_lib.exists():
    import os
    os.add_dll_directory(str(_openslide_lib))
    os.environ["PATH"] = str(_openslide_lib) + os.pathsep + os.environ.get("PATH", "")
    # DLL이 bin/ 하위에 있는 경우
    _openslide_bin = _openslide_lib / "bin"
    if _openslide_bin.exists():
        os.add_dll_directory(str(_openslide_bin))
        os.environ["PATH"] = str(_openslide_bin) + os.pathsep + os.environ.get("PATH", "")

from api.services.detection_api_service import get_detection_service
from api.routers.detection import router as detection_router

# ============================================================================
# 서버 시작 시간 (uptime 계산용)
# ============================================================================
_start_time: float = 0.0


def get_start_time() -> float:
    return _start_time


# ============================================================================
# Lifespan (startup / shutdown)
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 리소스 관리"""
    global _start_time
    _start_time = time.time()

    print("=" * 60)
    print("  HnE Cell Detection API Server Starting...")
    print("=" * 60)

    # Detection 모델 사전 로드
    service = get_detection_service()
    print(f"Device: {service.get_device_str()}")

    model_path = PROJECT_ROOT / "model" / "HnE_detection.pt"
    if model_path.exists():
        success = service.load_detection_model(str(model_path))
        if success:
            print(f"Detection 모델 로드 완료: {model_path.name}")
        else:
            print(f"Detection 모델 로드 실패: {model_path}")
    else:
        print(f"Detection 모델 파일 없음: {model_path}")
        print("  → /detection/analyze 호출 시 자동 로드 시도")

    # Segmentation 모델 파일 존재 확인
    for name in ["HnE_BR_segmentation.pt", "HnE_ST_segmentation.pt"]:
        seg_path = PROJECT_ROOT / "model" / name
        status = "✓" if seg_path.exists() else "✗"
        print(f"  {status} {name}")

    print("=" * 60)
    print("  Server ready!")
    print("  Docs: http://localhost:8000/docs")
    print("=" * 60)

    yield  # 앱 실행

    # Shutdown
    print("서버 종료 중...")
    service.unload_detection_model()
    print("모델 언로드 완료")


# ============================================================================
# FastAPI App
# ============================================================================

app = FastAPI(
    title="HnE Cell Detection API",
    description=(
        "H&E 염색 병리 이미지(WSI)에서 세포를 검출하고, "
        "Breast/Stomach 조직인 경우 Epithelial 세포를 Tumor/Benign으로 "
        "자동 재분류하는 REST API"
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록 (prefix: /api/v1)
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
# CLI 실행
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
