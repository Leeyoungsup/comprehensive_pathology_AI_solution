"""
타일 서빙 API — OpenSlide로 타일을 잘라서 JPEG로 반환
기존 TileLoader.load_tile() 로직을 HTTP 엔드포인트로 변환
"""

import io
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.config import settings
from app.slide_manager import slide_manager

router = APIRouter()

TILE_SIZE = settings.TILE_SIZE


@router.get("/{slide_id}/{level}/{tile_x}/{tile_y}.jpeg")
async def get_tile(
    slide_id: str,
    level: int,
    tile_x: int,
    tile_y: int,
):
    """
    타일 이미지 반환.

    URL 패턴: /api/tiles/{slide_id}/{level}/{tile_x}/{tile_y}.jpeg
    기존 TileLoader.load_tile()과 동일한 좌표계 사용.
    """
    info = slide_manager.get(slide_id)
    if not info:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")

    slide = info.slide

    if level < 0 or level >= info.level_count:
        raise HTTPException(400, f"잘못된 레벨: {level} (max: {info.level_count - 1})")

    # 타일의 level-0 좌표 계산 (기존 TileLoader와 동일)
    downsample = info.level_downsamples[level]
    x = int(tile_x * TILE_SIZE * downsample)
    y = int(tile_y * TILE_SIZE * downsample)

    level_0_width, level_0_height = info.dimensions
    if x >= level_0_width or y >= level_0_height:
        raise HTTPException(404, "타일 범위 초과")

    try:
        # OpenSlide read_region (level-0 좌표, 해당 레벨, 타일 크기)
        tile = slide.read_region((x, y), level, (TILE_SIZE, TILE_SIZE))
        tile_rgb = tile.convert("RGB")

        # JPEG 인코딩
        buf = io.BytesIO()
        tile_rgb.save(buf, format="JPEG", quality=settings.TILE_QUALITY)
        buf.seek(0)

        return Response(
            content=buf.getvalue(),
            media_type="image/jpeg",
            headers={
                "Cache-Control": "public, max-age=86400",  # 24시간 브라우저 캐싱
            },
        )
    except Exception as e:
        raise HTTPException(500, f"타일 로딩 실패: {e}")


@router.get("/{slide_id}/stage-level")
async def get_stage_level(
    slide_id: str,
    effective_mpp: float = Query(..., description="현재 화면의 effective MPP"),
):
    """effective MPP 기반 4단계 레벨 반환 (기존 get_stage_level과 동일)"""
    info = slide_manager.get(slide_id)
    if not info:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")

    level = info.get_stage_level(effective_mpp)
    return {
        "level": level,
        "level_dimensions": info.level_dimensions[level],
        "downsample": info.level_downsamples[level],
    }
