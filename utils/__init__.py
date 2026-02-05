"""
유틸리티 모듈
좌표 변환 및 기타 헬퍼 함수 제공
"""

from .coordinate_utils import (
    CoordinateConverter,
    calculate_tile_range,
    is_rect_overlapping,
    clamp,
    mask_to_polygons,
    polygons_to_mask
)

__all__ = [
    'CoordinateConverter',
    'calculate_tile_range',
    'is_rect_overlapping',
    'clamp',
    'mask_to_polygons',
    'polygons_to_mask'
]
