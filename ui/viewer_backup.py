"""
병리 이미지 뷰어 메인 윈도우
대용량 병리 이미지(WSI) 로드, 표시, 줌/패닝 기능 제공
ASAP 구조를 참고한 타일 기반 렌더링 시스템
"""

from PyQt5 import uic
from PyQt5.QtWidgets import QMainWindow, QGraphicsView, QGraphicsScene, QFileDialog, QGraphicsPixmapItem, QVBoxLayout, QHBoxLayout
from PyQt5.QtCore import Qt, QPoint, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import QPixmap, QImage, QWheelEvent, QMouseEvent, QPainter, QBrush, QColor
import numpy as np
from pathlib import Path
import os
import sys

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.wsi_tile_manager import WSITileManager
from ui.minimap import MiniMap


class WSIViewer(QGraphicsView):
    """WSI 표시 및 마우스 인터랙션을 처리하는 커스텀 위젯 (ASAP PathologyViewer 참고)"""
    
    zoomChanged = pyqtSignal(float)
    fieldOfViewChanged = pyqtSignal(QRectF, int)
    
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
        self.current_level = -1  # 현재 표시 중인 레벨 추적 (ASAP 방식)
        
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
        
        # 미니맵 위젯 (오버레이)
        self.minimap = MiniMap(self)
        self.minimap.hide()  # 초기에는 숨김
    
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
    
    def resizeEvent(self, event):
        """윈도우 크기 변경 시 미니맵 위치 조정"""
        super().resizeEvent(event)
        if hasattr(self, 'minimap'):
            # 왼쪽 하단에 배치 (10px 여백)
            minimap_x = 10
            minimap_y = self.height() - self.minimap.height() - 10
            self.minimap.move(minimap_x, minimap_y)
    
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
        """줌 레벨 설정 (ASAP zoom 참고)"""
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
        new_zoom = self.zoom_level * 1.2
        self.set_zoom(new_zoom, anchor_pos)
    
    def zoom_out(self, anchor_pos=None):
        """줌 아웃"""
        new_zoom = self.zoom_level / 1.2
        self.set_zoom(new_zoom, anchor_pos)
    
    def update_field_of_view(self):
        """현재 보이는 영역 업데이트 및 타일 로딩 (ASAP PathologyViewer::updateFieldOfView 참고)"""
        if not self.tile_manager:
            return
        
        # 현재 보이는 영역 계산
        view_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        
        # 4단계 레벨 시스템 사용
        level = self.tile_manager.get_stage_level(self.zoom_level)
        
        # print(f"FOV 업데이트: view_rect={view_rect.x():.0f},{view_rect.y():.0f} {view_rect.width():.0f}x{view_rect.height():.0f}, level={level}, zoom={self.zoom_level:.4f}")
        
        # ★ 레벨 변경 감지 (이전 타일은 유지하고 새 타일을 위에 덮음)
        level_changed = (self.current_level != level)
        if level_changed:
            # print(f"레벨 변경: {self.current_level} -> {level}, 이전 타일 유지하고 새 타일 덮어씌움")
            self.current_level = level
        
        # 시그널 발생
        self.fieldOfViewChanged.emit(view_rect, level)
        
        # 타일 로딩 요청 (항상 실행, 캐시에 없는 타일만 로드)
        self.tile_manager.load_tiles_for_view(view_rect, level)
        
        # 미니맵 업데이트
        if hasattr(self, 'minimap') and self.minimap.isVisible():
            self.minimap.update_field_of_view(view_rect)
            # 캐시 상태 업데이트
            cached_tiles = self.tile_manager.get_cached_tiles_info()
            self.minimap.update_cached_tiles(cached_tiles)
        
        # ★ 즉시 캐시된 타일 렌더링 (레벨 변경이든 패닝이든 항상)
        self.on_tiles_updated()
    
    def on_tiles_updated(self):
        """타일 업데이트 시 호출 - 새로 로드된 타일만 추가"""
        if not self.tile_manager:
            return
        
        # 현재 보이는 영역 계산
        view_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        level = self.tile_manager.get_stage_level(self.zoom_level)
        level_downsample = self.tile_manager.get_level_downsample(level)
        
        # 타일 크기 (레벨 0 기준)
        tile_size = 512
        
        # 보이는 타일 범위 계산 (레벨 0 좌표계 기준)
        start_tile_x = max(0, int(view_rect.left() / tile_size / level_downsample))
        start_tile_y = max(0, int(view_rect.top() / tile_size / level_downsample))
        end_tile_x = int(view_rect.right() / tile_size / level_downsample) + 2
        end_tile_y = int(view_rect.bottom() / tile_size / level_downsample) + 2
        
        # print(f"타일 렌더링: 타일 범위 x[{start_tile_x}~{end_tile_x}] y[{start_tile_y}~{end_tile_y}], level={level}")
        
        # 타일 렌더링
        tiles_rendered = 0
        tiles_from_cache = 0
        for ty in range(start_tile_y, end_tile_y):
            for tx in range(start_tile_x, end_tile_x):
                cache_key = (tx, ty, level)
                
                # 이미 렌더링된 타일인지 확인
                if cache_key not in self.tile_items:
                    pixmap = self.tile_manager.get_tile(tx, ty, level)
                    if pixmap:
                        tiles_from_cache += 1
                        # 타일 위치 계산 (레벨 0 좌표계)
                        tile_x_pos = tx * tile_size * level_downsample
                        tile_y_pos = ty * tile_size * level_downsample
                        
                        # 타일 아이템 생성 및 추가
                        item = QGraphicsPixmapItem(pixmap)
                        item.setPos(tile_x_pos, tile_y_pos)
                        
                        # 타일 크기 조정 (레벨 0 좌표계에 맞춤)
                        scale = level_downsample
                        item.setScale(scale)
                        
                        # Z-value 설정: 레벨이 낮을수록(고해상도) 위에 표시
                        # 레벨 0 = z=4, 레벨 1 = z=3, 레벨 2 = z=2, 레벨 3 = z=1
                        item.setZValue(10 - level)
                        
                        self.scene.addItem(item)
                        self.tile_items[cache_key] = item
                        tiles_rendered += 1
        
        if tiles_rendered > 0:
            # print(f"  -> {tiles_rendered}개 타일 렌더링됨 (캐시에서: {tiles_from_cache}개)")
            # 미니맵 캐시 상태 업데이트
            if hasattr(self, 'minimap') and self.minimap.isVisible():
                cached_tiles = self.tile_manager.get_cached_tiles_info()
                self.minimap.update_cached_tiles(cached_tiles)
        
        # 타일 정리: 현재 레벨의 보이지 않는 타일 + 이전 레벨의 타일 제거
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
            # 다른 레벨이면: 현재 레벨 타일로 덮인 영역만 제거 (배경 유지)
            else:
                # 이전 레벨 타일의 영역을 현재 레벨 좌표로 변환
                old_downsample = self.tile_manager.get_level_downsample(lv)
                old_tile_x0 = tx * tile_size * old_downsample
                old_tile_y0 = ty * tile_size * old_downsample
                old_tile_x1 = old_tile_x0 + tile_size * old_downsample
                old_tile_y1 = old_tile_y0 + tile_size * old_downsample
                
                # 이 영역이 현재 레벨의 타일로 완전히 덮였는지 확인
                covered = True
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
                            if (new_tx, new_ty, level) not in self.tile_items:
                                covered = False
                                break
                    if not covered:
                        break
                
                # 완전히 덮였으면 제거
                if covered:
                    item = self.tile_items[key]
                    self.scene.removeItem(item)
                    keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self.tile_items[key]
    
    def wheelEvent(self, event: QWheelEvent):
        """마우스 휠로 줌 인/아웃 (ASAP wheelEvent 참고)"""
        if not self.tile_manager:
            return
        
        # 휠 방향에 따라 줌
        delta = event.angleDelta().y()
        anchor_pos = event.pos()
        
        if delta > 0:
            self.zoom_in(anchor_pos)
        else:
            self.zoom_out(anchor_pos)
        
        event.accept()
    
    def mousePressEvent(self, event: QMouseEvent):
        """마우스 버튼 누름 - 패닝 시작 (ASAP mousePressEvent 참고)"""
        if event.button() == Qt.LeftButton:
            self.is_panning = True
            self.last_pan_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            event.ignore()
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """마우스 이동 - 패닝 (ASAP pan 참고)"""
        if self.is_panning:
            # 마우스 이동량 계산
            delta = event.pos() - self.last_pan_pos
            self.last_pan_pos = event.pos()
            
            # 스크롤바 값 업데이트 (패닝)
            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())
            
            self.update_field_of_view()
            event.accept()
        else:
            # 마우스 좌표 표시
            if self.tile_manager:
                scene_pos = self.mapToScene(event.pos())
                # 상위 위젯(MainWindow)의 상태바에 좌표 표시
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
        """마우스 버튼 놓음 - 패닝 종료 (ASAP mouseReleaseEvent 참고)"""
        if event.button() == Qt.LeftButton:
            self.is_panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            event.ignore()
    
    def resizeEvent(self, event):
        """윈도우 크기 변경 시 처리"""
        super().resizeEvent(event)
        self.update_field_of_view()
    
    def close(self):
        """리소스 정리"""
        if self.tile_manager:
            self.tile_manager.close()
            self.tile_manager = None
        
        self.scene.clear()
        self.tile_items.clear()


class PathologyViewer(QMainWindow):
    """병리 이미지 뷰어 메인 윈도우"""
    
    def __init__(self):
        super().__init__()
        self.current_image_path = None
        
        # UI 파일 로드
        ui_path = os.path.join(os.path.dirname(__file__), 'viewer.ui')
        uic.loadUi(ui_path, self)
        
        # 커스텀 WSIViewer 위젯으로 교체
        self.setup_wsi_viewer()
        
        # 시그널 연결
        self.connect_signals()
        
        # 초기 상태 설정
        self.statusbar.showMessage("준비됨")
        
    def setup_wsi_viewer(self):
        """imageViewer QLabel을 커스텀 WSIViewer로 교체"""
        # 기존 QLabel 찾기
        old_viewer = self.imageViewer
        parent = old_viewer.parent()
        layout = old_viewer.parent().layout()
        
        # 기존 위젯 제거
        layout.removeWidget(old_viewer)
        old_viewer.deleteLater()
        
        # 새로운 레이아웃 생성 (WSIViewer + MiniMap)
        container = parent
        main_layout = QHBoxLayout()
        
        # WSIViewer 생성 및 추가
        self.wsi_viewer = WSIViewer(container)
        main_layout.addWidget(self.wsi_viewer, stretch=1)
        
        # 오른쪽 패널 (미니맵은 오버레이로 사용하므로 숨김)
        # right_panel = QVBoxLayout()
        # self.minimap = MiniMap(container)
        # right_panel.addWidget(self.minimap)
        # right_panel.addStretch(1)
        # main_layout.addLayout(right_panel)
        
        # 레이아웃 적용
        layout.insertLayout(0, main_layout)
        
        # 시그널 연결
        self.wsi_viewer.fieldOfViewChanged.connect(self.on_field_of_view_changed)
        # self.minimap.positionClicked.connect(self.on_minimap_clicked)  # 오버레이 미니맵에서 처리
        
    def connect_signals(self):
        """UI 요소에 시그널 연결"""
        # 툴바 액션 연결
        self.actionOpenImage.triggered.connect(self.open_image)
        self.actionZoomIn.triggered.connect(self.wsi_viewer.zoom_in)
        self.actionZoomOut.triggered.connect(self.wsi_viewer.zoom_out)
        self.actionFitWindow.triggered.connect(self.wsi_viewer.fit_to_window)
        self.actionSaveResults.triggered.connect(self.save_results)
                # 정보 버튼 연결 (UI에 있는 경우)
        if hasattr(self, 'actionSlideInfo'):
            self.actionSlideInfo.triggered.connect(self.show_slide_info)
                # AI 버튼 연결
        self.btnSegmentation.clicked.connect(self.run_segmentation)
        self.btnClassification.clicked.connect(self.run_classification)
        self.btnDetection.clicked.connect(self.run_detection)
        
    
    def open_image(self):
        """이미지 파일 열기"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "병리 이미지 선택",
            "",
            "Image Files (*.png *.jpg *.jpeg *.tif *.tiff *.svs *.ndpi);;All Files (*)"
        )
        
        if file_path:
            self.load_image(file_path)
    
    def load_image(self, file_path):
        """이미지 로드 및 정보 업데이트"""
        if self.wsi_viewer.load_wsi(file_path):
            self.current_image_path = file_path
            
            # 이미지 정보 업데이트
            file_name = Path(file_path).name
            self.statusbar.showMessage(f"이미지 로드 완료: {file_name}")
            self.resultText.clear()
        else:
            self.statusbar.showMessage("이미지 로드 실패")
    
    def on_field_of_view_changed(self, fov_rect, level):
        """보이는 영역 변경 시 호출 (미니맵은 WSIViewer 내부에서 처리)"""
        pass
    
    def on_minimap_clicked(self, x, y):
        """미니맵 클릭 시 해당 위치로 이동 (미사용)"""
        pass
    
    def show_slide_info(self):
        """슬라이드 정보 표시 (별도 다이얼로그)"""
        if not self.wsi_viewer.tile_manager:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, "정보", "먼저 이미지를 로드해주세요.")
            return
        
        info = self.wsi_viewer.tile_manager.get_slide_info()
        if not info:
            return
        
        # 정보 다이얼로그 생성
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTextEdit, QPushButton, QGroupBox, QFormLayout
        
        dialog = QDialog(self)
        dialog.setWindowTitle("슬라이드 정보")
        dialog.setMinimumWidth(600)
        
        main_layout = QVBoxLayout(dialog)
        
        # 기본 정보 그룹
        basic_group = QGroupBox("기본 정보")
        basic_layout = QFormLayout()
        
        filename_edit = QLineEdit(info['filename'])
        filename_edit.setReadOnly(True)
        basic_layout.addRow("파일명:", filename_edit)
        
        vendor_edit = QLineEdit(info['vendor'])
        vendor_edit.setReadOnly(True)
        basic_layout.addRow("벤더:", vendor_edit)
        
        objective_edit = QLineEdit(f"{info['objective_power']}x")
        objective_edit.setReadOnly(True)
        basic_layout.addRow("배율:", objective_edit)
        
        basic_group.setLayout(basic_layout)
        main_layout.addWidget(basic_group)
        
        # 크기 정보 그룹
        size_group = QGroupBox("크기 정보")
        size_layout = QFormLayout()
        
        dimensions_edit = QLineEdit(f"{info['dimensions'][0]} x {info['dimensions'][1]} pixels")
        dimensions_edit.setReadOnly(True)
        size_layout.addRow("픽셀 크기 (Level 0):", dimensions_edit)
        
        if info['mpp_x'] and info['mpp_y']:
            mpp_edit = QLineEdit(f"{info['mpp_x']:.4f} x {info['mpp_y']:.4f} µm/pixel")
            mpp_edit.setReadOnly(True)
            size_layout.addRow("MPP:", mpp_edit)
            
            # 물리적 크기 계산
            width_mm = info['dimensions'][0] * info['mpp_x'] / 1000
            height_mm = info['dimensions'][1] * info['mpp_y'] / 1000
            physical_edit = QLineEdit(f"{width_mm:.2f} x {height_mm:.2f} mm")
            physical_edit.setReadOnly(True)
            size_layout.addRow("물리적 크기:", physical_edit)
        
        size_group.setLayout(size_layout)
        main_layout.addWidget(size_group)
        
        # 레벨 정보 그룹
        level_group = QGroupBox("레벨 정보")
        level_layout = QVBoxLayout()
        
        level_count_label = QLabel(f"총 레벨 수: {info['level_count']}")
        level_layout.addWidget(level_count_label)
        
        level_text = QTextEdit()
        level_text.setReadOnly(True)
        level_text.setMaximumHeight(150)
        
        level_info_str = ""
        for i, (dim, downsample) in enumerate(zip(info['level_dimensions'], info['level_downsamples'])):
            level_info_str += f"Level {i}: {dim[0]} x {dim[1]} pixels (downsample: {downsample:.2f})\n"
        
        level_text.setPlainText(level_info_str)
        level_layout.addWidget(level_text)
        
        level_group.setLayout(level_layout)
        main_layout.addWidget(level_group)
        
        # 닫기 버튼
        close_button = QPushButton("닫기")
        close_button.clicked.connect(dialog.accept)
        main_layout.addWidget(close_button)
        
        dialog.exec_()
    
    
    def run_segmentation(self):
        """조직 분할 AI 실행 (추후 구현)"""
        if self.current_image_path is None:
            self.resultText.setText("먼저 이미지를 로드해주세요.")
            return
        
        self.resultText.setText("조직 분할 분석 실행 중...\n(AI 모델 통합 예정)")
        self.statusbar.showMessage("조직 분할 분석 실행 중...")
    
    def run_classification(self):
        """암 분류 AI 실행 (추후 구현)"""
        if self.current_image_path is None:
            self.resultText.setText("먼저 이미지를 로드해주세요.")
            return
        
        self.resultText.setText("암 분류 분석 실행 중...\n(AI 모델 통합 예정)")
        self.statusbar.showMessage("암 분류 분석 실행 중...")
    
    def run_detection(self):
        """병변 검출 AI 실행 (추후 구현)"""
        if self.current_image_path is None:
            self.resultText.setText("먼저 이미지를 로드해주세요.")
            return
        
        self.resultText.setText("병변 검출 분석 실행 중...\n(AI 모델 통합 예정)")
        self.statusbar.showMessage("병변 검출 분석 실행 중...")
    
    def save_results(self):
        """분석 결과 저장 (추후 구현)"""
        self.statusbar.showMessage("결과 저장 기능 (추후 구현)")
    
    def closeEvent(self, event):
        """윈도우 닫기 시 리소스 정리"""
        self.wsi_viewer.close()
        event.accept()
