"""
Utilities module
Provides coordinate conversion and other helper functions
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
