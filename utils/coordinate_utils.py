"""
좌표 변환 유틸리티
WSI 이미지의 다양한 좌표계 간 변환을 지원
"""

from PyQt5.QtCore import QPointF, QRectF
import numpy as np
import cv2


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


def mask_to_polygons(mask, metadata, class_names, simplify_epsilon=2.0, min_area=10):
    """
    Segmentation mask를 클래스별 polygon 윤곽선으로 변환 (WSI level-0 좌표계)

    Args:
        mask: numpy.ndarray, shape (H, W), dtype uint8, 값 0~N (클래스 ID)
        metadata: dict - wsi_mpp, output_mpp, region_offset 포함
        class_names: list 또는 dict - 클래스 이름
        simplify_epsilon: cv2.approxPolyDP epsilon (mask 픽셀 단위)
        min_area: 최소 contour 면적 (mask 픽셀 단위, 이보다 작으면 제거)

    Returns:
        dict: {cls_id_str: {"class_name": str, "polygons": [{"exterior": [[x,y],...], "interiors": [...]}]}}
    """
    wsi_mpp = metadata.get('wsi_mpp', 0.25)
    output_mpp = metadata.get('output_mpp', 4.0)
    region_offset = metadata.get('region_offset', (0, 0))
    offset_x, offset_y = region_offset
    scale = output_mpp / wsi_mpp  # mask pixel → WSI level-0 pixels

    if isinstance(class_names, dict):
        names = class_names
    else:
        names = {i: name for i, name in enumerate(class_names)}

    result = {}

    for cls_id in range(1, max(names.keys()) + 1):  # Background(0) 제외
        if cls_id not in names:
            continue

        class_binary = (mask == cls_id).astype(np.uint8)
        contours, hierarchy = cv2.findContours(
            class_binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
        )

        if not contours or hierarchy is None:
            continue

        hierarchy = hierarchy[0]  # shape: (N, 4) — [next, prev, child, parent]

        polygons = []
        idx = 0
        while idx >= 0 and idx < len(hierarchy):
            # top-level contour (exterior)만 처리
            if hierarchy[idx][3] != -1:
                idx = hierarchy[idx][0]
                continue

            contour = contours[idx]
            if cv2.contourArea(contour) < min_area:
                idx = hierarchy[idx][0]
                continue

            if simplify_epsilon > 0:
                contour = cv2.approxPolyDP(contour, simplify_epsilon, True)

            if len(contour) < 3:
                idx = hierarchy[idx][0]
                continue

            # mask 좌표 → WSI level-0 좌표
            exterior = []
            for pt in contour:
                mx, my = float(pt[0][0]), float(pt[0][1])
                wsi_x = mx * scale + offset_x
                wsi_y = my * scale + offset_y
                exterior.append([round(wsi_x, 1), round(wsi_y, 1)])

            # hole contour (children) 수집
            interiors = []
            child_idx = hierarchy[idx][2]
            while child_idx >= 0:
                hole_contour = contours[child_idx]
                if simplify_epsilon > 0:
                    hole_contour = cv2.approxPolyDP(hole_contour, simplify_epsilon, True)
                if len(hole_contour) >= 3:
                    interior = []
                    for pt in hole_contour:
                        mx, my = float(pt[0][0]), float(pt[0][1])
                        wsi_x = mx * scale + offset_x
                        wsi_y = my * scale + offset_y
                        interior.append([round(wsi_x, 1), round(wsi_y, 1)])
                    interiors.append(interior)
                child_idx = hierarchy[child_idx][0]

            polygons.append({"exterior": exterior, "interiors": interiors})
            idx = hierarchy[idx][0]

        if polygons:
            result[str(cls_id)] = {
                "class_name": names[cls_id],
                "polygons": polygons
            }

    return result


def polygons_to_mask(class_polygons, metadata):
    """
    Polygon 윤곽선에서 segmentation mask를 복원

    Args:
        class_polygons: mask_to_polygons 출력 형식의 dict
        metadata: dict - mask_shape, wsi_mpp, output_mpp, region_offset 포함

    Returns:
        numpy.ndarray: 복원된 mask, shape metadata['mask_shape'], dtype uint8
    """
    mask_shape = tuple(metadata['mask_shape'])  # (H, W)
    wsi_mpp = metadata.get('wsi_mpp', 0.25)
    output_mpp = metadata.get('output_mpp', 4.0)
    region_offset = metadata.get('region_offset', (0, 0))
    offset_x, offset_y = region_offset
    inv_scale = wsi_mpp / output_mpp  # WSI level-0 → mask pixels

    mask = np.zeros(mask_shape, dtype=np.uint8)

    # 클래스 순서대로 처리 (높은 ID가 나중에 덮어씀)
    for cls_id_str in sorted(class_polygons.keys(), key=int):
        cls_id = int(cls_id_str)
        cls_data = class_polygons[cls_id_str]

        for polygon in cls_data["polygons"]:
            # exterior 채우기
            exterior_pts = np.array([
                [int((x - offset_x) * inv_scale), int((y - offset_y) * inv_scale)]
                for x, y in polygon["exterior"]
            ], dtype=np.int32)

            if len(exterior_pts) >= 3:
                cv2.fillPoly(mask, [exterior_pts], cls_id)

            # hole 복원 (Background로)
            for interior in polygon.get("interiors", []):
                interior_pts = np.array([
                    [int((x - offset_x) * inv_scale), int((y - offset_y) * inv_scale)]
                    for x, y in interior
                ], dtype=np.int32)

                if len(interior_pts) >= 3:
                    cv2.fillPoly(mask, [interior_pts], 0)

    return mask
