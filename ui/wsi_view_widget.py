"""
WSI 뷰어 위젯
대용량 병리 이미지(WSI) 표시, 줌/패닝 기능을 담당하는 커스텀 QGraphicsView
ASAP 구조를 참고한 타일 기반 렌더링 시스템
"""

from PyQt5.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QMainWindow
from PyQt5.QtCore import Qt, QPoint, QRectF, pyqtSignal, QEvent, QTimer
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
from ui.annotation_items import AnnotationGraphicsItem, DrawingPolygonItem, DrawingRectangleItem, DrawingPointItem


class AnnotationMode:
    """Annotation 모드"""
    NONE = 0
    DRAWING_POLYGON = 1
    DRAWING_RECTANGLE = 2
    DRAWING_POINT = 3
    EDITING = 4
    SELECTING = 5


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
        self.setViewportUpdateMode(QGraphicsView.MinimalViewportUpdate)
        
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
        # 지속 그리기 플래그 (툴을 켜둔 상태에서 계속 그리기)
        self.keep_drawing = False
        
        # 미니맵 위젯 (오버레이)
        self.minimap = MiniMap(self)
        self.minimap.hide()  # 초기에는 숨김
        self.minimap.positionClicked.connect(self.on_minimap_clicked)
        
        # 검출 결과 오버레이
        self.detection_overlay_item = None  # QGraphicsPixmapItem
        self.detection_overlay = None  # TiledDetectionOverlay 객체
        self.detection_cells = []  # 검출된 세포 리스트
        
        # Segmentation 오버레이
        self.segmentation_overlay_item = None  # QGraphicsPixmapItem
        self.segmentation_mask = None
        self.segmentation_metadata = None
        self.segmentation_class_names = None
        self.segmentation_class_visibility = {}  # 클래스별 가시성
        self.segmentation_roi_bounds = None  # ROI 영역 정보

        # Virtual Stain 오버레이
        self.virtual_stain_overlay_item = None  # QGraphicsPixmapItem
        self.virtual_stain_canvas = None         # np.ndarray (H, W, 3)
        self.virtual_stain_metadata = None       # dict with roi_origin, target_mpp, canvas_l0_w/h
        self.virtual_stain_visible = True
        
        # 오버레이 업데이트 디바운싱 타이머
        self.overlay_update_timer = QTimer(self)
        self.overlay_update_timer.setSingleShot(True)
        self.overlay_update_timer.timeout.connect(self._do_update_detection_overlay)
        self.overlay_update_delay = 100  # 100ms 딜레이
    
    def load_wsi(self, wsi_path):
        """WSI 파일 로드"""
        try:
            # 기존 타일 매니저 정리
            if self.tile_manager:
                self.tile_manager.close()
            
            # 그리기 상태 초기화 (scene.clear() 전에 참조 해제)
            self.current_drawing = None
            self.is_drawing_drag = False
            self.drag_start_pos = None
            self.annotation_mode = AnnotationMode.NONE

            # Scene 초기화
            self.scene.clear()
            self.tile_items.clear()
            
            # 새로운 타일 매니저 생성
            self.tile_manager = WSITileManager(wsi_path, num_workers=4)
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
            print(f"WSI load failed: {e}")
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
        print(f"Fit to window: image size = {width}x{height}")
        
        # 화면에 맞추기
        self.fitInView(0, 0, width, height, Qt.KeepAspectRatio)
        
        # 현재 줌 레벨 계산
        self.zoom_level = self.transform().m11()
        print(f"Initial zoom level: {self.zoom_level}")
        self.update_field_of_view()
    
    def get_effective_mpp(self):
        """현재 화면의 effective MPP (μm/px) = wsi_mpp / zoom_level.
        슬라이드 크기와 무관한 물리적 해상도 기준값을 반환한다.
        """
        if not self.tile_manager or self.zoom_level <= 0:
            return float('inf')
        return self.tile_manager.mpp / self.zoom_level

    def set_zoom(self, zoom_level, anchor_pos=None):
        """줌 레벨 설정"""
        if not self.tile_manager:
            return
        
        # 줌 레벨 제한
        zoom_level = max(self.min_zoom, min(self.max_zoom, zoom_level))
        
        if anchor_pos:
            # 마우스 위치 기준 줌 (부분적 센터링)
            old_center = self.mapToScene(self.viewport().rect().center())
            target_pos = self.mapToScene(anchor_pos)
            
            self.resetTransform()
            self.scale(zoom_level, zoom_level)
            
            # 현재 중심과 마우스 위치의 중간 지점으로 이동 (30% 센터링 강도)
            centering_strength = 0.3  # 0.0 = 센터링 없음, 1.0 = 완전 센터링
            new_center_x = old_center.x() + (target_pos.x() - old_center.x()) * centering_strength
            new_center_y = old_center.y() + (target_pos.y() - old_center.y()) * centering_strength
            self.centerOn(new_center_x, new_center_y)
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
        new_zoom = self.zoom_level * 1.1
        self.set_zoom(new_zoom, anchor_pos)
    
    def zoom_out(self, anchor_pos=None):
        """줌 아웃"""
        if self.zoom_level <= self.min_zoom:
            return  # 이미 최소 줌
        new_zoom = self.zoom_level / 1.1
        self.set_zoom(new_zoom, anchor_pos)
    
    def update_field_of_view(self):
        """현재 보이는 영역 업데이트 및 타일 로딩"""
        if not self.tile_manager:
            return
        
        # 현재 보이는 영역 계산
        view_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        
        # 4단계 레벨 시스템 사용
        level = self.tile_manager.get_stage_level(self.get_effective_mpp())
        
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
        
        # 검출 결과 오버레이 업데이트 (디바운싱)
        if self.detection_cells:
            self.schedule_overlay_update()
        
        # Segmentation 오버레이 업데이트
        if self.segmentation_mask is not None:
            self.update_segmentation_overlay()

        # Virtual Stain 오버레이 업데이트
        if self.virtual_stain_canvas is not None:
            self.update_virtual_stain_overlay()
        
        # 즉시 캐시된 타일 렌더링
        self.on_tiles_updated()
    
    def on_tiles_updated(self):
        """타일 업데이트 시 호출 - 새로 로드된 타일만 추가"""
        if not self.tile_manager:
            return
        
        # 현재 보이는 영역 계산
        view_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        level = self.tile_manager.get_stage_level(self.get_effective_mpp())
        level_downsample = self.tile_manager.get_level_downsample(level)
        
        # 타일 크기
        tile_size = self.tile_manager.tile_size
        
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
                    try:
                        self.scene.removeItem(item)
                    except RuntimeError:
                        pass
                    keys_to_remove.append(key)
            # 다른 레벨이면: 현재 레벨 타일로 덮인 영역만 제거
            else:
                if self._is_tile_covered(tx, ty, lv, start_tile_x, start_tile_y, end_tile_x, end_tile_y, level, tile_size, level_downsample):
                    item = self.tile_items[key]
                    try:
                        self.scene.removeItem(item)
                    except RuntimeError:
                        pass
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
    
    # ============== 검출 결과 오버레이 ==============
    
    def set_detection_results(self, cells, color_map=None):
        """
        검출 결과 설정 및 오버레이 표시

        Args:
            cells: 검출된 세포 리스트 [{'x': x, 'y': y, 'cls_id': cls_id, 'confidence': conf}, ...]
            color_map: 커스텀 색상맵 (None이면 기본 CLASS_COLORS_RGB 사용)
        """
        from ai.detection import TiledDetectionOverlay

        self.detection_cells = cells

        # TiledDetectionOverlay 초기화
        if self.detection_overlay is None:
            self.detection_overlay = TiledDetectionOverlay(color_map=color_map)

        self.detection_overlay.set_cells(cells, color_map=color_map)

        # 오버레이 업데이트
        self.schedule_overlay_update()
    
    def schedule_overlay_update(self):
        """오버레이 업데이트 예약 (디바운싱)"""
        # 타이머가 실행 중이면 재시작
        self.overlay_update_timer.stop()
        self.overlay_update_timer.start(self.overlay_update_delay)
    
    def _do_update_detection_overlay(self):
        """실제 오버레이 업데이트 수행 (타이머에서 호출)"""
        self.update_detection_overlay()
    
    def update_detection_overlay(self):
        """현재 뷰 영역의 검출 결과 오버레이 업데이트"""
        if not self.detection_overlay or not self.detection_cells:
            return
        
        if not self.tile_manager:
            return
        
        # 기존 오버레이 제거
        if self.detection_overlay_item:
            try:
                if isinstance(self.detection_overlay_item, list):
                    for item in self.detection_overlay_item:
                        self.scene.removeItem(item)
                else:
                    self.scene.removeItem(self.detection_overlay_item)
            except RuntimeError:
                # 이미 삭제된 객체는 무시
                pass
            self.detection_overlay_item = None
        
        # 현재 뷰 영역 가져오기
        view_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        
        # 다운샘플 계산 — effective MPP 기준 (슬라이드 크기 무관)
        # 세포 직경 ~10-20 μm 기준으로 화면에서 차지하는 크기를 고려
        mpp = self.get_effective_mpp()
        if mpp > 8.0:
            downsample = 16
        elif mpp > 4.0:
            downsample = 8
        elif mpp > 1.0:
            downsample = 4
        elif mpp > 0.4:
            downsample = 2
        else:
            downsample = 1

        # LOD: mpp > 3 μm/px 이상이면 히트맵, 이하면 circle
        use_heatmap = mpp > 3.0

        if use_heatmap:
            pixmap, mask_x, mask_y, scale = self.detection_overlay.create_heatmap_mask(view_rect)
        else:
            pixmap, mask_x, mask_y = self.detection_overlay.create_view_mask(view_rect, downsample)
            scale = downsample

        if pixmap is None:
            return

        # 새 오버레이 아이템 생성
        self.detection_overlay_item = QGraphicsPixmapItem(pixmap)
        self.detection_overlay_item.setPos(mask_x, mask_y)
        self.detection_overlay_item.setScale(scale)
        self.detection_overlay_item.setZValue(50)

        self.scene.addItem(self.detection_overlay_item)
    
    def clear_detection_overlay(self):
        """검출 결과 오버레이 제거"""
        if self.detection_overlay_item:
            try:
                self.scene.removeItem(self.detection_overlay_item)
            except RuntimeError:
                pass
            self.detection_overlay_item = None
        
        self.detection_cells = []
        if self.detection_overlay:
            self.detection_overlay.clear_cells()
    
    def clear_detection_results(self):
        """검출 결과 완전히 제거 (오버레이 + 데이터)"""
        self.clear_detection_overlay()
        self.detection_overlay = None
    
    def set_segmentation_overlay(self, mask, metadata, class_names, roi_bounds=None, roi_polygons=None):
        """세분화 결과를 오버레이로 표시"""
        self.segmentation_mask = mask
        self.segmentation_metadata = metadata
        self.segmentation_roi_bounds = roi_bounds
        self.segmentation_roi_polygons = roi_polygons  # ROI polygon 좌표 저장
        
        # class_names가 리스트인 경우 딕셔너리로 변환
        if isinstance(class_names, list):
            self.segmentation_class_names = {i: name for i, name in enumerate(class_names)}
        else:
            self.segmentation_class_names = class_names
        
        # 초기 가시성 설정 (모두 보이게)
        self.segmentation_class_visibility = {cls_id: True for cls_id in self.segmentation_class_names.keys()}
        
        # 전체 RGBA 이미지 미리 생성 (ROI 마스킹 포함)
        self._create_segmentation_rgba_image()
        
        # 오버레이 업데이트
        self.update_segmentation_overlay()
    
    def _create_segmentation_rgba_image(self):
        """Segmentation 마스크를 RGBA 이미지로 미리 변환 (ROI 마스킹 포함)"""
        import numpy as np
        
        if self.segmentation_mask is None:
            self.segmentation_rgba_cache = None
            return
        
        mask = self.segmentation_mask
        mask_h, mask_w = mask.shape
        
        # 컬러 맵
        seg_colors_rgb = {
            0: (0, 0, 0, 0),          # Background - 투명
            1: (255, 0, 0, 128),      # Stroma - 반투명 빨강
            2: (0, 255, 0, 128),      # Non_Tumor - 반투명 초록
            3: (0, 0, 255, 128)       # Tumor - 반투명 파랑
        }
        
        # RGBA 이미지 생성 (전체 투명으로 초기화)
        rgba_image = np.zeros((mask_h, mask_w, 4), dtype=np.uint8)
        
        # ROI polygon이 있으면 polygon 내부만 표시
        if self.segmentation_roi_polygons:
            import cv2
            
            region_offset = self.segmentation_metadata.get('region_offset', (0, 0))
            offset_x, offset_y = region_offset
            
            wsi_mpp = self.segmentation_metadata.get('wsi_mpp', 0.25)
            output_mpp = self.segmentation_metadata.get('output_mpp', 8.0)
            scale_factor = wsi_mpp / output_mpp
            
            # 모든 polygon들을 합친 binary mask 생성
            polygon_mask = np.zeros((mask_h, mask_w), dtype=np.uint8)
            
            for polygon_coords in self.segmentation_roi_polygons:
                # WSI 좌표를 mask 좌표로 변환
                mask_coords = []
                for x, y in polygon_coords:
                    mask_x = int((x - offset_x) * scale_factor)
                    mask_y = int((y - offset_y) * scale_factor)
                    mask_coords.append([mask_x, mask_y])
                
                # Polygon 채우기
                pts = np.array(mask_coords, dtype=np.int32)
                cv2.fillPoly(polygon_mask, [pts], 1)
            
            # Polygon 내부에만 컬러 적용
            for cls_id, color in seg_colors_rgb.items():
                # 해당 클래스이면서 polygon 내부인 픽셀
                class_mask = (mask == cls_id) & (polygon_mask == 1)
                rgba_image[class_mask] = color
        
        elif self.segmentation_roi_bounds:
            # ROI bounds만 있으면 사각형 영역 처리
            roi_x_min, roi_y_min, roi_x_max, roi_y_max = self.segmentation_roi_bounds
            
            region_offset = self.segmentation_metadata.get('region_offset', (0, 0))
            offset_x, offset_y = region_offset
            
            wsi_mpp = self.segmentation_metadata.get('wsi_mpp', 0.25)
            output_mpp = self.segmentation_metadata.get('output_mpp', 8.0)
            scale_factor = wsi_mpp / output_mpp
            
            # ROI를 mask 좌표로 변환
            roi_mask_x_min = int((roi_x_min - offset_x) * scale_factor)
            roi_mask_y_min = int((roi_y_min - offset_y) * scale_factor)
            roi_mask_x_max = int((roi_x_max - offset_x) * scale_factor)
            roi_mask_y_max = int((roi_y_max - offset_y) * scale_factor)
            
            # Boundary check
            roi_mask_x_min = max(0, min(roi_mask_x_min, mask_w))
            roi_mask_y_min = max(0, min(roi_mask_y_min, mask_h))
            roi_mask_x_max = max(0, min(roi_mask_x_max, mask_w))
            roi_mask_y_max = max(0, min(roi_mask_y_max, mask_h))
            
            # ROI 영역만 컬러 적용
            roi_mask = mask[roi_mask_y_min:roi_mask_y_max, roi_mask_x_min:roi_mask_x_max]
            for cls_id, color in seg_colors_rgb.items():
                mask_indices = (roi_mask == cls_id)
                rgba_image[roi_mask_y_min:roi_mask_y_max, roi_mask_x_min:roi_mask_x_max][mask_indices] = color
        else:
            # 전체 영역 컬러 적용
            for cls_id, color in seg_colors_rgb.items():
                mask_indices = (mask == cls_id)
                rgba_image[mask_indices] = color
        
        self.segmentation_rgba_cache = rgba_image
    
    def update_segmentation_overlay(self):
        """Segmentation 오버레이 업데이트 (미리 만들어진 RGBA 이미지 사용)"""
        if self.segmentation_mask is None or not hasattr(self, 'segmentation_rgba_cache') or self.segmentation_rgba_cache is None:
            return
        
        # 기존 오버레이 제거
        if self.segmentation_overlay_item:
            try:
                self.scene.removeItem(self.segmentation_overlay_item)
            except RuntimeError:
                pass
            self.segmentation_overlay_item = None
        
        import numpy as np
        from PyQt5.QtGui import QImage, QPixmap
        
        # 가시성 필터링된 RGBA 이미지 생성
        rgba_filtered = self.segmentation_rgba_cache.copy()
        
        # 숨김 처리된 클래스는 투명하게
        for cls_id, visible in self.segmentation_class_visibility.items():
            if not visible:
                mask_indices = (self.segmentation_mask == cls_id)
                rgba_filtered[mask_indices] = [0, 0, 0, 0]  # 투명
        
        # QPixmap으로 변환
        h, w = rgba_filtered.shape[:2]
        bytes_per_line = 4 * w
        qimage = QImage(rgba_filtered.data, w, h, bytes_per_line, QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimage)
        
        # 실제 WSI 좌표 계산
        region_offset = self.segmentation_metadata.get('region_offset', (0, 0))
        offset_x, offset_y = region_offset
        
        wsi_mpp = self.segmentation_metadata.get('wsi_mpp', 0.25)
        output_mpp = self.segmentation_metadata.get('output_mpp', 8.0)
        scale_factor = wsi_mpp / output_mpp
        actual_scale = 1.0 / scale_factor
        
        # 오버레이 아이템 생성
        self.segmentation_overlay_item = QGraphicsPixmapItem(pixmap)
        self.segmentation_overlay_item.setPos(offset_x, offset_y)
        self.segmentation_overlay_item.setScale(actual_scale)
        self.segmentation_overlay_item.setZValue(45)  # Detection 오버레이보다 아래
        
        self.scene.addItem(self.segmentation_overlay_item)
    
    def set_segmentation_class_visibility(self, cls_id, visible):
        """Segmentation 클래스 가시성 설정"""
        if self.segmentation_class_visibility is not None:
            self.segmentation_class_visibility[cls_id] = visible
            self.update_segmentation_overlay()
    
    def clear_segmentation_overlay(self):
        """Segmentation 오버레이 제거"""
        if self.segmentation_overlay_item:
            try:
                self.scene.removeItem(self.segmentation_overlay_item)
            except RuntimeError:
                pass
            self.segmentation_overlay_item = None
        
        self.segmentation_mask = None
        self.segmentation_metadata = None
        self.segmentation_class_names = None
        self.segmentation_class_visibility = {}
        self.segmentation_roi_bounds = None

        if hasattr(self, 'segmentation_rgba_cache'):
            self.segmentation_rgba_cache = None
        if hasattr(self, 'segmentation_roi_polygons'):
            self.segmentation_roi_polygons = None
    
    # ── Virtual Stain Overlay ──

    def set_virtual_stain_overlay(self, canvas, metadata):
        """
        Virtual stain 결과를 WSI 좌표에 오버레이로 표시.
        canvas: np.ndarray (H, W, 3) uint8 RGB
        metadata: dict with 'roi_origin', 'target_mpp', 'canvas_l0_w', 'canvas_l0_h'
        """
        self.virtual_stain_canvas = canvas
        self.virtual_stain_metadata = metadata
        self.virtual_stain_visible = True
        self.update_virtual_stain_overlay()

    def update_virtual_stain_overlay(self):
        """Virtual stain 오버레이를 현재 뷰에 맞게 업데이트"""
        if self.virtual_stain_canvas is None or self.virtual_stain_metadata is None:
            return

        # 기존 아이템 제거
        if self.virtual_stain_overlay_item:
            try:
                self.scene.removeItem(self.virtual_stain_overlay_item)
            except RuntimeError:
                pass
            self.virtual_stain_overlay_item = None

        if not self.virtual_stain_visible:
            return

        import numpy as np
        from PyQt5.QtGui import QImage, QPixmap

        canvas = self.virtual_stain_canvas
        meta = self.virtual_stain_metadata
        h, w = canvas.shape[:2]

        # WSI level-0 좌표 원점
        origin_x, origin_y = meta.get('roi_origin', (0, 0))
        # canvas가 커버하는 level-0 영역 크기
        canvas_l0_w = meta.get('canvas_l0_w', w)
        canvas_l0_h = meta.get('canvas_l0_h', h)

        # scale: canvas 1px이 WSI level-0에서 몇 px인지
        actual_scale_x = canvas_l0_w / w
        actual_scale_y = canvas_l0_h / h
        actual_scale = (actual_scale_x + actual_scale_y) / 2.0

        # RGB → QPixmap
        bytes_per_line = 3 * w
        qimage = QImage(canvas.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimage)

        self.virtual_stain_overlay_item = QGraphicsPixmapItem(pixmap)
        self.virtual_stain_overlay_item.setPos(origin_x, origin_y)
        self.virtual_stain_overlay_item.setScale(actual_scale)
        self.virtual_stain_overlay_item.setZValue(40)  # 타일 위, segmentation 아래
        self.scene.addItem(self.virtual_stain_overlay_item)

    def toggle_virtual_stain_overlay(self):
        """Virtual stain 오버레이 표시/숨김 토글"""
        if self.virtual_stain_canvas is None:
            return False
        self.virtual_stain_visible = not self.virtual_stain_visible
        self.update_virtual_stain_overlay()
        return self.virtual_stain_visible

    def clear_virtual_stain_overlay(self):
        """Virtual stain 오버레이 제거"""
        if self.virtual_stain_overlay_item:
            try:
                self.scene.removeItem(self.virtual_stain_overlay_item)
            except RuntimeError:
                pass
            self.virtual_stain_overlay_item = None

        self.virtual_stain_canvas = None
        self.virtual_stain_metadata = None
        self.virtual_stain_visible = True

    def set_detection_class_visibility(self, cls_id, visible):
        """특정 클래스의 가시성 설정"""
        if self.detection_overlay:
            self.detection_overlay.set_class_visibility(cls_id, visible)
            self.update_detection_overlay()
    
    def set_detection_opacity(self, opacity):
        """검출 결과 오버레이 투명도 설정 (0.0 ~ 1.0)"""
        if self.detection_overlay_item:
            self.detection_overlay_item.setOpacity(opacity)
    
    # ============================================
    
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
                try:
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
                except RuntimeError:
                    self.current_drawing = None
                    return
                
                # 점 추가
                if self.current_drawing:
                    try:
                        self.current_drawing.add_point(scene_pos.x(), scene_pos.y())
                    except RuntimeError:
                        self.current_drawing = None
                        return
                
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
        
        elif self.annotation_mode == AnnotationMode.DRAWING_RECTANGLE:
            if event.button() == Qt.LeftButton:
                # Scene 좌표로 변환
                scene_pos = self.mapToScene(event.pos())
                
                # Rectangle 그리기 시작
                self.current_drawing = DrawingRectangleItem(self.annotation_color)
                self.current_drawing.set_start_point(scene_pos.x(), scene_pos.y())
                self.scene.addItem(self.current_drawing)
                self.is_drawing_drag = True
                
                event.accept()
                return
            elif event.button() == Qt.RightButton:
                # 우클릭: 취소
                self.cancel_drawing()
                event.accept()
                return
        
        elif self.annotation_mode == AnnotationMode.DRAWING_POINT:
            if event.button() == Qt.LeftButton:
                # Scene 좌표로 변환
                scene_pos = self.mapToScene(event.pos())
                
                # Point 즉시 생성
                self.finish_drawing_point(scene_pos.x(), scene_pos.y())
                
                event.accept()
                return
            elif event.button() == Qt.RightButton:
                # 우클릭: 모드 종료
                self.set_annotation_mode(AnnotationMode.NONE)
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
            try:
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
            except RuntimeError:
                self.current_drawing = None
                return
            
            event.accept()
            return
        
        elif self.annotation_mode == AnnotationMode.DRAWING_RECTANGLE and self.is_drawing_drag and self.current_drawing:
            # Rectangle 그리기 중
            scene_pos = self.mapToScene(event.pos())
            self.current_drawing.update_end_point(scene_pos.x(), scene_pos.y())
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
            
            # Rectangle 그리기 완료
            if self.annotation_mode == AnnotationMode.DRAWING_RECTANGLE and self.is_drawing_drag:
                self.finish_drawing_rectangle()
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
            if self.annotation_mode in [AnnotationMode.DRAWING_POLYGON, 
                                       AnnotationMode.DRAWING_RECTANGLE,
                                       AnnotationMode.DRAWING_POINT]:
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
        elif mode == AnnotationMode.DRAWING_RECTANGLE:
            self.setCursor(Qt.CrossCursor)
        elif mode == AnnotationMode.DRAWING_POINT:
            self.setCursor(Qt.CrossCursor)
        elif mode == AnnotationMode.EDITING:
            self.setCursor(Qt.ArrowCursor)
            # 선택된 annotation 편집 시작
            if self.annotation_list.selected_annotation:
                self.start_editing_annotation(self.annotation_list.selected_annotation)
        else:
            self.setCursor(Qt.ArrowCursor)
            # 편집 모드 종료
            for item in list(self.annotation_items.values()):
                try:
                    item.stop_editing()
                except RuntimeError:
                    pass
    
    def start_drawing_polygon(self):
        """Polygon 그리기 시작"""
        self.set_annotation_mode(AnnotationMode.DRAWING_POLYGON)
        self.annotation_color = QColor(0, 255, 0)  # 초록색
        self.current_drawing = DrawingPolygonItem(self.annotation_color)
        self.scene.addItem(self.current_drawing)
    
    def finish_drawing_polygon(self):
        """Polygon 그리기 완료"""
        try:
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

                # 그래픽 아이템 생성
                self.add_annotation_item(annotation)

                # 방금 생성한 annotation을 선택 상태로 설정 (제어점은 선택 시에만 표시됨)
                self.select_annotation(annotation)

                # 시그널 발생
                self.annotationAdded.emit(annotation)
        except RuntimeError:
            self.current_drawing = None
        
        # 그리기 아이템 제거
        if self.current_drawing:
            try:
                self.current_drawing.remove_start_point_indicator()
                self.scene.removeItem(self.current_drawing)
            except RuntimeError:
                pass
            self.current_drawing = None

        # 드래그 상태 초기화
        self.is_drawing_drag = False
        self.drag_start_pos = None
        self.last_view_pos = None

        # 지속 그리기 모드라면 같은 모드 유지하여 다음 그리기를 바로 시작할 수 있게 함
        if self.keep_drawing and self.annotation_mode == AnnotationMode.DRAWING_POLYGON:
            # 새 그리기 아이템 생성
            self.current_drawing = DrawingPolygonItem(self.annotation_color)
            self.scene.addItem(self.current_drawing)
        else:
            self.set_annotation_mode(AnnotationMode.NONE)
    
    def cancel_drawing(self):
        """그리기 취소"""
        if self.current_drawing:
            try:
                # 시작점 표시 제거 (polygon만 해당)
                if hasattr(self.current_drawing, 'remove_start_point_indicator'):
                    self.current_drawing.remove_start_point_indicator()
                self.scene.removeItem(self.current_drawing)
            except RuntimeError:
                pass
            self.current_drawing = None
        
        # 드래그 상태 초기화
        self.is_drawing_drag = False
        self.drag_start_pos = None
        
        # 지속 그리기 모드면 모드를 유지, 아니면 종료
        if not self.keep_drawing:
            self.set_annotation_mode(AnnotationMode.NONE)
            self.drawingCancelled.emit()  # 시그널 발생
        else:
            # keep_drawing인 경우에는 현재 그리기 상태만 초기화
            self.last_view_pos = None
    
    def start_drawing_rectangle(self):
        """Rectangle 그리기 시작"""
        self.set_annotation_mode(AnnotationMode.DRAWING_RECTANGLE)
        self.annotation_color = QColor(255, 0, 0)  # 빨간색
        # Rectangle은 마우스 press 시 생성
    
    def finish_drawing_rectangle(self):
        """Rectangle 그리기 완료"""
        try:
            if self.current_drawing and isinstance(self.current_drawing, DrawingRectangleItem) and self.current_drawing.is_valid():
                # Annotation 생성
                self.annotation_counter += 1
                annotation = Annotation(
                    name=f"Rectangle_{self.annotation_counter}",
                    type=AnnotationType.RECTANGLE,
                    coordinates=self.current_drawing.get_coordinates(),
                    color=(self.annotation_color.red(),
                           self.annotation_color.green(),
                           self.annotation_color.blue())
                )

                # AnnotationList에 추가
                self.annotation_list.add_annotation(annotation)

                # 그래픽 아이템 생성
                self.add_annotation_item(annotation)

                # 방금 생성한 annotation을 선택 상태로 설정 (제어점은 선택 시에만 표시됨)
                self.select_annotation(annotation)

                # 시그널 발생
                self.annotationAdded.emit(annotation)
        except RuntimeError:
            self.current_drawing = None

        # 그리기 아이템 제거
        if self.current_drawing:
            try:
                self.scene.removeItem(self.current_drawing)
            except RuntimeError:
                pass
            self.current_drawing = None
        
        # 드래그 상태 초기화
        self.is_drawing_drag = False
        self.drag_start_pos = None
        
        # 지속 그리기 모드라면 다음 그리기를 위해 모드를 유지, 아니면 종료
        if not self.keep_drawing:
            self.set_annotation_mode(AnnotationMode.NONE)
    
    def start_drawing_point(self):
        """Point 그리기 시작"""
        self.set_annotation_mode(AnnotationMode.DRAWING_POINT)
        self.annotation_color = QColor(0, 0, 255)  # 파란색
        # Point는 클릭 시 즉시 생성
    
    def finish_drawing_point(self, x: float, y: float):
        """Point 그리기 완료"""
        # Annotation 생성
        self.annotation_counter += 1
        annotation = Annotation(
            name=f"Point_{self.annotation_counter}",
            type=AnnotationType.POINT,
            coordinates=[(x, y)],
            color=(self.annotation_color.red(), 
                   self.annotation_color.green(), 
                   self.annotation_color.blue())
        )
        
        # AnnotationList에 추가
        self.annotation_list.add_annotation(annotation)
        
        # 그래픽 아이템 생성
        self.add_annotation_item(annotation)
        
        # 방금 생성한 annotation 선택
        annotation.selected = True
        
        # 시그널 발생
        self.annotationAdded.emit(annotation)
        
        # 지속 그리기 모드가 아니면 일반 모드로 복귀
        if not self.keep_drawing:
            self.set_annotation_mode(AnnotationMode.NONE)

    def exit_drawing_mode(self):
        """그리기 모드 완전 종료 (툴을 끔)"""
        # 현재 그리기 아이템 제거
        if self.current_drawing:
            if hasattr(self.current_drawing, 'remove_start_point_indicator'):
                self.current_drawing.remove_start_point_indicator()
            self.scene.removeItem(self.current_drawing)
            self.current_drawing = None
        
        # 플래그 및 상태 초기화
        self.keep_drawing = False
        self.is_drawing_drag = False
        self.drag_start_pos = None
        self.last_view_pos = None
        
        self.set_annotation_mode(AnnotationMode.NONE)
        self.drawingCancelled.emit()    
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
            # 편집 모드(제어점)가 활성화되어 있으면 제어점을 먼저 제거
            try:
                item.stop_editing()
            except Exception:
                pass
            try:
                self.scene.removeItem(item)
            except RuntimeError:
                pass
            del self.annotation_items[annotation.id]
        
        # AnnotationList에서 제거
        self.annotation_list.remove_annotation(annotation)
    
    def select_annotation(self, annotation: Annotation):
        """Annotation 선택 - 선택된 annotation에 대해서만 제어점 표시"""
        self.annotation_list.select_annotation(annotation)
        
        # 선택된 annotation만 편집 모드(제어점 표시)를 활성화하고, 나머지는 비활성화
        for ann in self.annotation_list.annotations:
            if ann.id in self.annotation_items:
                item = self.annotation_items[ann.id]
                if annotation and ann.id == annotation.id:
                    item.start_editing()
                else:
                    item.stop_editing()
                item.update_style()
        
        self.annotationSelected.emit(annotation)

    def center_on_annotation(self, annotation: Annotation):
        """Annotation의 중심 좌표로 뷰를 이동시킴"""
        if not annotation or not annotation.coordinates:
            return

        x_min, y_min, x_max, y_max = annotation.get_bounds()
        center_x = (x_min + x_max) / 2.0
        center_y = (y_min + y_max) / 2.0

        # 중심으로 이동
        self.centerOn(center_x, center_y)
        self.update_field_of_view()
    
    def start_editing_annotation(self, annotation: Annotation):
        """Annotation 편집 시작"""
        if annotation.id in self.annotation_items:
            item = self.annotation_items[annotation.id]
            item.start_editing()
    
    def clear_annotations(self):
        """모든 Annotation 제거"""
        # 그래픽 아이템 제거
        for item in list(self.annotation_items.values()):
            # 편집 모드(제어점)가 활성화되어 있으면 제어점을 먼저 제거
            try:
                item.stop_editing()
            except Exception:
                pass
            try:
                self.scene.removeItem(item)
            except RuntimeError:
                pass
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
