"""
MeDICus Studio SaaS — FastAPI Backend
WSI 타일 서빙 + AI 분석 API
"""

import os
import sys
import logging
from pathlib import Path
from contextlib import asynccontextmanager


# ── 200 OK 로그 숨기기 (에러만 출력) ──
class _SuccessFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        # 정상 응답(2xx, 3xx)은 숨기고 에러(4xx, 5xx)만 출력
        if "HTTP/1.1" in msg:
            for code in ("200", "204", "304"):
                if f'" {code}' in msg:
                    return False
        return True


logging.getLogger("uvicorn.access").addFilter(_SuccessFilter())

# ── OpenSlide DLL 경로 설정 (import 전에 실행해야 함) ──
PROJECT_ROOT = Path(__file__).parent.parent.parent
_dll_paths = [
    PROJECT_ROOT / "libs" / "openslide_lib" / "bin",
    PROJECT_ROOT / "libs",
]
for _dp in _dll_paths:
    if _dp.exists():
        os.environ['OPENSLIDE_PATH'] = str(_dp)
        break
_path_additions = [
    str(p) for p in _dll_paths
    if p.exists() and str(p) not in os.environ.get('PATH', '')
]
if _path_additions:
    os.environ['PATH'] = os.pathsep.join(_path_additions) + os.pathsep + os.environ.get('PATH', '')
for _dp in _dll_paths:
    if _dp.exists():
        try:
            os.add_dll_directory(str(_dp))
        except (AttributeError, OSError):
            pass

# AI 모듈 경로 추가 (기존 ai/ 코드 재사용)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import slides, tiles, ai


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 리소스 관리"""
    # 디렉토리 생성
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(settings.TILES_DIR, exist_ok=True)
    print(f"[MeDICus SaaS] Upload dir: {settings.UPLOAD_DIR}")
    print(f"[MeDICus SaaS] Tiles dir:  {settings.TILES_DIR}")
    print(f"[MeDICus SaaS] Server ready")
    yield
    # 종료 시 열린 슬라이드 정리
    from app.slide_manager import slide_manager
    slide_manager.close_all()
    print("[MeDICus SaaS] Shutdown complete")


app = FastAPI(
    title="MeDICus Studio SaaS",
    description="병리 AI 분석 SaaS API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 설정 (개발 중에는 모든 origin 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(slides.router, prefix="/api/slides", tags=["slides"])
app.include_router(tiles.router, prefix="/api/tiles", tags=["tiles"])
app.include_router(ai.router, prefix="/api/ai", tags=["ai"])

# 프론트엔드 정적 파일 서빙
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "MeDICus Studio SaaS"}
