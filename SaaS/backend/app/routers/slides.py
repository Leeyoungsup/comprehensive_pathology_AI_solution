"""
슬라이드 관리 API — 업로드 (청크), 목록, 정보 조회, 삭제
"""

import os
import uuid
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import settings
from app.slide_manager import slide_manager

router = APIRouter()


# ── 청크 업로드 ──

@router.post("/upload/start")
async def upload_start(filename: str = Form(...)):
    """업로드 시작 — upload_id 발급"""
    ext = Path(filename).suffix.lower()
    if ext not in settings.SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"지원하지 않는 파일 형식: {ext}")

    upload_id = uuid.uuid4().hex[:12]
    chunk_dir = Path(settings.UPLOAD_DIR) / f"_chunks_{upload_id}"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    return {
        "upload_id": upload_id,
        "filename": filename,
        "chunk_size": settings.CHUNK_SIZE,
    }


@router.post("/upload/chunk")
async def upload_chunk(
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    chunk: UploadFile = File(...),
):
    """청크 업로드 — 개별 청크 저장"""
    chunk_dir = Path(settings.UPLOAD_DIR) / f"_chunks_{upload_id}"
    if not chunk_dir.exists():
        raise HTTPException(404, "업로드 세션을 찾을 수 없습니다")

    chunk_path = chunk_dir / f"chunk_{chunk_index:06d}"
    content = await chunk.read()
    with open(chunk_path, "wb") as f:
        f.write(content)

    return {"chunk_index": chunk_index, "size": len(content)}


@router.post("/upload/complete")
async def upload_complete(
    upload_id: str = Form(...),
    filename: str = Form(...),
    total_chunks: int = Form(...),
):
    """업로드 완료 — 청크 조립 → 슬라이드 열기"""
    chunk_dir = Path(settings.UPLOAD_DIR) / f"_chunks_{upload_id}"
    if not chunk_dir.exists():
        raise HTTPException(404, "업로드 세션을 찾을 수 없습니다")

    # 슬라이드 ID 생성
    slide_id = uuid.uuid4().hex[:12]
    final_path = Path(settings.UPLOAD_DIR) / f"{slide_id}_{filename}"

    # 청크 조립
    with open(final_path, "wb") as out:
        for i in range(total_chunks):
            chunk_path = chunk_dir / f"chunk_{i:06d}"
            if not chunk_path.exists():
                raise HTTPException(400, f"청크 {i} 누락")
            with open(chunk_path, "rb") as cf:
                shutil.copyfileobj(cf, out)

    # 청크 디렉토리 삭제
    shutil.rmtree(chunk_dir, ignore_errors=True)

    # 슬라이드 열기
    try:
        info = slide_manager.open(slide_id, str(final_path))
    except Exception as e:
        # 열기 실패 시 파일 삭제
        final_path.unlink(missing_ok=True)
        raise HTTPException(400, f"슬라이드 열기 실패: {e}")

    return {
        "slide_id": slide_id,
        "filename": filename,
        "dimensions": info.dimensions,
        "level_count": info.level_count,
        "level_dimensions": info.level_dimensions,
        "level_downsamples": info.level_downsamples,
        "mpp": info.mpp,
    }


# ── 서버 로컬 파일 열기 ──

@router.post("/open-local")
async def open_local_file(file_path: str = Form(...)):
    """서버 로컬 디스크의 WSI 파일 열기"""
    path = Path(file_path)
    if not path.exists():
        raise HTTPException(404, f"파일이 존재하지 않습니다: {file_path}")

    ext = path.suffix.lower()
    if ext not in settings.SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"지원하지 않는 파일 형식: {ext}")

    slide_id = uuid.uuid4().hex[:12]
    try:
        info = slide_manager.open(slide_id, str(path))
    except Exception as e:
        raise HTTPException(400, f"슬라이드 열기 실패: {e}")

    return {
        "slide_id": slide_id,
        "filename": path.name,
        "dimensions": info.dimensions,
        "level_count": info.level_count,
        "level_dimensions": info.level_dimensions,
        "level_downsamples": info.level_downsamples,
        "mpp": info.mpp,
    }


# ── 슬라이드 정보 ──

@router.get("/{slide_id}/info")
async def get_slide_info(slide_id: str):
    """슬라이드 메타데이터 조회"""
    info = slide_manager.get(slide_id)
    if not info:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")

    return {
        "slide_id": slide_id,
        "file_path": info.file_path,
        "dimensions": info.dimensions,
        "level_count": info.level_count,
        "level_dimensions": info.level_dimensions,
        "level_downsamples": info.level_downsamples,
        "mpp": info.mpp,
    }


@router.get("/{slide_id}/thumbnail")
async def get_thumbnail(slide_id: str, size: int = Query(300, ge=64, le=1024)):
    """슬라이드 썸네일 반환"""
    info = slide_manager.get(slide_id)
    if not info:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")

    thumb = info.slide.get_thumbnail((size, size))
    thumb_rgb = thumb.convert("RGB")

    import io
    buf = io.BytesIO()
    thumb_rgb.save(buf, format="JPEG", quality=85)
    buf.seek(0)

    return StreamingResponse(buf, media_type="image/jpeg")


# ── 목록 / 삭제 ──

@router.get("/")
async def list_slides():
    """열린 슬라이드 목록"""
    return slide_manager.list_slides()


@router.delete("/{slide_id}")
async def close_slide(slide_id: str):
    """슬라이드 닫기"""
    info = slide_manager.get(slide_id)
    if not info:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")

    slide_manager.close(slide_id)
    return {"status": "closed", "slide_id": slide_id}
