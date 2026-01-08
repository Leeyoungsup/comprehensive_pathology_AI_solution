"""
WSI 뷰어 위젯
대용량 병리 이미지(WSI) 표시, 줌/패닝 기능을 담당하는 커스텀 QGraphicsView
ASAP 구조를 참고한 타일 기반 렌더링 시스템
"""

from PyQt5.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QMainWindow
from PyQt5.QtCore import Qt, QPoint, QRectF, pyqtSignal, QEvent
from PyQt5.QtGui import QWheelEvent, QMouseEvent, QPainter, QBrush, QColor, QKeyEvent
from pathlib import Path
import sys

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.wsi_tile_manager import WSITileManager
from core.annotation import AnnotationList, Annotation, AnnotationType
from ui.minimap import MiniMap
from ui.annotation_items import AnnotationGraphicsItem, DrawingPolygonItem


class AnnotationMode:
    """Annotation 모드"""
    NONE = 0
    DRAWING_POLYGON = 1
    EDITING = 2
    SELECTING = 3


class WSIViewWidget(QGraphicsView):
    """WSI 표시 및 마우스 인터랙션을 처리하는 커스텀 위젯"""
    
    zoomChanged = pyqtSignal(float)
    fieldOfViewChanged = pyqtSignal(QRectF, int)
    annotationAdded = pyqtSignal(Annotation)
    annotationSelected = pyqtSignal(Annotation)
    annotationDeleted = pyqtSignal(Annotation)  # 어노테이션 삭제 시그널
    drawingCancelled = pyqtSignal()  # 그리기 취소 시그널
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 기본 설정
        self.setMinimumSize(800, 800)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setRenderHint(QPainter.Antialiasing, False)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        
        # Scene 설정
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.scene.setBackgroundBrush(QBrush(QColor(43, 43, 43)))
        
        # WSI 관련 속성
        self.tile_manager = None
        self.tile_items = {}  # (tile_x, tile_y, level) -> QGraphicsPixmapItem
        self.current_level = -1  # 현재 표시 중인 레벨 추적
        
        # 줌 관련 속성
        self.zoom_level = 1.0
        self.min_zoom = 0.01
        self.max_zoom = 40.0
        self.scene_scale = 1.0
        
        # 패닝 관련 속성
        self.is_panning = False
        self.last_pan_pos = QPoint()
        
        # 마우스 추적 활성화
        self.setMouseTracking(True)
        
        # Annotation 관련 속성
        self.annotation_list = AnnotationList()
        self.annotation_items = {}  # annotation.id -> AnnotationGraphicsItem
        self.annotation_mode = AnnotationMode.NONE
        self.current_drawing = None  # DrawingPolygonItem
        self.annotation_color = QColor(0, 255, 0)  # 기본 초록색
        self.annotation_counter = 0
        self.is_drawing_drag = False  # 드래그 중인지 여부
        self.drag_start_pos = None  # 드래그 시작 위치 (scene 좌표)
        self.last_view_pos = None  # 마지막 점 추가 위치 (view 좌표)
        
        # 미니맵 위젯 (오버레이)
        self.minimap = MiniMap(self)
        self.minimap.hide()  # 초기에는 숨김
        self.minimap.positionClicked.connect(self.on_minimap_clicked)
    
    def load_wsi(self, wsi_path):
        """WSI 파일 로드"""
        try:
            # 기존 타일 매니저 정리
            if self.tile_manager:
                self.tile_manager.close()
            
            # Scene 초기화
            self.scene.clear()
            self.tile_items.clear()
            
            # 새로운 타일 매니저 생성
            self.tile_manager = WSITileManager(wsi_path, tile_size=512, num_workers=4)
            self.tile_manager.tilesUpdated.connect(self.on_tiles_updated)
            
            # Scene 크기 설정 (레벨 0 기준)
            width, height = self.tile_manager.get_level_dimensions(0)
            self.scene_scale = 1.0  # 레벨 0 기준으로 1:1 스케일
            
            # Scene 여유 공간 설정
            margin = max(width, height) * 0.5
            self.scene.setSceneRect(
                -margin, -margin,
                width + 2 * margin, height + 2 * margin
            )
            
            # 초기 뷰 설정
            self.fit_to_window()
            
            # 미니맵 초기화 및 표시
            thumbnail = self.tile_manager.get_thumbnail((300, 300))
            if thumbnail:
                self.minimap.set_thumbnail(thumbnail)
                self.minimap.set_image_dimensions(width, height)
                self.minimap.show()
                # 위치 조정
                minimap_x = 10
                minimap_y = self.height() - self.minimap.height() - 10
                self.minimap.move(minimap_x, minimap_y)
            
            return True
            
        except Exception as e:
            print(f"WSI 로드 실패: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_tile_manager(self):
        """타일 매니저 반환 (외부에서 슬라이드 정보 접근용)"""
        return self.tile_manager
    
    def on_minimap_clicked(self, img_x, img_y):
        """미니맵에서 클릭한 위치로 뷰 이동"""
        if self.tile_manager:
            self.centerOn(img_x, img_y)
            self.update_field_of_view()
    
    def fit_to_window(self):
        """이미지를 윈도우 크기에 맞추기"""
        if not self.tile_manager:
            return
        
        # 최상위 레벨 크기 가져오기
        level = 0
        width, height = self.tile_manager.get_level_dimensions(level)
        print(f"Fit to window: 이미지 크기 = {width}x{height}")
        
        # 화면에 맞추기
        self.fitInView(0, 0, width, height, Qt.KeepAspectRatio)
        
        # 현재 줌 레벨 계산
        self.zoom_level = self.transform().m11()
        print(f"초기 줌 레벨: {self.zoom_level}")
        self.update_field_of_view()
    
    def set_zoom(self, zoom_level, anchor_pos=None):
        """줌 레벨 설정"""
        if not self.tile_manager:
            return
        
        # 줌 레벨 제한
        zoom_level = max(self.min_zoom, min(self.max_zoom, zoom_level))
        
        if anchor_pos:
            # 마우스 위치 기준 줌
            scene_pos = self.mapToScene(anchor_pos)
            self.resetTransform()
            self.scale(zoom_level, zoom_level)
            self.centerOn(scene_pos)
        else:
            # 중앙 기준 줌
            center = self.mapToScene(self.viewport().rect().center())
            self.resetTransform()
            self.scale(zoom_level, zoom_level)
            self.centerOn(center)
        
        self.zoom_level = zoom_level
        self.zoomChanged.emit(zoom_level)
        self.update_field_of_view()
    
    def zoom_in(self, anchor_pos=None):
        """줌 인"""
        if self.zoom_level >= self.max_zoom:
            return  # 이미 최대 줌
        new_zoom = self.zoom_level * 1.2
        self.set_zoom(new_zoom, anchor_pos)
    
    def zoom_out(self, anchor_pos=None):
        """줌 아웃"""
        if self.zoom_level <= self.min_zoom:
            return  # 이미 최소 줌
        new_zoom = self.zoom_level / 1.2
        self.set_zoom(new_zoom, anchor_pos)
    
    def update_field_of_view(self):
        """현재 보이는 영역 업데이트 및 타일 로딩"""
        if not self.tile_manager:
            return
        
        # 현재 보이는 영역 계산
        view_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        
        # 4단계 레벨 시스템 사용
        level = self.tile_manager.get_stage_level(self.zoom_level)
        
        # 레벨 변경 감지
        level_changed = (self.current_level != level)
        if level_changed:
            self.current_level = level
        
        # 시그널 발생
        self.fieldOfViewChanged.emit(view_rect, level)
        
        # 타일 로딩 요청
        self.tile_manager.load_tiles_for_view(view_rect, level)
        
        # 미니맵 업데이트
        if hasattr(self, 'minimap') and self.minimap.isVisible():
            self.minimap.update_field_of_view(view_rect)
            cached_tiles = self.tile_manager.get_cached_tiles_info()
            self.minimap.update_cached_tiles(cached_tiles)
        
        # 즉시 캐시된 타일 렌더링
        self.on_tiles_updated()
    
    def on_tiles_updated(self):
        """타일 업데이트 시 호출 - 새로 로드된 타일만 추가"""
        if not self.tile_manager:
            return
        
        # 현재 보이는 영역 계산
        view_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        level = self.tile_manager.get_stage_level(self.zoom_level)
        level_downsample = self.tile_manager.get_level_downsample(level)
        
        # 타일 크기
        tile_size = 512
        
        # 보이는 타일 범위 계산
        start_tile_x = max(0, int(view_rect.left() / tile_size / level_downsample))
        start_tile_y = max(0, int(view_rect.top() / tile_size / level_downsample))
        end_tile_x = int(view_rect.right() / tile_size / level_downsample) + 2
        end_tile_y = int(view_rect.bottom() / tile_size / level_downsample) + 2
        
        # 타일 렌더링
        tiles_rendered = 0
        for ty in range(start_tile_y, end_tile_y):
            for tx in range(start_tile_x, end_tile_x):
                cache_key = (tx, ty, level)
                
                # 이미 렌더링된 타일인지 확인
                if cache_key not in self.tile_items:
                    pixmap = self.tile_manager.get_tile(tx, ty, level)
                    if pixmap:
                        # 타일 위치 계산
                        tile_x_pos = tx * tile_size * level_downsample
                        tile_y_pos = ty * tile_size * level_downsample
                        
                        # 타일 아이템 생성 및 추가
                        item = QGraphicsPixmapItem(pixmap)
                        item.setPos(tile_x_pos, tile_y_pos)
                        item.setScale(level_downsample)
                        item.setZValue(10 - level)  # 고해상도가 위에
                        
                        self.scene.addItem(item)
                        self.tile_items[cache_key] = item
                        tiles_rendered += 1
        
        # 미니맵 캐시 상태 업데이트
        if tiles_rendered > 0 and hasattr(self, 'minimap') and self.minimap.isVisible():
            cached_tiles = self.tile_manager.get_cached_tiles_info()
            self.minimap.update_cached_tiles(cached_tiles)
        
        # 타일 정리
        self._cleanup_tiles(start_tile_x, start_tile_y, end_tile_x, end_tile_y, level, tile_size, level_downsample)
    
    def _cleanup_tiles(self, start_tile_x, start_tile_y, end_tile_x, end_tile_y, level, tile_size, level_downsample):
        """보이지 않는 타일 제거"""
        keys_to_remove = []
        for key in self.tile_items:
            tx, ty, lv = key
            
            # 현재 레벨이면: 보이는 범위 밖만 제거
            if lv == level:
                if tx < start_tile_x - 2 or tx > end_tile_x + 2 or \
                   ty < start_tile_y - 2 or ty > end_tile_y + 2:
                    item = self.tile_items[key]
                    self.scene.removeItem(item)
                    keys_to_remove.append(key)
            # 다른 레벨이면: 현재 레벨 타일로 덮인 영역만 제거
            else:
                if self._is_tile_covered(tx, ty, lv, start_tile_x, start_tile_y, end_tile_x, end_tile_y, level, tile_size, level_downsample):
                    item = self.tile_items[key]
                    self.scene.removeItem(item)
                    keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self.tile_items[key]
    
    def _is_tile_covered(self, tx, ty, old_level, start_tile_x, start_tile_y, end_tile_x, end_tile_y, new_level, tile_size, level_downsample):
        """이전 레벨 타일이 현재 레벨 타일로 완전히 덮였는지 확인"""
        old_downsample = self.tile_manager.get_level_downsample(old_level)
        old_tile_x0 = tx * tile_size * old_downsample
        old_tile_y0 = ty * tile_size * old_downsample
        old_tile_x1 = old_tile_x0 + tile_size * old_downsample
        old_tile_y1 = old_tile_y0 + tile_size * old_downsample
        
        # 현재 레벨 타일과 겹치는지 확인
        for new_ty in range(start_tile_y, end_tile_y):
            for new_tx in range(start_tile_x, end_tile_x):
                new_tile_x0 = new_tx * tile_size * level_downsample
                new_tile_y0 = new_ty * tile_size * level_downsample
                new_tile_x1 = new_tile_x0 + tile_size * level_downsample
                new_tile_y1 = new_tile_y0 + tile_size * level_downsample
                
                # 겹치는지 확인
                if not (new_tile_x1 < old_tile_x0 or new_tile_x0 > old_tile_x1 or
                        new_tile_y1 < old_tile_y0 or new_tile_y0 > old_tile_y1):
                    # 겹치는 타일이 캐시에 있는지 확인
                    if (new_tx, new_ty, new_level) not in self.tile_items:
                        return False
        
        return True
    
    def wheelEvent(self, event: QWheelEvent):
        """마우스 휠로 줌 인/아웃"""
        if not self.tile_manager:
            return
        
        delta = event.angleDelta().y()
        anchor_pos = event.pos()
        
        if delta > 0:
            self.zoom_in(anchor_pos)
        else:
            self.zoom_out(anchor_pos)
        
        event.accept()
    
    def mousePressEvent(self, event: QMouseEvent):
        """마우스 버튼 누름"""
        # Ctrl+드래그 시 패닝 (모든 모드에서 동작)
        if event.modifiers() & Qt.ControlModifier and event.button() == Qt.LeftButton:
            self.is_panning = True
            self.last_pan_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        
        # Annotation 그리기 모드
        if self.annotation_mode == AnnotationMode.DRAWING_POLYGON:
            if event.button() == Qt.LeftButton:
                # Scene 좌표로 변환
                scene_pos = self.mapToScene(event.pos())
                
                # 시작점 근처 체크 (최소 2점 이후, 즉 3번째 클릭부터)
                # 2점 + 현재 클릭 = 3점이므로 유효한 polygon
                if self.current_drawing and len(self.current_drawing.points) >= 2:
                    start_point = self.current_drawing.get_start_point()
                    if start_point:
                        # 화면 좌표 기준으로 거리 계산
                        start_view_pos = self.mapFromScene(start_point)
                        current_view_pos = event.pos()
                        view_distance = ((current_view_pos.x() - start_view_pos.x()) ** 2 + 
                                        (current_view_pos.y() - start_view_pos.y()) ** 2) ** 0.5
                        
                        # 시작점 근처(20픽셀)면 자동 완성 (점 추가 없이)
                        if view_distance < 20:
                            self.finish_drawing_polygon()
                            event.accept()
                            return
                
                # 점 추가
                if self.current_drawing:
                    self.current_drawing.add_point(scene_pos.x(), scene_pos.y())
                
                # 드래그 시작 (화면 좌표 저장)
                self.is_drawing_drag = True
                self.drag_start_pos = scene_pos
                self.last_view_pos = event.pos()
                self.last_view_pos = event.pos()
                
                event.accept()
                return
            elif event.button() == Qt.RightButton:
                # 우클릭: Polygon 완성
                self.finish_drawing_polygon()
                event.accept()
                return
        
        # 일반 모드: 패닝
        if event.button() == Qt.LeftButton:
            # Scene 아이템 클릭 확인 (Annotation 선택)
            scene_pos = self.mapToScene(event.pos())
            items = self.scene.items(scene_pos)
            
            annotation_clicked = False
            for item in items:
                if isinstance(item, AnnotationGraphicsItem):
                    self.select_annotation(item.annotation)
                    annotation_clicked = True
                    break
            
            if not annotation_clicked:
                # Annotation을 클릭하지 않았으면 패닝
                self.is_panning = True
                self.last_pan_pos = event.pos()
                self.setCursor(Qt.ClosedHandCursor)
            
            event.accept()
        else:
            event.ignore()
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """마우스 이동"""
        # 패닝 모드 (Ctrl+드래그 중이거나 일반 패닝 중)
        if self.is_panning:
            delta = event.pos() - self.last_pan_pos
            self.last_pan_pos = event.pos()
            
            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())
            
            self.update_field_of_view()
            event.accept()
            return
        
        # Annotation 그리기 모드
        if self.annotation_mode == AnnotationMode.DRAWING_POLYGON and self.current_drawing:
            scene_pos = self.mapToScene(event.pos())
            
            # 시작점 근처에 있는지 확인 (화면 좌표 기준으로 체크)
            is_near_start = False
            if len(self.current_drawing.points) >= 3:
                start_point = self.current_drawing.get_start_point()
                if start_point:
                    # Scene 좌표를 화면 좌표로 변환
                    start_view_pos = self.mapFromScene(start_point)
                    current_view_pos = event.pos()
                    
                    # 화면 좌표 기준으로 거리 계산 (20픽셀)
                    view_distance = ((current_view_pos.x() - start_view_pos.x()) ** 2 + 
                                    (current_view_pos.y() - start_view_pos.y()) ** 2) ** 0.5
                    is_near_start = view_distance < 20
            
            # 시작점 근처면 커서 변경
            if is_near_start:
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.setCursor(Qt.CrossCursor)
            
            if self.is_drawing_drag:
                # 드래그 중: 화면 좌표 기준으로 일정 거리마다 점 추가
                if self.last_view_pos:
                    current_view_pos = event.pos()
                    # 화면 좌표 기준 거리 계산
                    view_distance = ((current_view_pos.x() - self.last_view_pos.x()) ** 2 + 
                                    (current_view_pos.y() - self.last_view_pos.y()) ** 2) ** 0.5
                    
                    # 10픽셀 이상 이동 시 새 점 추가
                    if view_distance > 10:
                        # 시작점 근찄면 자동 완성
                        if is_near_start:
                            self.finish_drawing_polygon()
                            return
                        
                        self.current_drawing.add_point(scene_pos.x(), scene_pos.y())
                        self.last_view_pos = current_view_pos
            else:
                # 드래그 중이 아닐 때: 마우스를 따라다니는 선 업데이트
                self.current_drawing.update_last_point(scene_pos.x(), scene_pos.y())
            
            event.accept()
            return
        
        # 마우스 좌표 표시
        if self.tile_manager:
            scene_pos = self.mapToScene(event.pos())
            parent = self.parent()
            while parent:
                if isinstance(parent, QMainWindow):
                    parent.statusbar.showMessage(
                        f"이미지 좌표: ({scene_pos.x():.0f}, {scene_pos.y():.0f})", 
                        1000
                    )
                    break
                parent = parent.parent()
        event.ignore()
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """마우스 버튼 놓음"""
        if event.button() == Qt.LeftButton:
            # 패닝 종료
            if self.is_panning:
                self.is_panning = False
                # 그리기 모드였다면 커서 복구
                if self.annotation_mode == AnnotationMode.DRAWING_POLYGON:
                    self.setCursor(Qt.CrossCursor)
                else:
                    self.setCursor(Qt.ArrowCursor)
                event.accept()
                return
            
            # Annotation 그리기 모드에서 드래그 종료
            if self.annotation_mode == AnnotationMode.DRAWING_POLYGON:
                self.is_drawing_drag = False
                self.drag_start_pos = None
                event.accept()
                return
            
            self.setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            event.ignore()
    
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """더블 클릭 - 폴리곤 완성"""
        if self.annotation_mode == AnnotationMode.DRAWING_POLYGON and event.button() == Qt.LeftButton:
            self.finish_drawing_polygon()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)
    
    def keyPressEvent(self, event):
        """키 이벤트 처리"""
        if event.key() == Qt.Key_Escape:
            # ESC: 그리기 취소
            if self.annotation_mode == AnnotationMode.DRAWING_POLYGON:
                self.cancel_drawing()
                event.accept()
                return
        elif event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            # Enter: 폴리곤 완성
            if self.annotation_mode == AnnotationMode.DRAWING_POLYGON:
                self.finish_drawing_polygon()
                event.accept()
                return
        elif event.key() == Qt.Key_Delete:
            # Delete: 선택된 annotation 삭제
            if self.annotation_list.selected_annotation:
                self.annotationDeleted.emit(self.annotation_list.selected_annotation)
                event.accept()
                return
        
        super().keyPressEvent(event)
    
    def resizeEvent(self, event):
        """윈도우 크기 변경 시 처리"""
        super().resizeEvent(event)
        
        # 미니맵 위치 조정
        if hasattr(self, 'minimap'):
            minimap_x = 10
            minimap_y = self.height() - self.minimap.height() - 10
            self.minimap.move(minimap_x, minimap_y)
        
        self.update_field_of_view()
    
    def close(self):
        """리소스 정리"""
        if self.tile_manager:
            self.tile_manager.close()
            self.tile_manager = None
        
        self.scene.clear()
        self.tile_items.clear()
        self.annotation_items.clear()
    
    # ==================== Annotation 기능 ====================
    
    def set_annotation_mode(self, mode: int):
        """Annotation 모드 설정"""
        self.annotation_mode = mode
        
        if mode == AnnotationMode.DRAWING_POLYGON:
            self.setCursor(Qt.CrossCursor)
        elif mode == AnnotationMode.EDITING:
            self.setCursor(Qt.ArrowCursor)
            # 선택된 annotation 편집 시작
            if self.annotation_list.selected_annotation:
                self.start_editing_annotation(self.annotation_list.selected_annotation)
        else:
            self.setCursor(Qt.ArrowCursor)
            # 편집 모드 종료
            for item in self.annotation_items.values():
                item.stop_editing()
    
    def start_drawing_polygon(self):
        """Polygon 그리기 시작"""
        self.set_annotation_mode(AnnotationMode.DRAWING_POLYGON)
        self.current_drawing = DrawingPolygonItem(self.annotation_color)
        self.scene.addItem(self.current_drawing)
    
    def finish_drawing_polygon(self):
        """Polygon 그리기 완료"""
        if self.current_drawing and self.current_drawing.is_valid():
            # 시작점 표시 제거
            self.current_drawing.remove_start_point_indicator()
            
            # Annotation 생성
            self.annotation_counter += 1
            annotation = Annotation(
                name=f"ROI_{self.annotation_counter}",
                type=AnnotationType.POLYGON,
                coordinates=self.current_drawing.get_coordinates(),
                color=(self.annotation_color.red(), 
                       self.annotation_color.green(), 
                       self.annotation_color.blue())
            )
            
            # AnnotationList에 추가
            self.annotation_list.add_annotation(annotation)
            
            # 그래픽 아이템 생성 및 제어점 표시
            self.add_annotation_item(annotation)
            
            # 방금 생성한 annotation 선택하고 제어점 표시
            annotation.selected = True
            if annotation.id in self.annotation_items:
                self.annotation_items[annotation.id].start_editing()
            
            # 시그널 발생
            self.annotationAdded.emit(annotation)
        
        # 그리기 아이템 제거
        if self.current_drawing:
            self.scene.removeItem(self.current_drawing)
            self.current_drawing = None
        
        # 드래그 상태 초기화
        self.is_drawing_drag = False
        self.drag_start_pos = None
        self.last_view_pos = None
        
        self.set_annotation_mode(AnnotationMode.NONE)
    
    def cancel_drawing(self):
        """그리기 취소"""
        if self.current_drawing:
            # 시작점 표시 제거
            self.current_drawing.remove_start_point_indicator()
            self.scene.removeItem(self.current_drawing)
            self.current_drawing = None
        
        # 드래그 상태 초기화
        self.is_drawing_drag = False
        self.drag_start_pos = None
        self.last_view_pos = None
        
        self.set_annotation_mode(AnnotationMode.NONE)
        self.drawingCancelled.emit()  # 시그널 발생
    
    def add_annotation_item(self, annotation: Annotation):
        """Annotation 그래픽 아이템 추가"""
        item = AnnotationGraphicsItem(annotation)
        self.scene.addItem(item)
        self.annotation_items[annotation.id] = item
    
    def remove_annotation(self, annotation: Annotation):
        """Annotation 제거"""
        # 그래픽 아이템 제거
        if annotation.id in self.annotation_items:
            item = self.annotation_items[annotation.id]
            self.scene.removeItem(item)
            del self.annotation_items[annotation.id]
        
        # AnnotationList에서 제거
        self.annotation_list.remove_annotation(annotation)
    
    def select_annotation(self, annotation: Annotation):
        """Annotation 선택"""
        self.annotation_list.select_annotation(annotation)
        
        # 모든 아이템 스타일 업데이트
        for ann in self.annotation_list.annotations:
            if ann.id in self.annotation_items:
                self.annotation_items[ann.id].update_style()
        
        self.annotationSelected.emit(annotation)
    
    def start_editing_annotation(self, annotation: Annotation):
        """Annotation 편집 시작"""
        if annotation.id in self.annotation_items:
            item = self.annotation_items[annotation.id]
            item.start_editing()
    
    def clear_annotations(self):
        """모든 Annotation 제거"""
        # 그래픽 아이템 제거
        for item in self.annotation_items.values():
            self.scene.removeItem(item)
        self.annotation_items.clear()
        
        # AnnotationList 초기화
        self.annotation_list.clear()
    
    def get_annotations(self):
        """Annotation 목록 반환"""
        return list(self.annotation_list.annotations)
    
    def save_annotations(self, file_path: str):
        """Annotation 저장"""
        self.annotation_list.save_to_json(file_path)
    
    def load_annotations(self, file_path: str):
        """Annotation 로드"""
        self.clear_annotations()
        self.annotation_list.load_from_json(file_path)
        
        # 그래픽 아이템 생성
        for annotation in self.annotation_list.annotations:
            self.add_annotation_item(annotation)
    
    def close(self):
        """리소스 정리"""
        if self.tile_manager:
            self.tile_manager.close()
            self.tile_manager = None
        
        self.scene.clear()
        self.tile_items.clear()
