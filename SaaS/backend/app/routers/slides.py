"""
슬라이드 관리 API — 업로드 (청크), 서버 파일 열기, 목록, 정보, 삭제
타일 프리제네레이션 트리거 + 진행 상태 조회
"""

import os
import uuid
import hashlib
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import settings
from app.slide_manager import slide_manager
from app import tile_generator

router = APIRouter()


def _slide_response(slide_id: str, info, filename: str):
    """슬라이드 정보 응답 공통 포맷"""
    return {
        "slide_id": slide_id,
        "filename": filename,
        "dimensions": info.dimensions,
        "level_count": info.level_count,
        "level_dimensions": info.level_dimensions,
        "level_downsamples": info.level_downsamples,
        "mpp": info.mpp,
        "mpp_x": info.mpp_x,
        "mpp_y": info.mpp_y,
        "vendor": info.vendor,
        "objective_power": info.objective_power,
        "physical_width_mm": info.physical_width_mm,
        "physical_height_mm": info.physical_height_mm,
        "tiles_ready": tile_generator.tiles_ready(filename),
    }


def _open_and_generate(slide_id: str, file_path: str, filename: str):
    """슬라이드 열기 + 타일 생성 시작 → 응답 반환"""
    # 이미 열려있으면 그대로
    existing = slide_manager.get(slide_id)
    if existing:
        tile_generator.start_generation(filename, file_path)
        return _slide_response(slide_id, existing, filename)

    try:
        info = slide_manager.open(slide_id, file_path)
    except Exception as e:
        raise HTTPException(400, f"슬라이드 열기 실패: {e}")

    # 백그라운드 타일 생성 시작
    tile_generator.start_generation(filename, file_path)
    return _slide_response(slide_id, info, filename)


# ── 저장된 슬라이드/폴더 목록 ──

def _safe_subpath(subpath: str) -> Path:
    """uploads/ 하위 경로만 허용 (디렉토리 탈출 방지)"""
    upload_dir = Path(settings.UPLOAD_DIR).resolve()
    target = (upload_dir / subpath).resolve()
    if not str(target).startswith(str(upload_dir)):
        raise HTTPException(400, "잘못된 경로")
    return target


@router.get("/browse")
async def browse(path: str = Query("", description="uploads/ 기준 상대 경로")):
    """현재 폴더의 하위 폴더 + 슬라이드 파일 목록"""
    target = _safe_subpath(path)
    if not target.exists() or not target.is_dir():
        raise HTTPException(404, "폴더를 찾을 수 없습니다")

    folders = []
    slides = []

    for f in sorted(target.iterdir()):
        if f.name.startswith("_chunks_") or f.name.startswith("."):
            continue
        if f.is_dir():
            folders.append({"name": f.name, "type": "folder"})
        elif f.is_file() and f.suffix.lower() in settings.SUPPORTED_EXTENSIONS:
            slide_id = hashlib.md5(f.name.encode()).hexdigest()[:12]
            slides.append({
                "filename": f.name,
                "slide_id": slide_id,
                "size_mb": round(f.stat().st_size / 1024 / 1024, 1),
                "type": "slide",
            })

    return {"path": path, "folders": folders, "slides": slides}


@router.post("/folder/create")
async def create_folder(path: str = Form(""), name: str = Form(...)):
    """폴더 생성"""
    target = _safe_subpath(path) / name
    if target.exists():
        raise HTTPException(400, "이미 존재하는 폴더입니다")
    target.mkdir(parents=True, exist_ok=True)
    return {"status": "created", "path": str(Path(path) / name)}


@router.post("/folder/rename")
async def rename_folder(path: str = Form(...), new_name: str = Form(...)):
    """폴더 이름 변경"""
    target = _safe_subpath(path)
    if not target.exists() or not target.is_dir():
        raise HTTPException(404, "폴더를 찾을 수 없습니다")
    new_target = target.parent / new_name
    if new_target.exists():
        raise HTTPException(400, "이미 존재하는 이름입니다")
    target.rename(new_target)
    return {"status": "renamed"}


@router.post("/folder/delete")
async def delete_folder(path: str = Form(...)):
    """폴더 삭제 (비어있을 때만)"""
    target = _safe_subpath(path)
    if not target.exists() or not target.is_dir():
        raise HTTPException(404, "폴더를 찾을 수 없습니다")
    # 비어있는지 확인
    children = list(target.iterdir())
    if children:
        raise HTTPException(400, "폴더가 비어있지 않습니다")
    target.rmdir()
    return {"status": "deleted"}


@router.post("/file/move")
async def move_file(filename: str = Form(...), src_path: str = Form(""), dst_path: str = Form("")):
    """파일을 다른 폴더로 이동"""
    src = _safe_subpath(src_path) / filename
    dst_dir = _safe_subpath(dst_path)
    if not src.exists():
        raise HTTPException(404, "파일을 찾을 수 없습니다")
    if not dst_dir.exists() or not dst_dir.is_dir():
        raise HTTPException(404, "대상 폴더를 찾을 수 없습니다")
    dst = dst_dir / filename
    if dst.exists():
        raise HTTPException(400, "대상 폴더에 같은 이름의 파일이 있습니다")
    shutil.move(str(src), str(dst))
    return {"status": "moved"}


# ── 서버에 파일 존재 확인 후 바로 열기 ──

@router.post("/open")
async def open_slide(filename: str = Form(...), path: str = Form("")):
    """파일명으로 서버 디스크에 있는지 확인 → 있으면 바로 열기"""
    final_path = _safe_subpath(path) / filename
    if not final_path.exists():
        return {"exists": False}

    slide_id = hashlib.md5(filename.encode()).hexdigest()[:12]
    resp = _open_and_generate(slide_id, str(final_path), filename)
    resp["exists"] = True
    return resp


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
    path: str = Form(""),
):
    """업로드 완료 — 청크 조립 → 슬라이드 열기 + 타일 생성"""
    chunk_dir = Path(settings.UPLOAD_DIR) / f"_chunks_{upload_id}"
    if not chunk_dir.exists():
        raise HTTPException(404, "업로드 세션을 찾을 수 없습니다")

    save_dir = _safe_subpath(path)
    save_dir.mkdir(parents=True, exist_ok=True)
    final_path = save_dir / filename

    if final_path.exists():
        shutil.rmtree(chunk_dir, ignore_errors=True)
    else:
        with open(final_path, "wb") as out:
            for i in range(total_chunks):
                chunk_path = chunk_dir / f"chunk_{i:06d}"
                if not chunk_path.exists():
                    raise HTTPException(400, f"청크 {i} 누락")
                with open(chunk_path, "rb") as cf:
                    shutil.copyfileobj(cf, out)
        shutil.rmtree(chunk_dir, ignore_errors=True)

    slide_id = hashlib.md5(filename.encode()).hexdigest()[:12]
    return _open_and_generate(slide_id, str(final_path), filename)


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

    slide_id = hashlib.md5(path.name.encode()).hexdigest()[:12]
    return _open_and_generate(slide_id, str(path), path.name)


# ── 타일 생성 진행 상태 ──

@router.get("/tile-progress/{slide_id}")
async def get_tile_progress(slide_id: str):
    """타일 프리제네레이션 진행 상태 (slide_id로 filename 조회)"""
    info = slide_manager.get(slide_id)
    if not info:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")
    filename = Path(info.file_path).name
    progress = tile_generator.get_progress(filename)
    if progress is None:
        raise HTTPException(404, "타일 생성 정보를 찾을 수 없습니다")
    return progress


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
        "tiles_ready": tile_generator.tiles_ready(Path(info.file_path).name),
    }


@router.get("/thumbnail-by-name")
async def get_thumbnail_by_name(
    filename: str = Query(...),
    path: str = Query(""),
    size: int = Query(300, ge=64, le=1024),
):
    """파일명 기반 썸네일 — slide_manager 불필요, 디스크에서 바로 반환"""
    import io
    import openslide

    # 1) 프리제네레이트된 썸네일이 있으면 바로 반환
    thumb_path = tile_generator.get_tiles_dir(filename) / "thumbnail.jpeg"
    if thumb_path.exists():
        return StreamingResponse(open(thumb_path, "rb"), media_type="image/jpeg")

    # 2) 없으면 즉석 생성 + 저장
    file_path = _safe_subpath(path) / filename
    if not file_path.exists():
        raise HTTPException(404, "파일을 찾을 수 없습니다")

    try:
        slide = openslide.OpenSlide(str(file_path))
        thumb = slide.get_thumbnail((size, size))
        thumb_rgb = thumb.convert("RGB")

        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        thumb_rgb.save(str(thumb_path), "JPEG", quality=85)
        slide.close()

        buf = io.BytesIO()
        thumb_rgb.save(buf, format="JPEG", quality=85)
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(500, f"썸네일 생성 실패: {e}")


@router.get("/{slide_id}/thumbnail")
async def get_thumbnail(slide_id: str, size: int = Query(300, ge=64, le=1024)):
    """slide_id 기반 썸네일 (하위 호환)"""
    info = slide_manager.get(slide_id)
    if not info:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")
    filename = Path(info.file_path).name
    thumb_path = tile_generator.get_tiles_dir(filename) / "thumbnail.jpeg"
    if thumb_path.exists():
        return StreamingResponse(open(thumb_path, "rb"), media_type="image/jpeg")

    import io
    thumb = info.slide.get_thumbnail((size, size))
    thumb_rgb = thumb.convert("RGB")
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    thumb_rgb.save(str(thumb_path), "JPEG", quality=85)
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


# ── Annotation 저장/불러오기 ──

import json

@router.post("/{slide_id}/annotations/save")
async def save_annotations(slide_id: str, data: str = Form(...)):
    """슬라이드별 annotation JSON 저장"""
    info = slide_manager.get(slide_id)
    if not info:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")
    filename = Path(info.file_path).name
    ann_path = tile_generator.get_tiles_dir(filename) / "annotations.json"
    ann_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ann_path, "w", encoding="utf-8") as f:
        f.write(data)
    return {"status": "saved", "count": len(json.loads(data))}


@router.get("/{slide_id}/annotations/load")
async def load_annotations(slide_id: str):
    """슬라이드별 annotation JSON 불러오기"""
    info = slide_manager.get(slide_id)
    if not info:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")
    filename = Path(info.file_path).name
    ann_path = tile_generator.get_tiles_dir(filename) / "annotations.json"
    if not ann_path.exists():
        return []
    with open(ann_path, "r", encoding="utf-8") as f:
        return json.loads(f.read())
