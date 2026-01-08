"""
좌표 변환 유틸리티
WSI 이미지의 다양한 좌표계 간 변환을 지원
"""

from PyQt5.QtCore import QPointF, QRectF


class CoordinateConverter:
    """
    좌표 변환 유틸리티 클래스
    
    좌표계 종류:
    - 레벨 0 좌표계: 원본 이미지의 픽셀 좌표
    - 레벨 N 좌표계: 다운샘플된 이미지의 픽셀 좌표
    - Scene 좌표계: QGraphicsScene의 좌표
    - View 좌표계: QGraphicsView의 화면 좌표
    """
    
    @staticmethod
    def level0_to_levelN(x, y, downsample):
        """
        레벨 0 좌표를 레벨 N 좌표로 변환
        
        Args:
            x, y: 레벨 0 좌표
            downsample: 레벨 N의 다운샘플 배율
        
        Returns:
            tuple: (x_levelN, y_levelN)
        """
        return (x / downsample, y / downsample)
    
    @staticmethod
    def levelN_to_level0(x, y, downsample):
        """
        레벨 N 좌표를 레벨 0 좌표로 변환
        
        Args:
            x, y: 레벨 N 좌표
            downsample: 레벨 N의 다운샘플 배율
        
        Returns:
            tuple: (x_level0, y_level0)
        """
        return (x * downsample, y * downsample)
    
    @staticmethod
    def rect_level0_to_levelN(rect, downsample):
        """
        레벨 0 사각형을 레벨 N 사각형으로 변환
        
        Args:
            rect: QRectF 또는 (x, y, w, h) 튜플
            downsample: 레벨 N의 다운샘플 배율
        
        Returns:
            QRectF: 변환된 사각형
        """
        if isinstance(rect, QRectF):
            x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        else:
            x, y, w, h = rect
        
        return QRectF(
            x / downsample,
            y / downsample,
            w / downsample,
            h / downsample
        )
    
    @staticmethod
    def rect_levelN_to_level0(rect, downsample):
        """
        레벨 N 사각형을 레벨 0 사각형으로 변환
        
        Args:
            rect: QRectF 또는 (x, y, w, h) 튜플
            downsample: 레벨 N의 다운샘플 배율
        
        Returns:
            QRectF: 변환된 사각형
        """
        if isinstance(rect, QRectF):
            x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        else:
            x, y, w, h = rect
        
        return QRectF(
            x * downsample,
            y * downsample,
            w * downsample,
            h * downsample
        )
    
    @staticmethod
    def tile_index_to_level0(tile_x, tile_y, tile_size, downsample):
        """
        타일 인덱스를 레벨 0 좌표로 변환
        
        Args:
            tile_x, tile_y: 타일 인덱스
            tile_size: 타일 크기 (픽셀)
            downsample: 레벨의 다운샘플 배율
        
        Returns:
            tuple: (x_level0, y_level0)
        """
        return (
            tile_x * tile_size * downsample,
            tile_y * tile_size * downsample
        )
    
    @staticmethod
    def level0_to_tile_index(x, y, tile_size, downsample):
        """
        레벨 0 좌표를 타일 인덱스로 변환
        
        Args:
            x, y: 레벨 0 좌표
            tile_size: 타일 크기 (픽셀)
            downsample: 레벨의 다운샘플 배율
        
        Returns:
            tuple: (tile_x, tile_y)
        """
        return (
            int(x / tile_size / downsample),
            int(y / tile_size / downsample)
        )
    
    @staticmethod
    def physical_to_pixel(physical_mm, mpp):
        """
        물리적 크기(mm)를 픽셀로 변환
        
        Args:
            physical_mm: 물리적 크기 (mm)
            mpp: Microns Per Pixel
        
        Returns:
            float: 픽셀 수
        """
        if mpp is None or mpp == 0:
            return 0
        return (physical_mm * 1000) / mpp
    
    @staticmethod
    def pixel_to_physical(pixel, mpp):
        """
        픽셀을 물리적 크기(mm)로 변환
        
        Args:
            pixel: 픽셀 수
            mpp: Microns Per Pixel
        
        Returns:
            float: 물리적 크기 (mm)
        """
        if mpp is None:
            return 0
        return (pixel * mpp) / 1000


def calculate_tile_range(view_rect, tile_size, level_downsample, margin=2):
    """
    보이는 영역에 해당하는 타일 범위 계산
    
    Args:
        view_rect: QRectF, 보이는 영역 (레벨 0 좌표)
        tile_size: 타일 크기 (픽셀)
        level_downsample: 레벨의 다운샘플 배율
        margin: 여유 타일 수
    
    Returns:
        tuple: (start_tile_x, start_tile_y, end_tile_x, end_tile_y)
    """
    start_tile_x = max(0, int(view_rect.left() / tile_size / level_downsample) - margin)
    start_tile_y = max(0, int(view_rect.top() / tile_size / level_downsample) - margin)
    end_tile_x = int(view_rect.right() / tile_size / level_downsample) + margin
    end_tile_y = int(view_rect.bottom() / tile_size / level_downsample) + margin
    
    return (start_tile_x, start_tile_y, end_tile_x, end_tile_y)


def is_rect_overlapping(rect1, rect2):
    """
    두 사각형이 겹치는지 확인
    
    Args:
        rect1, rect2: QRectF 또는 (x, y, w, h) 튜플
    
    Returns:
        bool: 겹치면 True
    """
    if isinstance(rect1, QRectF):
        x1, y1, w1, h1 = rect1.x(), rect1.y(), rect1.width(), rect1.height()
    else:
        x1, y1, w1, h1 = rect1
    
    if isinstance(rect2, QRectF):
        x2, y2, w2, h2 = rect2.x(), rect2.y(), rect2.width(), rect2.height()
    else:
        x2, y2, w2, h2 = rect2
    
    return not (x1 + w1 < x2 or x2 + w2 < x1 or y1 + h1 < y2 or y2 + h2 < y1)


def clamp(value, min_value, max_value):
    """
    값을 범위 내로 제한
    
    Args:
        value: 제한할 값
        min_value: 최소값
        max_value: 최대값
    
    Returns:
        제한된 값
    """
    return max(min_value, min(max_value, value))
