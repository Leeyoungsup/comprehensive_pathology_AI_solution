"""
Annotation 그래픽 아이템
QGraphicsItem을 사용한 Annotation 렌더링
ASAP의 PathologyViewer annotation 렌더링 참고
"""

from PyQt5.QtWidgets import QGraphicsItem, QGraphicsPolygonItem, QGraphicsEllipseItem
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QPen, QBrush, QColor, QPolygonF, QPainter
from typing import List, Optional, Tuple
import sys
from pathlib import Path

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.annotation import Annotation, AnnotationType


class AnnotationGraphicsItem(QGraphicsPolygonItem):
    """
    Annotation을 표시하는 QGraphicsItem
    ASAP의 AnnotationGraphicsItem 참고
    """
    
    def __init__(self, annotation: Annotation, parent=None):
        super().__init__(parent)
        self.annotation = annotation
        self.control_points: List[ControlPointItem] = []
        self.is_editing = False
        
        # 기본 설정
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setZValue(100)  # Annotation은 타일 위에 표시
        
        self.update_from_annotation()
    
    def update_from_annotation(self):
        """Annotation 데이터로부터 그래픽 업데이트"""
        if not self.annotation.coordinates:
            return
        
        # Polygon 생성
        polygon = QPolygonF()
        for x, y in self.annotation.coordinates:
            polygon.append(QPointF(x, y))
        self.setPolygon(polygon)
        
        # 스타일 설정
        self.update_style()
    
    def update_style(self):
        """선택/편집 상태에 따라 스타일 업데이트"""
        color = QColor(*self.annotation.color)
        
        if self.annotation.selected or self.isSelected():
            # 선택됨: 굵은 선
            pen = QPen(color, 3, Qt.SolidLine)
            brush = QBrush(QColor(color.red(), color.green(), color.blue(), 50))
        else:
            # 일반: 얇은 선
            pen = QPen(color, 2, Qt.SolidLine)
            brush = QBrush(QColor(color.red(), color.green(), color.blue(), 30))
        
        # Cosmetic pen: 배율에 관계없이 화면에서 일정한 두께
        pen.setCosmetic(True)
        
        self.setPen(pen)
        self.setBrush(brush)
    
    def start_editing(self):
        """편집 모드 시작 - 제어점 표시"""
        self.is_editing = True
        
        # 기존 제어점 제거
        for cp in self.control_points:
            if cp.scene():
                cp.scene().removeItem(cp)
        self.control_points.clear()
        
        # 새 제어점 생성
        for i, (x, y) in enumerate(self.annotation.coordinates):
            cp = ControlPointItem(x, y, i, self)
            self.control_points.append(cp)
            if self.scene():
                self.scene().addItem(cp)
    
    def stop_editing(self):
        """편집 모드 종료 - 제어점 숨김"""
        self.is_editing = False
        
        for cp in self.control_points:
            if cp.scene():
                cp.scene().removeItem(cp)
        self.control_points.clear()
    
    def update_coordinate(self, index: int, x: float, y: float):
        """특정 좌표 업데이트"""
        if 0 <= index < len(self.annotation.coordinates):
            self.annotation.coordinates[index] = (x, y)
            self.update_from_annotation()
    
    def hoverEnterEvent(self, event):
        """마우스 호버 시 하이라이트"""
        if not self.annotation.selected:
            pen = self.pen()
            pen.setWidth(3)
            pen.setCosmetic(True)
            self.setPen(pen)
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        """마우스 호버 해제"""
        if not self.annotation.selected:
            self.update_style()
        super().hoverLeaveEvent(event)
    
    def mousePressEvent(self, event):
        """마우스 클릭 - 선택"""
        super().mousePressEvent(event)
        self.annotation.selected = True
        self.update_style()
    
    def paint(self, painter: QPainter, option, widget=None):
        """커스텀 페인팅"""
        super().paint(painter, option, widget)
        
        # Annotation 이름 표시 (선택됐을 때)
        if self.annotation.selected and self.annotation.name:
            bounds = self.boundingRect()
            painter.setPen(QPen(Qt.white, 1))
            painter.drawText(
                bounds.topLeft() + QPointF(5, -5),
                self.annotation.name
            )


class ControlPointItem(QGraphicsEllipseItem):
    """
    Annotation 편집을 위한 제어점
    ASAP의 ControlPoint 참고
    """
    
    def __init__(self, x: float, y: float, index: int, parent_annotation: AnnotationGraphicsItem):
        # 제어점 크기 (화면 좌표 기준으로 5픽셀)
        size = 10
        super().__init__(-size/2, -size/2, size, size)
        
        self.index = index
        self.parent_annotation = parent_annotation
        
        self.setPos(x, y)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)  # 줌 시에도 크기 유지
        self.setZValue(101)  # Annotation 위에 표시
        
        # 스타일
        self.setPen(QPen(Qt.white, 2))
        self.setBrush(QBrush(QColor(0, 120, 255)))
        
        self.setAcceptHoverEvents(True)
    
    def itemChange(self, change, value):
        """아이템 변경 감지 - 드래그 시 좌표 업데이트"""
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            new_pos = value
            # 부모 Annotation의 좌표 업데이트
            self.parent_annotation.update_coordinate(
                self.index, 
                new_pos.x(), 
                new_pos.y()
            )
        
        return super().itemChange(change, value)
    
    def hoverEnterEvent(self, event):
        """호버 시 크기 확대"""
        self.setScale(1.5)
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        """호버 해제 시 원래 크기"""
        self.setScale(1.0)
        super().hoverLeaveEvent(event)


class DrawingPolygonItem(QGraphicsPolygonItem):
    """
    Polygon 그리기 중인 임시 아이템
    ASAP의 drawing mode 참고
    """
    
    def __init__(self, color: QColor = QColor(0, 255, 0)):
        super().__init__()
        
        self.points: List[QPointF] = []
        self.color = color
        self.start_point_item = None  # 시작점 표시
        
        # 스타일 - 영역 채우기 없이 선만 표시
        pen = QPen(color, 2, Qt.SolidLine)
        pen.setCosmetic(True)  # 배율 독립적 크기
        brush = QBrush(Qt.NoBrush)  # 투명 (영역 안 그림)
        self.setPen(pen)
        self.setBrush(brush)
        
        self.setZValue(99)  # Annotation 아래, 타일 위
    
    def add_point(self, x: float, y: float):
        """점 추가"""
        self.points.append(QPointF(x, y))
        
        # 첫 번째 점일 때 시작점 표시
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
        """마지막 점 업데이트 (마우스 따라다니기)"""
        if self.points:
            temp_points = self.points.copy()
            temp_points.append(QPointF(x, y))
            
            polygon = QPolygonF()
            for point in temp_points:
                polygon.append(point)
            self.setPolygon(polygon)
    
    def update_polygon(self):
        """Polygon 업데이트"""
        polygon = QPolygonF()
        for point in self.points:
            polygon.append(point)
        self.setPolygon(polygon)
    
    def get_coordinates(self) -> List[Tuple[float, float]]:
        """좌표 리스트 반환"""
        return [(p.x(), p.y()) for p in self.points]
    
    def is_valid(self) -> bool:
        """유효한 Polygon인지 확인 (최소 3점)"""
        return len(self.points) >= 3
    
    def is_near_start_point(self, x: float, y: float, threshold: float = 50.0) -> bool:
        """시작점에 가까운지 확인 (scene 좌표 기준)"""
        if len(self.points) < 3:
            return False
        
        start_point = self.points[0]
        distance = ((x - start_point.x()) ** 2 + (y - start_point.y()) ** 2) ** 0.5
        return distance < threshold
    
    def get_start_point(self):
        """시작점 좌표 반환"""
        if len(self.points) > 0:
            return self.points[0]
        return None
    
    def remove_start_point_indicator(self):
        """시작점 표시 제거"""
        if self.start_point_item and self.scene():
            self.scene().removeItem(self.start_point_item)
            self.start_point_item = None
