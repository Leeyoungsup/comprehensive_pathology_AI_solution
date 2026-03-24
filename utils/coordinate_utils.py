"""
Coordinate conversion utilities
Supports conversion between various coordinate systems of WSI images
"""

from PyQt5.QtCore import QPointF, QRectF
import numpy as np
import cv2


class CoordinateConverter:
    """
    Coordinate conversion utility class

    Coordinate systems:
    - Level 0 coordinates: Pixel coordinates of the original image
    - Level N coordinates: Pixel coordinates of the downsampled image
    - Scene coordinates: QGraphicsScene coordinates
    - View coordinates: QGraphicsView screen coordinates
    """

    @staticmethod
    def level0_to_levelN(x, y, downsample):
        """
        Convert level 0 coordinates to level N coordinates

        Args:
            x, y: Level 0 coordinates
            downsample: Downsample factor of level N

        Returns:
            tuple: (x_levelN, y_levelN)
        """
        return (x / downsample, y / downsample)

    @staticmethod
    def levelN_to_level0(x, y, downsample):
        """
        Convert level N coordinates to level 0 coordinates

        Args:
            x, y: Level N coordinates
            downsample: Downsample factor of level N

        Returns:
            tuple: (x_level0, y_level0)
        """
        return (x * downsample, y * downsample)

    @staticmethod
    def rect_level0_to_levelN(rect, downsample):
        """
        Convert level 0 rectangle to level N rectangle

        Args:
            rect: QRectF or (x, y, w, h) tuple
            downsample: Downsample factor of level N

        Returns:
            QRectF: Converted rectangle
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
        Convert level N rectangle to level 0 rectangle

        Args:
            rect: QRectF or (x, y, w, h) tuple
            downsample: Downsample factor of level N

        Returns:
            QRectF: Converted rectangle
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
        Convert tile index to level 0 coordinates

        Args:
            tile_x, tile_y: Tile index
            tile_size: Tile size (pixels)
            downsample: Downsample factor of the level

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
        Convert level 0 coordinates to tile index

        Args:
            x, y: Level 0 coordinates
            tile_size: Tile size (pixels)
            downsample: Downsample factor of the level

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
        Convert physical size (mm) to pixels

        Args:
            physical_mm: Physical size (mm)
            mpp: Microns Per Pixel

        Returns:
            float: Number of pixels
        """
        if mpp is None or mpp == 0:
            return 0
        return (physical_mm * 1000) / mpp

    @staticmethod
    def pixel_to_physical(pixel, mpp):
        """
        Convert pixels to physical size (mm)

        Args:
            pixel: Number of pixels
            mpp: Microns Per Pixel

        Returns:
            float: Physical size (mm)
        """
        if mpp is None:
            return 0
        return (pixel * mpp) / 1000


def calculate_tile_range(view_rect, tile_size, level_downsample, margin=2):
    """
    Calculate the tile range corresponding to the visible area

    Args:
        view_rect: QRectF, visible area (level 0 coordinates)
        tile_size: Tile size (pixels)
        level_downsample: Downsample factor of the level
        margin: Extra tile margin

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
    Check if two rectangles overlap

    Args:
        rect1, rect2: QRectF or (x, y, w, h) tuple

    Returns:
        bool: True if overlapping
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
    Clamp a value within a range

    Args:
        value: Value to clamp
        min_value: Minimum value
        max_value: Maximum value

    Returns:
        Clamped value
    """
    return max(min_value, min(max_value, value))


def mask_to_polygons(mask, metadata, class_names, simplify_epsilon=2.0, min_area=10):
    """
    Convert segmentation mask to per-class polygon contours (WSI level-0 coordinate system)

    Args:
        mask: numpy.ndarray, shape (H, W), dtype uint8, values 0~N (class IDs)
        metadata: dict - contains wsi_mpp, output_mpp, region_offset
        class_names: list or dict - class names
        simplify_epsilon: cv2.approxPolyDP epsilon (in mask pixel units)
        min_area: Minimum contour area (in mask pixel units, smaller contours are removed)

    Returns:
        dict: {cls_id_str: {"class_name": str, "polygons": [{"exterior": [[x,y],...], "interiors": [...]}]}}
    """
    wsi_mpp = metadata.get('wsi_mpp', 0.25)
    output_mpp = metadata.get('output_mpp', 4.0)
    region_offset = metadata.get('region_offset', (0, 0))
    offset_x, offset_y = region_offset
    scale = output_mpp / wsi_mpp  # mask pixel -> WSI level-0 pixels

    if isinstance(class_names, dict):
        names = class_names
    else:
        names = {i: name for i, name in enumerate(class_names)}

    result = {}

    for cls_id in range(1, max(names.keys()) + 1):  # Exclude Background(0)
        if cls_id not in names:
            continue

        class_binary = (mask == cls_id).astype(np.uint8)
        contours, hierarchy = cv2.findContours(
            class_binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
        )

        if not contours or hierarchy is None:
            continue

        hierarchy = hierarchy[0]  # shape: (N, 4) -- [next, prev, child, parent]

        polygons = []
        idx = 0
        while idx >= 0 and idx < len(hierarchy):
            # Process only top-level contours (exterior)
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

            # mask coordinates -> WSI level-0 coordinates
            exterior = []
            for pt in contour:
                mx, my = float(pt[0][0]), float(pt[0][1])
                wsi_x = mx * scale + offset_x
                wsi_y = my * scale + offset_y
                exterior.append([round(wsi_x, 1), round(wsi_y, 1)])

            # Collect hole contours (children)
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
    Reconstruct segmentation mask from polygon contours

    Args:
        class_polygons: dict in mask_to_polygons output format
        metadata: dict - contains mask_shape, wsi_mpp, output_mpp, region_offset

    Returns:
        numpy.ndarray: Reconstructed mask, shape metadata['mask_shape'], dtype uint8
    """
    mask_shape = tuple(metadata['mask_shape'])  # (H, W)
    wsi_mpp = metadata.get('wsi_mpp', 0.25)
    output_mpp = metadata.get('output_mpp', 4.0)
    region_offset = metadata.get('region_offset', (0, 0))
    offset_x, offset_y = region_offset
    inv_scale = wsi_mpp / output_mpp  # WSI level-0 -> mask pixels

    mask = np.zeros(mask_shape, dtype=np.uint8)

    # Process classes in order (higher IDs overwrite later)
    for cls_id_str in sorted(class_polygons.keys(), key=int):
        cls_id = int(cls_id_str)
        cls_data = class_polygons[cls_id_str]

        for polygon in cls_data["polygons"]:
            # Fill exterior
            exterior_pts = np.array([
                [int((x - offset_x) * inv_scale), int((y - offset_y) * inv_scale)]
                for x, y in polygon["exterior"]
            ], dtype=np.int32)

            if len(exterior_pts) >= 3:
                cv2.fillPoly(mask, [exterior_pts], cls_id)

            # Restore holes (as Background)
            for interior in polygon.get("interiors", []):
                interior_pts = np.array([
                    [int((x - offset_x) * inv_scale), int((y - offset_y) * inv_scale)]
                    for x, y in interior
                ], dtype=np.int32)

                if len(interior_pts) >= 3:
                    cv2.fillPoly(mask, [interior_pts], 0)

    return mask
