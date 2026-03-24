"""
Annotation Graphics Items
Annotation rendering using QGraphicsItem
Based on ASAP PathologyViewer annotation rendering
"""

from PyQt5.QtWidgets import QGraphicsItem, QGraphicsPolygonItem, QGraphicsEllipseItem, QGraphicsPathItem
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QPen, QBrush, QColor, QPolygonF, QPainter, QPainterPath
from typing import List, Optional, Tuple
import sys
from pathlib import Path
import math

# Add project root
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.annotation import Annotation, AnnotationType


class AnnotationGraphicsItem(QGraphicsPolygonItem):
    """
    QGraphicsItem for displaying annotations
    Based on ASAP AnnotationGraphicsItem
    """

    def __init__(self, annotation: Annotation, parent=None):
        super().__init__(parent)
        self.annotation = annotation
        self.control_points: List[ControlPointItem] = []
        self.is_editing = False

        # Default settings
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setZValue(100)  # Annotations displayed above tiles

        self.update_from_annotation()

    def update_from_annotation(self):
        """Update graphics from annotation data"""
        if not self.annotation.coordinates:
            return

        # Point type displayed as a small circle
        if self.annotation.type == AnnotationType.POINT and len(self.annotation.coordinates) == 1:
            # Approximate a circle with a 16-sided polygon for points
            x, y = self.annotation.coordinates[0]
            radius = 15
            polygon = QPolygonF()
            # 16-sided polygon approximating a circle
            for i in range(16):
                angle = 2 * math.pi * i / 16
                px = x + radius * math.cos(angle)
                py = y + radius * math.sin(angle)
                polygon.append(QPointF(px, py))
            self.setPolygon(polygon)
        else:
            # Create Polygon/Rectangle
            polygon = QPolygonF()
            for x, y in self.annotation.coordinates:
                polygon.append(QPointF(x, y))
            self.setPolygon(polygon)

        # Set style
        self.update_style()

    def update_style(self):
        """Update style based on selection/editing state"""
        color = QColor(*self.annotation.color)

        if self.annotation.selected or self.isSelected():
            # Selected: thick line
            pen = QPen(color, 3, Qt.SolidLine)
            brush = QBrush(Qt.NoBrush)  # Transparent (no fill)
        else:
            # Normal: thin line
            pen = QPen(color, 2, Qt.SolidLine)
            brush = QBrush(Qt.NoBrush)  # Transparent (no fill)

        # Cosmetic pen: constant thickness on screen regardless of scale
        pen.setCosmetic(True)

        self.setPen(pen)
        self.setBrush(brush)

    def start_editing(self):
        """Start editing mode - show control points"""
        self.is_editing = True

        # Remove existing control points
        for cp in self.control_points:
            if cp.scene():
                cp.scene().removeItem(cp)
        self.control_points.clear()

        # Create new control points
        for i, (x, y) in enumerate(self.annotation.coordinates):
            cp = ControlPointItem(x, y, i, self)
            self.control_points.append(cp)
            if self.scene():
                self.scene().addItem(cp)

    def stop_editing(self):
        """Stop editing mode - hide control points"""
        self.is_editing = False

        for cp in self.control_points:
            try:
                if cp.scene():
                    cp.scene().removeItem(cp)
            except RuntimeError:
                pass
        self.control_points.clear()

    def update_coordinate(self, index: int, x: float, y: float):
        """Update a specific coordinate"""
        if 0 <= index < len(self.annotation.coordinates):
            self.annotation.coordinates[index] = (x, y)
            self.update_from_annotation()

    def hoverEnterEvent(self, event):
        """Highlight on mouse hover"""
        if not self.annotation.selected:
            pen = self.pen()
            pen.setWidth(3)
            pen.setCosmetic(True)
            self.setPen(pen)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        """Remove highlight on mouse hover exit"""
        if not self.annotation.selected:
            self.update_style()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        """Mouse click - select"""
        super().mousePressEvent(event)
        self.annotation.selected = True
        self.update_style()

    def paint(self, painter: QPainter, option, widget=None):
        """Custom painting"""
        super().paint(painter, option, widget)

        # Show annotation name (when selected)
        if self.annotation.selected and self.annotation.name:
            bounds = self.boundingRect()
            painter.setPen(QPen(Qt.white, 1))
            painter.drawText(
                bounds.topLeft() + QPointF(5, -5),
                self.annotation.name
            )


class ControlPointItem(QGraphicsEllipseItem):
    """
    Control point for annotation editing
    Based on ASAP ControlPoint
    """

    def __init__(self, x: float, y: float, index: int, parent_annotation: AnnotationGraphicsItem):
        # Control point size (5 pixels in screen coordinates)
        size = 10
        super().__init__(-size/2, -size/2, size, size)

        self.index = index
        self.parent_annotation = parent_annotation

        self.setPos(x, y)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)  # Maintain size during zoom
        self.setZValue(101)  # Displayed above annotations

        # Style
        self.setPen(QPen(Qt.white, 2))
        self.setBrush(QBrush(QColor(0, 120, 255)))

        self.setAcceptHoverEvents(True)

    def itemChange(self, change, value):
        """Detect item changes - update coordinates on drag"""
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            new_pos = value
            # Update parent annotation coordinates
            self.parent_annotation.update_coordinate(
                self.index,
                new_pos.x(),
                new_pos.y()
            )

        return super().itemChange(change, value)

    def hoverEnterEvent(self, event):
        """Enlarge on hover"""
        self.setScale(1.5)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        """Restore size on hover exit"""
        self.setScale(1.0)
        super().hoverLeaveEvent(event)


class DrawingPolygonItem(QGraphicsPathItem):
    """
    Temporary item while drawing a polygon
    Based on ASAP drawing mode
    - Uses QGraphicsPathItem so start and end points are not auto-connected
    """

    def __init__(self, color: QColor = QColor(0, 255, 0)):
        super().__init__()

        self.points: List[QPointF] = []
        self.color = color
        self.start_point_item = None  # Start point indicator

        # Style - line only, no fill
        pen = QPen(color, 2, Qt.SolidLine)
        pen.setCosmetic(True)  # Scale-independent size
        self.setPen(pen)
        self.setBrush(QBrush(Qt.NoBrush))  # Transparent

        self.setZValue(99)  # Below annotations, above tiles

    def add_point(self, x: float, y: float):
        """Add a point"""
        self.points.append(QPointF(x, y))

        # Show start point indicator on first point
        if len(self.points) == 1 and self.scene():
            self.start_point_item = QGraphicsEllipseItem(-6, -6, 12, 12)
            self.start_point_item.setPos(x, y)
            self.start_point_item.setPen(QPen(self.color, 2))
            self.start_point_item.setBrush(QBrush(self.color))
            self.start_point_item.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
            self.start_point_item.setZValue(100)
            self.scene().addItem(self.start_point_item)

        self.update_polygon()

    def update_last_point(self, x: float, y: float):
        """Update last point (follow mouse) - displayed as open path"""
        if self.points:
            temp_points = self.points.copy()
            temp_points.append(QPointF(x, y))

            # Create open path with QPainterPath (no start-end connection)
            path = QPainterPath()
            if temp_points:
                path.moveTo(temp_points[0])
                for point in temp_points[1:]:
                    path.lineTo(point)
            self.setPath(path)

    def update_polygon(self):
        """Update path"""
        path = QPainterPath()
        if self.points:
            path.moveTo(self.points[0])
            for point in self.points[1:]:
                path.lineTo(point)
        self.setPath(path)

    def get_coordinates(self) -> List[Tuple[float, float]]:
        """Return coordinate list"""
        return [(p.x(), p.y()) for p in self.points]

    def is_valid(self) -> bool:
        """Check if polygon is valid (minimum 3 points)"""
        return len(self.points) >= 3

    def is_near_start_point(self, x: float, y: float, threshold: float = 50.0) -> bool:
        """Check if near start point (in scene coordinates)"""
        if len(self.points) < 3:
            return False

        start_point = self.points[0]
        distance = ((x - start_point.x()) ** 2 + (y - start_point.y()) ** 2) ** 0.5
        return distance < threshold

    def get_start_point(self):
        """Return start point coordinates"""
        if len(self.points) > 0:
            return self.points[0]
        return None

    def remove_start_point_indicator(self):
        """Remove start point indicator"""
        if self.start_point_item and self.scene():
            self.scene().removeItem(self.start_point_item)
            self.start_point_item = None


class DrawingRectangleItem(QGraphicsPathItem):
    """
    Temporary item while drawing a rectangle
    Created by dragging
    """

    def __init__(self, color: QColor = QColor(255, 0, 0)):
        super().__init__()

        self.start_point: Optional[QPointF] = None
        self.end_point: Optional[QPointF] = None
        self.color = color

        # Style - line only, no fill
        pen = QPen(color, 2, Qt.SolidLine)
        pen.setCosmetic(True)  # Scale-independent size
        self.setPen(pen)
        self.setBrush(QBrush(Qt.NoBrush))  # Transparent (no fill)

        self.setZValue(99)  # Below annotations, above tiles

    def set_start_point(self, x: float, y: float):
        """Set start point"""
        self.start_point = QPointF(x, y)
        self.end_point = QPointF(x, y)
        self.update_rectangle()

    def update_end_point(self, x: float, y: float):
        """Update end point"""
        self.end_point = QPointF(x, y)
        self.update_rectangle()

    def update_rectangle(self):
        """Update rectangle"""
        if self.start_point and self.end_point:
            path = QPainterPath()
            rect = QRectF(self.start_point, self.end_point).normalized()
            path.addRect(rect)
            self.setPath(path)

    def get_coordinates(self) -> List[Tuple[float, float]]:
        """Return four corner coordinates of the rectangle (compatible with polygon)"""
        if not self.start_point or not self.end_point:
            return []

        rect = QRectF(self.start_point, self.end_point).normalized()
        return [
            (rect.left(), rect.top()),
            (rect.right(), rect.top()),
            (rect.right(), rect.bottom()),
            (rect.left(), rect.bottom())
        ]

    def is_valid(self) -> bool:
        """Check if rectangle is valid"""
        if not self.start_point or not self.end_point:
            return False

        rect = QRectF(self.start_point, self.end_point).normalized()
        return rect.width() > 5 and rect.height() > 5


class DrawingPointItem(QGraphicsEllipseItem):
    """
    Temporary item while drawing a point
    Displays a dot at the clicked position
    """

    def __init__(self, x: float, y: float, color: QColor = QColor(0, 0, 255)):
        # Circle with radius 10 pixels
        super().__init__(-10, -10, 20, 20)

        self.setPos(x, y)
        self.color = color
        self.point_x = x
        self.point_y = y

        # Style
        pen = QPen(color, 2, Qt.SolidLine)
        pen.setCosmetic(True)  # Scale-independent size
        self.setPen(pen)
        self.setBrush(QBrush(color))

        # Maintain size regardless of scale
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setZValue(99)  # Below annotations, above tiles

    def get_coordinates(self) -> List[Tuple[float, float]]:
        """Return point coordinates"""
        return [(self.point_x, self.point_y)]

    def is_valid(self) -> bool:
        """Always valid"""
        return True
