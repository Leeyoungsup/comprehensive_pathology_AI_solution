"""
MeDICus Studio - Main Window
Handles UI composition and event processing
"""

import json
import sys
import os
import time
from datetime import datetime
from functools import partial
from pathlib import Path

import numpy as np

from PyQt5 import uic
from PyQt5.QtWidgets import (
    QMainWindow, QFileDialog, QMessageBox,
    QApplication, QListWidgetItem, QWidget,
    QHBoxLayout, QLabel, QSlider, QCheckBox,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon, QPixmap, QColor

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from ui.wsi_view_widget import WSIViewWidget, AnnotationMode
from ui.annotation_panel import AnnotationPanel
from ui.dialogs import show_slide_info_dialog
from core.annotation import AnnotationType
from utils.coordinate_utils import mask_to_polygons, polygons_to_mask
from backend.services import (
    DetectionService,
    SlideService,
    AnnotationService,
    EpithelialClassificationService
)


class PathologyViewer(QMainWindow):
    """MeDICus Studio Main Window"""
    
    def __init__(self):
        super().__init__()
        self.current_image_path = None
        
        # Load UI file
        ui_path = os.path.join(os.path.dirname(__file__), 'viewer.ui')
        uic.loadUi(ui_path, self)
        
        # Set up WSI viewer widget
        self.setup_wsi_viewer()

        # Initialize service layer
        self.detection_service = DetectionService()
        self.slide_service = SlideService()
        self.annotation_service = AnnotationService()
        self.epithelial_classification_service = EpithelialClassificationService()
        
        # Initialize AI module variables (legacy, can be removed if needed)
        self.tissue_segmentation = None
        self.tissue_classification = None
        self.is_detection_running = False  # Detection running state

        # PD-L1 detection module
        self.pdl1_detection = None
        self.is_pdl1_running = False
        self.current_pdl1_result = None

        # Virtual Stain module
        self.virtual_stain_worker = None
        self.is_virtual_stain_running = False

        # Per-class detection result cache
        self.current_detection_result = None
        
        # Segmentation result cache
        self.current_segmentation_result = None
        self.is_segmentation_running = False
        self.tumor_seg_worker = None  # TumorSegmentationWorker 인스턴스

        # Tissue type (default: Stomach)
        self.current_tissue_type = "Stomach"
        
        # Connect signals
        self.connect_signals()

        # Additional UI element setup (programmatic)
        self.setup_ui_additions()

        # Initial state setup
        self.progressBar.setValue(0)
        self.progressLabel.setText("AI Progress")
        self.statusbar.showMessage("Ready")

    def setup_wsi_viewer(self):
        """Set up WSI viewer widget"""
        # Replace existing QLabel with custom WSIViewWidget
        old_viewer = self.imageViewer
        parent = old_viewer.parent()
        layout = old_viewer.parent().layout()
        
        # Remove existing widget
        layout.removeWidget(old_viewer)
        old_viewer.deleteLater()
        
        # WSI 뷰어만 추가 (전체 화면)
        self.wsi_viewer = WSIViewWidget(parent)
        layout.addWidget(self.wsi_viewer)
        
        # Annotation 패널을 오른쪽 패널에 추가
        self.annotation_panel = AnnotationPanel(self.rightPanel)
        self.annotation_panel.set_annotation_list(self.wsi_viewer.annotation_list)
        
        # 오른쪽 패널의 레이아웃에 추가 (verticalSpacer 다음에 삽입)
        right_layout = self.rightPanel.layout()
        right_layout.insertWidget(1, self.annotation_panel)
        
        # WSI 뷰어 시그널 연결
        self.wsi_viewer.fieldOfViewChanged.connect(self.on_field_of_view_changed)
        self.wsi_viewer.annotationAdded.connect(self.on_annotation_added)
        self.wsi_viewer.annotationSelected.connect(self.on_annotation_selected)
        self.wsi_viewer.annotationDeleted.connect(self.on_annotation_deleted)
        self.wsi_viewer.drawingCancelled.connect(self.on_drawing_cancelled)
        
        # Annotation 패널 시그널 연결
        self.annotation_panel.annotationSelected.connect(self.on_panel_annotation_selected)
        self.annotation_panel.annotationDeleted.connect(self.on_annotation_deleted)
        self.annotation_panel.clearAllRequested.connect(self.clear_roi)
        self.annotation_panel.saveRequested.connect(self.save_annotations)
        self.annotation_panel.loadRequested.connect(self.load_annotations)
    
    def setup_ui_additions(self):
        """추가 UI 요소 설정 (프로그래밍 방식으로 버튼 추가 등)"""
        # 자동저장 + 자동시각화 체크박스를 나란히 배치
        self.chkAutoSave = QCheckBox("Auto Save")
        self.chkAutoSave.setChecked(False)
        self.chkAutoSave.setToolTip("If checked, AI analysis results will be saved automatically to the WSI file location")

        self.chkAutoVisualize = QCheckBox("Auto Visualize")
        self.chkAutoVisualize.setChecked(False)
        self.chkAutoVisualize.setToolTip("If checked, the result visualization window will open automatically after detection completes")

        chk_row = QWidget()
        chk_layout = QHBoxLayout(chk_row)
        chk_layout.setContentsMargins(0, 0, 0, 0)
        chk_layout.addWidget(self.chkAutoSave)
        chk_layout.addWidget(self.chkAutoVisualize)
        self.groupBox.layout().addWidget(chk_row)
        chk_row.hide()  # 자동저장/자동시각화 체크박스 임시 숨김

    def setup_ai_modules(self):
        """
        AI 모듈 초기화 (Lazy Initialization)
        처음 사용 시에만 호출됨
        """
        # 검출 모듈은 DetectionService를 통해 관리
        # 시그널 중복 연결 방지 (run_detection 호출 시마다 이 함수가 불리므로)
        if not getattr(self, '_detection_signals_connected', False):
            detection_module = self.detection_service.get_detection_module()
            detection_module.detectionComplete.connect(self.on_detection_complete)
            detection_module.detectionProgress.connect(self.on_ai_progress)
            detection_module.detectionStatus.connect(self.on_detection_status)
            detection_module.detectionError.connect(self.on_ai_error)
            self._detection_signals_connected = True
        
        # 조직 분할 (필요 시 생성)
        if self.tissue_segmentation is None:
            from ai import TissueSegmentation
            self.tissue_segmentation = TissueSegmentation()
            self.tissue_segmentation.segmentationComplete.connect(self.on_segmentation_complete)
            self.tissue_segmentation.segmentationProgress.connect(self.on_ai_progress)
            self.tissue_segmentation.segmentationError.connect(self.on_ai_error)
        
        # 암 분류 (필요 시 생성)
        if self.tissue_classification is None:
            from ai import TissueClassification
            self.tissue_classification = TissueClassification()
            self.tissue_classification.classificationComplete.connect(self.on_classification_complete)
            self.tissue_classification.classificationProgress.connect(self.on_ai_progress)
            self.tissue_classification.classificationError.connect(self.on_ai_error)
    
    def connect_signals(self):
        """UI 요소에 시그널 연결"""
        # 툴바 액션
        self.actionOpenImage.triggered.connect(self.open_image)
        self.actionZoomIn.triggered.connect(self.wsi_viewer.zoom_in)
        self.actionZoomOut.triggered.connect(self.wsi_viewer.zoom_out)
        self.actionFitWindow.triggered.connect(self.wsi_viewer.fit_to_window)
        self.actionSaveResults.triggered.connect(self.save_results)
        
        # 슬라이드 정보 버튼
        if hasattr(self, 'actionSlideInfo'):
            self.actionSlideInfo.triggered.connect(self.show_slide_info)
        
        # Annotation 툴바 액션 (viewer.ui에서 정의됨)
        self.actionDrawPolygon.toggled.connect(self.toggle_draw_polygon)
        self.actionDrawRectangle.toggled.connect(self.toggle_draw_rectangle)
        self.actionDrawPoint.toggled.connect(self.toggle_draw_point)
        if hasattr(self, 'actionStopDrawing'):
            self.actionStopDrawing.triggered.connect(self.stop_drawing)
        
        # AI 버튼
        self.btnSegmentation.clicked.connect(self.run_segmentation)
        self.btnClassification.clicked.connect(self.run_classification)
        self.btnHneCellDetection.clicked.connect(self.run_detection)
        self.btnTumorSegmentation.clicked.connect(self.run_tumor_segmentation)
        self.btnVisualization.clicked.connect(self.show_detection_visualization)
        self.btnPDL1Detection.clicked.connect(self.run_pdl1_detection)
        self.btnIHCtoHnEMembrane.clicked.connect(self.run_virtual_stain_ihc_membrane)
        self.chkShowVirtualStain.toggled.connect(self.toggle_virtual_stain)

        # 조직 타입 Radio button
        self.radioBreast.toggled.connect(self.on_tissue_type_changed)
        self.radioStomach.toggled.connect(self.on_tissue_type_changed)
        self.radioOther.toggled.connect(self.on_tissue_type_changed)

        # 결과 리스트 아이템 클릭 시그널
        self.resultList.itemClicked.connect(self.on_result_list_item_clicked)
        # 체크박스 변경 시그널 (가시성 토글 처리)
        self.resultList.itemChanged.connect(self.on_result_list_item_changed)

        # 전체 raw cells 저장 (confidence 슬라이더용, 재추론 없이 필터링)
        self.all_raw_cells = []
        self.current_class_thresholds = {}  # {cls_id: threshold}
        self.current_color_map = None
        self.is_pdl1_mode = False

        # confidence 슬라이더 debounce 타이머 (무거운 overlay 재구축을 지연)
        self._conf_debounce_timer = QTimer(self)
        self._conf_debounce_timer.setSingleShot(True)
        self._conf_debounce_timer.setInterval(250)
        self._conf_debounce_timer.timeout.connect(self._apply_confidence_filter)

        # 결과 관리 버튼
        self.btnClearResults.clicked.connect(self.clear_results)
        self.btnSaveResults.clicked.connect(self.save_detection_results)
        self.btnLoadResults.clicked.connect(self.load_detection_results)

    def on_tissue_type_changed(self):
        """Called when tissue type radio button changes"""
        if self.radioBreast.isChecked():
            self.current_tissue_type = "Breast"
            self.statusbar.showMessage("Tissue type: Breast (Epithelial reclassification enabled)")
            self.btnTumorSegmentation.setEnabled(True)
        elif self.radioStomach.isChecked():
            self.current_tissue_type = "Stomach"
            self.statusbar.showMessage("Tissue type: Stomach (Epithelial reclassification enabled)")
            self.btnTumorSegmentation.setEnabled(True)
        elif self.radioOther.isChecked():
            self.current_tissue_type = "Other"
            self.statusbar.showMessage("Tissue type: Other (Epithelial reclassification disabled)")
            self.btnTumorSegmentation.setEnabled(False)

    def open_image(self):
        """이미지 파일 열기"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Image",
            "",
            "Image Files (*.png *.jpg *.jpeg *.tif *.tiff *.svs *.ndpi);;All Files (*)"
        )
        
        if file_path:
            self.load_image(file_path)
    
    def load_image(self, file_path):
        """이미지 로드"""
        if self.wsi_viewer.load_wsi(file_path):
            self.current_image_path = file_path
            file_name = Path(file_path).name

            # 그리기 모드 종료 (버튼 상태, 커서 복원)
            self.stop_drawing()

            # 이전 결과 모두 초기화
            self.current_detection_result = None
            self.current_segmentation_result = None
            self.current_pdl1_result = None
            self.all_raw_cells = []
            self.current_class_thresholds = {}
            self.is_pdl1_mode = False
            self.wsi_viewer.clear_detection_results()  # Detection overlay 제거
            self.wsi_viewer.clear_segmentation_overlay()  # Segmentation overlay 제거
            self.clear_virtual_stain()                 # Virtual Stain overlay 제거
            self.wsi_viewer.clear_annotations()        # Annotation/Polygon 제거
            self.annotation_panel.clear_annotations()  # Annotation 패널 테이블 초기화
            self.resultList.clear()                    # 결과 리스트 초기화
            self.btnVisualization.setEnabled(False)    # 시각화 버튼 비활성화

            # Initialize progress
            self.progressBar.setValue(0)
            self.progressLabel.setText("AI Progress")

            self.setWindowTitle(f"MeDICus Studio - [{file_name}]")
            self.statusbar.showMessage(f"Image loaded: {file_name}")
        else:
            self.statusbar.showMessage("Image load failed")
            QMessageBox.critical(self, "Error", "Unable to load image.")
    
    def on_field_of_view_changed(self, fov_rect, level):
        """보이는 영역 변경 시 호출"""
        # 필요시 추가 처리
        pass
    
    def show_slide_info(self):
        """슬라이드 정보 표시 (싱글턴 - 기존 창 닫고 열기)"""
        if hasattr(self, '_slide_info_dialog') and self._slide_info_dialog and self._slide_info_dialog.isVisible():
            self._slide_info_dialog.close()
        tile_manager = self.wsi_viewer.get_tile_manager()
        self._slide_info_dialog = show_slide_info_dialog(tile_manager, self)

    def show_detection_visualization(self):
        """HnE 검출 결과 시각화 창 표시 (싱글턴 - 기존 창 닫고 열기)"""
        if not self.all_raw_cells:
            QMessageBox.information(self, "Notice", "No detection results to display.")
            return

        if hasattr(self, '_visualization_dialog') and self._visualization_dialog and self._visualization_dialog.isVisible():
            self._visualization_dialog.close()

        from ui.dialogs.detection_visualization_dialog import show_detection_visualization
        tile_manager = self.wsi_viewer.get_tile_manager()
        slide_dimensions = None
        thumbnail_np = None
        roi_bounds = None

        if tile_manager and tile_manager.slide:
            slide_dimensions = tile_manager.slide.dimensions
            sw, sh = slide_dimensions

            # ROI 폴리곤이 있으면 bounds 계산
            annotations = self.wsi_viewer.annotation_list.annotations if self.wsi_viewer.annotation_list.annotations else []
            if annotations:
                xs = [p[0] for ann in annotations for p in ann.coordinates]
                ys = [p[1] for ann in annotations for p in ann.coordinates]
                roi_bounds = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))

                # 워커가 미리 생성한 썸네일 재사용 (슬라이드 재읽기 없음)
            pa = getattr(self, '_plot_arrays', None)
            if pa and pa.get('thumbnail') is not None:
                thumbnail_np = pa['thumbnail']
                # 워커 썸네일의 roi_bounds도 재사용 (annotations 없는 경우 대비)
                if not roi_bounds and pa.get('thumb_roi_bounds') is not None:
                    roi_bounds = pa['thumb_roi_bounds']
            else:
                try:
                    if roi_bounds:
                        import cv2
                        rx0, ry0, rx1, ry1 = roi_bounds
                        region_w = rx1 - rx0
                        region_h = ry1 - ry0
                        thumb_size = 600
                        scale = min(thumb_size / region_w, thumb_size / region_h)
                        best_level = tile_manager.slide.get_best_level_for_downsample(1.0 / scale)
                        level_ds = tile_manager.slide.level_downsamples[best_level]
                        lw = max(1, round(region_w / level_ds))
                        lh = max(1, round(region_h / level_ds))
                        region_thumb = tile_manager.slide.read_region((rx0, ry0), best_level, (lw, lh))
                        thumb_arr = np.array(region_thumb)[:, :, :3]
                        new_w = max(1, int(region_w * scale))
                        new_h = max(1, int(region_h * scale))
                        thumbnail_np = cv2.resize(thumb_arr, (new_w, new_h))
                    else:
                        thumb = tile_manager.slide.get_thumbnail((600, 600))
                        thumbnail_np = np.array(thumb.convert('RGB'))
                except Exception:
                    thumbnail_np = None

        # Segmentation 확률 맵 전달 (Other 타입이면 None)
        seg_prob_map = None
        seg_class_names = None
        if self.current_tissue_type != "Other" and self.current_segmentation_result:
            seg_metadata = self.current_segmentation_result.get('metadata', {})
            seg_prob_map = seg_metadata.get('prob_map')
            seg_class_names = self.current_segmentation_result.get(
                'class_names', ['Background', 'Stroma', 'Non_Tumor', 'Tumor'])

            # ROI가 있으면 prob_map을 thumbnail과 동일한 영역으로 크롭 (buffer 제거)
            if seg_prob_map is not None and roi_bounds is not None:
                rx0, ry0, rx1, ry1 = roi_bounds
                region_offset = seg_metadata.get('region_offset', (0, 0))
                wsi_mpp = seg_metadata.get('wsi_mpp', 0.25)
                output_mpp_val = seg_metadata.get('output_mpp', 4.0)
                scale = wsi_mpp / output_mpp_val
                px0 = max(0, int((rx0 - region_offset[0]) * scale))
                py0 = max(0, int((ry0 - region_offset[1]) * scale))
                px1 = min(seg_prob_map.shape[2], int((rx1 - region_offset[0]) * scale))
                py1 = min(seg_prob_map.shape[1], int((ry1 - region_offset[1]) * scale))
                if px1 > px0 and py1 > py0:
                    seg_prob_map = seg_prob_map[:, py0:py1, px0:px1]

        # 폴리곤 좌표 추출 (WSI level-0 기준)
        roi_polygon_coords = [list(ann.coordinates) for ann in annotations] if annotations else []

        # 슬라이드 경로
        slide_path = tile_manager.slide_path if tile_manager else None

        self._visualization_dialog = show_detection_visualization(
            self.all_raw_cells, slide_dimensions, thumbnail_np, roi_bounds,
            seg_prob_map, seg_class_names, roi_polygon_coords, slide_path, self,
            plot_arrays=getattr(self, '_plot_arrays', None)
        )
    
    # === AI 기능 ===
    
    def run_segmentation(self):
        """조직 분할 실행"""
        if not self.current_image_path:
            self.statusbar.showMessage("Please load an image first.")
            return
        
        # Initialize AI module (first use)
        if self.tissue_segmentation is None:
            self.statusbar.showMessage("Initializing tissue segmentation module...")
            QApplication.processEvents()
            self.setup_ai_modules()
        
        self.statusbar.showMessage("Running tissue segmentation analysis...")
        
        tile_manager = self.wsi_viewer.get_tile_manager()
        self.tissue_segmentation.run_segmentation(self.current_image_path, tile_manager)
    
    def run_classification(self):
        """암 분류 실행"""
        if not self.current_image_path:
            self.statusbar.showMessage("Please load an image first.")
            return
        
        # Initialize AI module (first use)
        if self.tissue_classification is None:
            self.statusbar.showMessage("Initializing cancer classification module...")
            QApplication.processEvents()
            self.setup_ai_modules()
        
        self.statusbar.showMessage("Running cancer classification analysis...")
        
        tile_manager = self.wsi_viewer.get_tile_manager()
        self.tissue_classification.run_classification(self.current_image_path, tile_manager)
    
    def run_detection(self):
        """병변 검출 실행 또는 중단"""
        # If running, stop
        if self.is_detection_running:
            self.btnHneCellDetection.setText("(Integrated) Cell Detection")
            self.is_detection_running = False
            
            self.detection_service.cancel_detection()
            self.statusbar.showMessage("Detection stopped.")
            return

        if not self.current_image_path:
            self.statusbar.showMessage("Please load an image first.")
            return
        
        # AI 시작: 그리기 모드 해제
        self.wsi_viewer.exit_drawing_mode()

        # 기존 Segmentation 결과 제거
        self.wsi_viewer.clear_segmentation_overlay()
        self.current_segmentation_result = None
        # ResultList 완전 초기화
        self.resultList.clear()

        # Update button state
        self.btnHneCellDetection.setText("⏸ Stop")
        self.is_detection_running = True
        
        # Initialize progress
        self.progressBar.setValue(0)
        self.progressLabel.setText("Initializing...")
        
        # Initialize AI module
        self.statusbar.showMessage("Initializing detection module...")
        QApplication.processEvents()
        self.setup_ai_modules()
        
        # Load model
        if not self.detection_service.is_model_loaded():
            self.statusbar.showMessage("Loading model...")
            QApplication.processEvents()
            
            success, message = self.detection_service.load_model()
            if not success:
                self.statusbar.showMessage("Model load failed")
                QMessageBox.critical(self, "Model Load Error", message)
                self.btnHneCellDetection.setText("(Integrated) Cell Detection")
                self.is_detection_running = False
                return
            
            self.statusbar.showMessage("Model loaded")
        
        self.statusbar.showMessage("Running cell detection analysis...")        
        # ROI 영역 가져오기
        roi_polygons = None
        roi_info = "Entire slide"
        if self.wsi_viewer.annotation_list.annotations:
            roi_polygons = self.wsi_viewer.annotation_list.annotations
            roi_count = len(roi_polygons)
            
            # ROI 타입별 카운트
            type_counts = {}
            for ann in roi_polygons:
                type_name = ann.type.value
                type_counts[type_name] = type_counts.get(type_name, 0) + 1
            
            # Build ROI info string
            type_strs = [f"{count} {type_name}" for type_name, count in type_counts.items()]
            roi_info = f"ROI {roi_count} ({', '.join(type_strs)})"
            
            self.statusbar.showMessage(f"Running cell detection analysis... [{roi_info}]")
            self.progressLabel.setText(f"Detection target: {roi_info}")
        else:
            self.progressLabel.setText("Detection target: Entire slide")
        
        # Open slide (via service)
        try:
            QApplication.processEvents()
            start_time = time.time()
            slide, message = self.detection_service.open_slide(self.current_image_path)
            
            if slide is None:
                self.statusbar.showMessage("Failed to open slide")
                self.btnHneCellDetection.setText("(Integrated) Cell Detection")
                self.is_detection_running = False
                return
            
            load_time = time.time() - start_time
            self.statusbar.showMessage(f"WSI loaded in {load_time:.2f}s")
            QApplication.processEvents()

            # Determine epithelial reclassification based on tissue type
            # Breast, Stomach: reclassification enabled / Other: reclassification disabled
            auto_classify = (self.current_tissue_type in ["Breast", "Stomach"])

            # Start detection (via service)
            self.detection_service.start_detection(slide, roi_polygons,
                                                    auto_classify_epithelial=auto_classify,
                                                    tissue_type=self.current_tissue_type,
                                                    image_path=self.current_image_path)
            
        except Exception as e:
            self.statusbar.showMessage("Detection execution failed")
            self.btnHneCellDetection.setText("(Integrated) Cell Detection")
            self.is_detection_running = False
    
    def run_tumor_segmentation(self):
        """Tumor Segmentation 실행 (백그라운드 스레드)"""
        # 실행 중이면 취소
        if self.is_segmentation_running:
            self.btnTumorSegmentation.setText("Tumor Segmentation")
            self.is_segmentation_running = False
            if self.tumor_seg_worker and self.tumor_seg_worker.isRunning():
                self.tumor_seg_worker.cancel()
            self.statusbar.showMessage("Segmentation stopped.")
            return

        if not self.current_image_path:
            self.statusbar.showMessage("Please load an image first.")
            return

        if self.current_tissue_type == "Other":
            QMessageBox.warning(self, "Warning", "Tumor segmentation cannot be performed in Other type.\nPlease select Breast or Stomach.")
            return

        # AI 시작: 그리기 모드 해제
        self.wsi_viewer.exit_drawing_mode()

        # 기존 Detection 결과 제거
        self.current_detection_result = None
        self.wsi_viewer.clear_detection_overlay()
        self.resultList.clear()

        # 버튼 상태 변경
        self.btnTumorSegmentation.setText("⏸ Stop")
        self.is_segmentation_running = True

        # Progress 초기화
        self.progressBar.setValue(0)
        self.progressLabel.setText("Initializing Tumor Segmentation...")

        # ROI polygon 좌표 수집
        roi_polygons = []
        roi_bounds = None
        if self.wsi_viewer.annotation_list.annotations:
            min_x = float('inf')
            min_y = float('inf')
            max_x = float('-inf')
            max_y = float('-inf')

            for polygon in self.wsi_viewer.annotation_list.annotations:
                coords = polygon.coordinates
                roi_polygons.append(coords)
                xs = [p[0] for p in coords]
                ys = [p[1] for p in coords]
                min_x = min(min_x, min(xs))
                min_y = min(min_y, min(ys))
                max_x = max(max_x, max(xs))
                max_y = max(max_y, max(ys))

            roi_bounds = (int(min_x), int(min_y), int(max_x), int(max_y))

        # 워커 생성 및 시그널 연결
        from ai.epithelial_classifier import TumorSegmentationWorker
        self.tumor_seg_worker = TumorSegmentationWorker(
            image_path=self.current_image_path,
            tissue_type=self.current_tissue_type,
            roi_bounds=roi_bounds,
            roi_polygons=roi_polygons if roi_polygons else None,
        )
        self.tumor_seg_worker.finished.connect(self.on_tumor_segmentation_complete)
        self.tumor_seg_worker.progress.connect(self.on_ai_progress)
        self.tumor_seg_worker.status.connect(self.on_detection_status)
        self.tumor_seg_worker.error.connect(self.on_tumor_segmentation_error)
        self.tumor_seg_worker.start()

        self.statusbar.showMessage("Running Tumor Segmentation...")

    def on_tumor_segmentation_complete(self, result):
        """Tumor Segmentation 완료 (백그라운드 스레드에서 시그널로 수신)"""
        self.is_segmentation_running = False
        self.btnTumorSegmentation.setText("Tumor Segmentation")

        # 결과 저장
        self.current_segmentation_result = result

        # 오버레이 표시
        self.wsi_viewer.set_segmentation_overlay(
            result['mask'], result['metadata'], result['class_names'],
            result['roi_bounds'], result['roi_polygons']
        )

        # 결과 리스트 업데이트
        self.update_segmentation_result_list()

        self.progressBar.setValue(100)
        self.progressLabel.setText("Segmentation complete")
        self.statusbar.showMessage("Tumor Segmentation complete")

        # AI 완료: annotation 제거
        self.wsi_viewer.clear_annotations()
        self.annotation_panel.clear_annotations()

        # 자동저장
        if self.chkAutoSave.isChecked():
            self._auto_save_segmentation_result()

    def on_tumor_segmentation_error(self, error_msg):
        """Tumor Segmentation 에러"""
        self.is_segmentation_running = False
        self.btnTumorSegmentation.setText("Tumor Segmentation")
        self.progressLabel.setText("Segmentation failed")
        self.statusbar.showMessage("Segmentation failed")
        print(error_msg)
        QMessageBox.critical(self, "Error", f"Segmentation failed:\n{error_msg.split(chr(10))[0]}")

    def run_pdl1_detection(self):
        """PD-L1 Detection 실행 또는 중단"""
        if self.is_pdl1_running:
            self.btnPDL1Detection.setText("PD-L1 Detection")
            self.is_pdl1_running = False
            if self.pdl1_detection:
                self.pdl1_detection.cancel()
            self.statusbar.showMessage("PD-L1 detection stopped.")
            return

        if not self.current_image_path:
            self.statusbar.showMessage("Please load an image first.")
            return

        # AI 시작: 그리기 모드 해제
        self.wsi_viewer.exit_drawing_mode()

        # 기존 결과 제거
        self.wsi_viewer.clear_segmentation_overlay()
        self.current_segmentation_result = None
        self.current_detection_result = None
        self.wsi_viewer.clear_detection_results()
        self.resultList.clear()

        # 버튼 상태 변경
        self.btnPDL1Detection.setText("⏸ Stop")
        self.is_pdl1_running = True

        self.progressBar.setValue(0)
        self.progressLabel.setText("Initializing PD-L1...")
        QApplication.processEvents()

        # Initialize PD-L1 module
        if self.pdl1_detection is None:
            from ai.pdl1_detection import PDL1Detection
            self.pdl1_detection = PDL1Detection()
            self.pdl1_detection.detectionComplete.connect(self.on_pdl1_detection_complete)
            self.pdl1_detection.detectionProgress.connect(self.on_ai_progress)
            self.pdl1_detection.detectionStatus.connect(self.on_detection_status)
            self.pdl1_detection.detectionError.connect(self.on_ai_error)

        # 모델 로드
        if not self.pdl1_detection.is_model_loaded():
            self.statusbar.showMessage("Loading PD-L1 model...")
            QApplication.processEvents()
            if not self.pdl1_detection.load_model():
                self.statusbar.showMessage("PD-L1 model load failed")
                QMessageBox.critical(self, "Error", "PD-L1 model load failed")
                self.btnPDL1Detection.setText("PD-L1 Detection")
                self.is_pdl1_running = False
                return

        self.statusbar.showMessage("Running PD-L1 detection...")

        # ROI 가져오기
        roi_polygons = None
        if self.wsi_viewer.annotation_list.annotations:
            roi_polygons = self.wsi_viewer.annotation_list.annotations

        try:
            import openslide
            slide = openslide.OpenSlide(self.current_image_path)
            self.pdl1_detection.run_detection(slide, roi_polygons)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"PD-L1 detection failed:\n{str(e)}")
            self.btnPDL1Detection.setText("PD-L1 Detection")
            self.is_pdl1_running = False

    def on_pdl1_detection_complete(self, result):
        """PD-L1 검출 완료"""
        self.is_pdl1_running = False
        self.btnPDL1Detection.setText("PD-L1 Detection")

        num_cells = result.get('num_cells', 0)
        tps = result.get('tps', 0.0)
        class_counts = result.get('class_counts', {})

        # 결과 캐시
        self.current_pdl1_result = result
        self.current_detection_result = result

        # Raw cells 저장 (슬라이더용)
        from ai.pdl1_detection import PDL1_CLASS_NAMES, PDL1_CLASS_COLORS_RGB
        cells = result.get('cells', [])
        self.all_raw_cells = cells
        self.current_class_thresholds = {c['cls_id']: 1 for c in cells}
        self.current_color_map = PDL1_CLASS_COLORS_RGB
        self.is_pdl1_mode = True

        self.progressBar.setValue(100)
        self.progressLabel.setText("PD-L1 detection complete")

        # Overlay display
        if cells:
            self.wsi_viewer.set_detection_results(cells, color_map=PDL1_CLASS_COLORS_RGB)

        # 결과 리스트 업데이트 (슬라이더 포함)
        self._update_result_list_with_sliders(
            class_names=PDL1_CLASS_NAMES,
            class_colors=PDL1_CLASS_COLORS_RGB,
            is_pdl1=True
        )

        # GPU 해제
        self.pdl1_detection.unload_model()

        # 자동저장
        if self.chkAutoSave.isChecked():
            self._auto_save_pdl1_result()

        # AI 완료: annotation 제거
        self.wsi_viewer.clear_annotations()
        self.annotation_panel.clear_annotations()

        tps_category = self._get_tps_category(tps)
        self.statusbar.showMessage(f"PD-L1 detection complete - TPS: {tps:.1f}% ({tps_category})")

    def _get_tps_category(self, tps):
        """TPS 값에 따른 판정 카테고리"""
        if tps < 1:
            return "Negative (<1%)"
        elif tps < 50:
            return "Low positive (1-49%)"
        else:
            return "High positive (≥50%)"

    def _auto_save_pdl1_result(self):
        """PD-L1 결과를 WSI 파일 위치에 자동 저장"""
        if not self.current_pdl1_result or not self.current_image_path:
            return
        try:
            wsi_dir = Path(self.current_image_path).parent
            wsi_stem = Path(self.current_image_path).stem
            save_path = wsi_dir / f"{wsi_stem}_pdl1_result.json"

            result_with_meta = {
                "metadata": {
                    "model_type": "pdl1_detection",
                    "model_name": "PD-L1 Detection",
                    "version": "1.0",
                    "timestamp": datetime.now().isoformat(),
                    "image_path": str(self.current_image_path),
                    "image_name": Path(self.current_image_path).name
                },
                "result": self.current_pdl1_result
            }

            with open(str(save_path), 'w', encoding='utf-8') as f:
                json.dump(result_with_meta, f, indent=2, ensure_ascii=False)

            self.statusbar.showMessage(f"Auto-saved: {save_path.name}")
            print(f"PD-L1 auto-save complete: {save_path}")
        except Exception as e:
            print(f"PD-L1 auto-save failed: {e}")

    # ── Virtual Stain (IHC → H&E) ──

    def run_virtual_stain_ihc_membrane(self):
        """IHC → H&E (Membrane) virtual staining"""
        if self.is_virtual_stain_running:
            # Cancel
            self.btnIHCtoHnEMembrane.setText("IHC → H&&E (Membrane)")
            self.is_virtual_stain_running = False
            if self.virtual_stain_worker:
                self.virtual_stain_worker.cancel()
            self.statusbar.showMessage("Virtual staining stopped.")
            return

        if not self.current_image_path:
            self.statusbar.showMessage("Please load an image first.")
            return

        # Model path
        model_path = os.path.join(str(project_root), "model", "IHC_HnE_virtual_stain_membrane.pth")
        if not os.path.exists(model_path):
            QMessageBox.critical(self, "Error",
                                 f"Virtual stain model not found:\n{model_path}")
            return

        # AI 시작: 그리기 모드 해제
        self.wsi_viewer.exit_drawing_mode()

        # ROI bounds & polygons
        roi_bounds = None
        roi_polygons = None
        if self.wsi_viewer.annotation_list.annotations:
            all_coords = []
            roi_polygons = []
            for ann in self.wsi_viewer.annotation_list.annotations:
                if ann.coordinates:
                    all_coords.extend(ann.coordinates)
                    roi_polygons.append(ann.coordinates)
            if all_coords:
                xs = [c[0] for c in all_coords]
                ys = [c[1] for c in all_coords]
                # 이미지 범위로 클램핑 (레터박스 영역 제외)
                tile_mgr = self.wsi_viewer.get_tile_manager()
                if tile_mgr:
                    img_w, img_h = tile_mgr.get_level_dimensions(0)
                    roi_bounds = (
                        max(0, int(min(xs))),
                        max(0, int(min(ys))),
                        min(img_w, int(max(xs))),
                        min(img_h, int(max(ys))),
                    )
                else:
                    roi_bounds = (int(min(xs)), int(min(ys)),
                                  int(max(xs)), int(max(ys)))

        # Button state
        self.btnIHCtoHnEMembrane.setText("⏸ Stop")
        self.is_virtual_stain_running = True
        self.progressBar.setValue(0)
        self.progressLabel.setText("Initializing Virtual Stain...")

        from ai.virtual_stain import VirtualStainWorker
        self.virtual_stain_worker = VirtualStainWorker(
            image_path=self.current_image_path,
            model_path=model_path,
            stain_type="ihc_membrane",
            target_mpp=2.0,
            patch_size=512,
            roi_bounds=roi_bounds,
            roi_polygons=roi_polygons,
        )
        self.virtual_stain_worker.finished.connect(self.on_virtual_stain_complete)
        self.virtual_stain_worker.progress.connect(self.on_ai_progress)
        self.virtual_stain_worker.status.connect(self.on_detection_status)
        self.virtual_stain_worker.error.connect(self.on_virtual_stain_error)
        self.virtual_stain_worker.start()

        self.statusbar.showMessage("Running IHC → H&E (Membrane) virtual staining...")

    def on_virtual_stain_complete(self, result):
        """Virtual staining 완료 → WSI 뷰어에 오버레이로 표시"""
        self.is_virtual_stain_running = False
        self.btnIHCtoHnEMembrane.setText("IHC → H&&E (Membrane)")

        tissue_count = result.get('tissue_count', 0)
        total = result.get('total_patches', 0)

        self.progressBar.setValue(100)
        self.progressLabel.setText("Virtual staining complete")

        # WSI 뷰어에 오버레이 표시 (줌/패닝 동기화)
        self.wsi_viewer.set_virtual_stain_overlay(
            canvas=result['canvas'],
            metadata={
                'roi_origin': result['roi_origin'],
                'target_mpp': result['target_mpp'],
                'canvas_l0_w': result['canvas_l0_w'],
                'canvas_l0_h': result['canvas_l0_h'],
            }
        )

        # 체크박스 활성화 + 체크
        self.chkShowVirtualStain.setEnabled(True)
        self.chkShowVirtualStain.blockSignals(True)
        self.chkShowVirtualStain.setChecked(True)
        self.chkShowVirtualStain.blockSignals(False)

        # AI 완료: annotation 제거
        self.wsi_viewer.clear_annotations()
        self.annotation_panel.clear_annotations()

        self.statusbar.showMessage(
            f"Virtual staining complete — {tissue_count}/{total} tissue patches"
        )

    def on_virtual_stain_error(self, error_msg):
        """Virtual staining 에러"""
        self.is_virtual_stain_running = False
        self.btnIHCtoHnEMembrane.setText("IHC → H&&E (Membrane)")
        self.progressLabel.setText("Virtual staining failed")
        self.statusbar.showMessage("Virtual staining failed")
        print(error_msg)
        QMessageBox.critical(self, "Error",
                             f"Virtual staining failed:\n{error_msg.split(chr(10))[0]}")

    def toggle_virtual_stain(self, checked):
        """Virtual stain 오버레이 표시/숨김 (체크박스 토글)"""
        if self.wsi_viewer.virtual_stain_canvas is None:
            return
        self.wsi_viewer.set_virtual_stain_visible(checked)
        self.statusbar.showMessage(
            f"Virtual stain overlay: {'Visible' if checked else 'Hidden'}"
        )

    def clear_virtual_stain(self):
        """Virtual stain 오버레이 제거"""
        self.wsi_viewer.clear_virtual_stain_overlay()
        self.chkShowVirtualStain.blockSignals(True)
        self.chkShowVirtualStain.setEnabled(False)
        self.chkShowVirtualStain.setChecked(False)
        self.chkShowVirtualStain.blockSignals(False)

    def update_segmentation_result_list(self):
        """Segmentation 결과를 리스트에 표시"""
        if not self.current_segmentation_result:
            return

        mask = self.current_segmentation_result['mask']
        class_names_raw = self.current_segmentation_result['class_names']
        metadata = self.current_segmentation_result['metadata']
        roi_bounds = self.current_segmentation_result.get('roi_bounds')
        
        # class_names가 리스트인 경우 딕셔너리로 변환
        if isinstance(class_names_raw, list):
            class_names = {i: name for i, name in enumerate(class_names_raw)}
        else:
            class_names = class_names_raw
        
        # Segmentation 클래스별 색상 (DeepLabV3Plus 기본 색상)
        seg_colors_rgb = {
            0: (0, 0, 0),          # Background - 검정
            1: (255, 0, 0),        # Stroma - 빨강
            2: (0, 255, 0),        # Non_Tumor - 초록
            3: (0, 0, 255)         # Tumor - 파랑
        }
        
        # 기존 결과 리스트 클리어 (Detection 결과 유지하려면 조건 추가)
        self.resultList.blockSignals(True)
        
        # Segmentation 섹션 추가
        header_text = "=== Tumor Segmentation ==="
        if roi_bounds:
            header_text += " (ROI Only)"
        header_item = QListWidgetItem(header_text)
        header_item.setFlags(Qt.ItemIsEnabled)
        font = header_item.font()
        font.setBold(True)
        header_item.setFont(font)
        self.resultList.addItem(header_item)
        
        # ROI 영역 내의 픽셀만 카운트
        if roi_bounds:
            # ROI 영역 계산
            roi_x_min, roi_y_min, roi_x_max, roi_y_max = roi_bounds
            region_offset = metadata.get('region_offset', (0, 0))
            offset_x, offset_y = region_offset
            
            wsi_mpp = metadata.get('wsi_mpp', 0.25)
            output_mpp = metadata.get('output_mpp', 4.0)
            scale_factor = wsi_mpp / output_mpp
            
            mask_h, mask_w = mask.shape
            
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
            
            # ROI 영역만 추출
            roi_mask = mask[roi_mask_y_min:roi_mask_y_max, roi_mask_x_min:roi_mask_x_max]
            
            if roi_mask.size == 0:
                self.resultList.blockSignals(False)
                return
            
            unique, counts = np.unique(roi_mask, return_counts=True)
            pixel_counts = dict(zip(unique, counts))
            total_pixels = roi_mask.size
        else:
            # 전체 mask 사용
            unique, counts = np.unique(mask, return_counts=True)
            pixel_counts = dict(zip(unique, counts))
            total_pixels = mask.size
        
        # MPP 정보로 실제 면적 계산
        output_mpp = metadata.get('output_mpp', 4.0)
        pixel_area_um2 = (output_mpp ** 2)  # 1 픽셀 = output_mpp^2 um^2
        pixel_area_mm2 = pixel_area_um2 / 1e6  # um^2 -> mm^2
        
        # Background(class 0)를 제외한 조직 영역 픽셀 수 계산
        tissue_pixels = sum(count for cls_id, count in pixel_counts.items() if cls_id != 0)
        
        for cls_id, cls_name in class_names.items():
            # Background는 표시하지 않음
            if cls_id == 0:
                continue
            
            count = pixel_counts.get(cls_id, 0)
            if count > 0:
                # 조직 영역(Background 제외) 대비 퍼센트
                if tissue_pixels > 0:
                    percentage = (count / tissue_pixels) * 100
                else:
                    percentage = 0.0
                
                area_mm2 = count * pixel_area_mm2
                
                color_rgb = seg_colors_rgb.get(cls_id, (255, 255, 255))
                
                # 컬러 아이콘 생성
                pix = QPixmap(16, 16)
                pix.fill(QColor(*color_rgb))
                icon = QIcon(pix)
                
                item = QListWidgetItem(icon, f"{cls_name}: {percentage:.1f}% ({area_mm2:.2f} mm²)")
                item.setData(Qt.UserRole, ('segmentation', cls_id))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                item.setCheckState(Qt.Checked)
                item.setToolTip(f"Show/hide {cls_name} region")
                self.resultList.addItem(item)
        
        self.resultList.blockSignals(False)
    
    def on_segmentation_complete(self, result):
        """조직 분할 완료"""
        self.statusbar.showMessage(f"Tissue segmentation complete - {result.get('message', '')}")
    
    def on_classification_complete(self, result):
        """암 분류 완료"""
        classification = result.get('classification', '')
        self.statusbar.showMessage(f"Cancer classification complete - {classification}")
    
    def on_detection_complete(self, result):
        """병변 검출 완료"""
        num_cells = result.get('num_cells', 0)
        class_counts = result.get('class_counts', {})

        # 결과 캐시 저장
        self.current_detection_result = result

        # Segmentation이 함께 실행된 경우 (Breast/Stomach) 결과 저장
        if result.get('seg_mask') is not None:
            seg_metadata = result.get('seg_metadata', {})
            self.current_segmentation_result = {
                'mask': result['seg_mask'],
                'metadata': seg_metadata,
                'class_names': result.get('seg_class_names', ['Background', 'Stroma', 'Non_Tumor', 'Tumor']),
            }

        # Raw cells 저장 (슬라이더용)
        cells = result.get('cells', [])
        self.all_raw_cells = cells
        self.current_class_thresholds = {c['cls_id']: 1 for c in cells}
        self.current_color_map = None
        self.is_pdl1_mode = False
        # 시각화 다이얼로그용 사전 계산 배열 저장
        self._plot_arrays = result.get('plot_arrays', None)

        # Initialize progress
        self.progressBar.setValue(100)
        self.progressLabel.setText("Detection complete")

        # Update status bar
        self.statusbar.showMessage(f"Cell detection complete - {num_cells:,} cells detected (GPU released)")

        # 결과 리스트 업데이트 (슬라이더 포함)
        self.update_result_list(class_counts, num_cells)

        # 검출 결과를 오버레이로 표시
        if cells:
            self.wsi_viewer.set_detection_results(cells)
        
        # GPU 리소스 해제
        self.detection_service.unload_model()
        
        # 자동저장
        if self.chkAutoSave.isChecked():
            self._auto_save_detection_result()

        # AI 완료: annotation 제거
        self.wsi_viewer.clear_annotations()
        self.annotation_panel.clear_annotations()

        # 버튼 상태 복원
        self.btnHneCellDetection.setText("(Integrated) Cell Detection")
        self.btnVisualization.setEnabled(True)
        self.is_detection_running = False

        # 자동 시각화
        if self.chkAutoVisualize.isChecked():
            self.show_detection_visualization()
    
    def update_result_list(self, class_counts, total_cells):
        """검출 결과를 리스트에 표시 (클래스별 confidence 슬라이더 포함)"""
        from ai.detection import CLASS_NAMES, CLASS_COLORS_RGB
        self._update_result_list_with_sliders(
            class_names=CLASS_NAMES,
            class_colors=CLASS_COLORS_RGB,
            is_pdl1=False
        )

    def _update_result_list_with_sliders(self, class_names, class_colors, is_pdl1=False):
        """클래스별 confidence 슬라이더를 포함한 결과 리스트 생성"""
        self.resultList.blockSignals(True)
        self.resultList.clear()

        # 현재 threshold로 필터링된 셀 계산
        filtered_cells = self._get_filtered_cells()
        total_filtered = len(filtered_cells)

        # 클래스별 카운트
        class_cell_counts = {}
        for cell in filtered_cells:
            cls_id = cell['cls_id']
            class_cell_counts[cls_id] = class_cell_counts.get(cls_id, 0) + 1

        # PD-L1이면 TPS 헤더
        if is_pdl1:
            positive = sum(1 for c in filtered_cells if c['cls_id'] == 1)
            negative = sum(1 for c in filtered_cells if c['cls_id'] == 0)
            total_tumor = positive + negative
            tps = (positive / total_tumor * 100) if total_tumor > 0 else 0.0
            tps_item = QListWidgetItem(f"TPS: {tps:.1f}% ({self._get_tps_category(tps)})")
            tps_item.setData(Qt.UserRole, None)
            font = tps_item.font()
            font.setBold(True)
            tps_item.setFont(font)
            self.resultList.addItem(tps_item)

        # 전체 행
        total_item = QListWidgetItem(f"Total: {total_filtered:,}")
        total_item.setData(Qt.UserRole, None)
        total_item.setFlags(total_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        total_item.setCheckState(Qt.Checked)
        font = total_item.font()
        font.setBold(True)
        total_item.setFont(font)
        total_item.setToolTip("Show/hide all classes")
        self.resultList.addItem(total_item)

        # 클래스별 행 + 미니 슬라이더
        # raw cells에서 존재하는 클래스만 표시
        raw_class_ids = set(c['cls_id'] for c in self.all_raw_cells)

        for cls_id, cls_name in class_names.items():
            if cls_id not in raw_class_ids:
                continue

            count = class_cell_counts.get(cls_id, 0)
            color_rgb = class_colors.get(cls_id, (255, 255, 255))

            # 빈 아이템 (커스텀 위젯용)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, cls_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Checked)
            item.setSizeHint(QListWidgetItem().sizeHint())

            # 커스텀 위젯: [색상] [이름: 개수] [슬라이더] [값]
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(4, 1, 4, 1)
            layout.setSpacing(4)

            # 색상 아이콘
            color_label = QLabel()
            pix = QPixmap(12, 12)
            pix.fill(QColor(*color_rgb))
            color_label.setPixmap(pix)
            color_label.setFixedWidth(14)
            layout.addWidget(color_label)

            # 클래스명 + 카운트
            count_label = QLabel(f"{cls_name}: {count:,}")
            count_label.setMinimumWidth(80)
            count_label.setObjectName(f"countLabel_{cls_id}")
            layout.addWidget(count_label)

            # 미니 슬라이더
            slider = QSlider(Qt.Horizontal)
            slider.setMinimum(1)
            slider.setMaximum(100)
            current_threshold = self.current_class_thresholds.get(cls_id, 1)
            slider.setValue(current_threshold)
            slider.setFixedHeight(16)
            slider.setToolTip(f"{cls_name} confidence threshold")
            layout.addWidget(slider)

            # 값 표시
            val_label = QLabel(f"{current_threshold / 100:.2f}")
            val_label.setFixedWidth(30)
            val_label.setObjectName(f"valLabel_{cls_id}")
            layout.addWidget(val_label)

            self.resultList.addItem(item)
            item.setSizeHint(widget.sizeHint())
            self.resultList.setItemWidget(item, widget)

            # 슬라이더 시그널 연결
            slider.valueChanged.connect(partial(self._on_class_confidence_changed, cls_id))

        self.resultList.blockSignals(False)

    def _get_filtered_cells(self):
        """현재 class threshold 설정에 따라 필터링된 셀 반환"""
        if not self.all_raw_cells:
            return []
        filtered = []
        for cell in self.all_raw_cells:
            threshold = self.current_class_thresholds.get(cell['cls_id'], 1) / 100.0
            if cell['confidence'] >= threshold:
                filtered.append(cell)
        return filtered

    def _on_class_confidence_changed(self, cls_id, value):
        """클래스별 confidence threshold 슬라이더 변경 — 라벨만 즉시 갱신, overlay는 debounce"""
        self.current_class_thresholds[cls_id] = value

        # 라벨만 즉시 업데이트 (빠름)
        for i in range(self.resultList.count()):
            item = self.resultList.item(i)
            widget = self.resultList.itemWidget(item)
            if widget is None:
                continue
            val_label = widget.findChild(QLabel, f"valLabel_{cls_id}")
            if val_label:
                val_label.setText(f"{value / 100:.2f}")

        # 무거운 작업(필터링 + overlay 재구축)은 debounce
        self._conf_debounce_timer.start()

    def _apply_confidence_filter(self):
        """debounce 후 실제 필터링 및 overlay 갱신"""
        filtered_cells = self._get_filtered_cells()

        # 클래스별 카운트 라벨 업데이트
        for i in range(self.resultList.count()):
            item = self.resultList.item(i)
            widget = self.resultList.itemWidget(item)
            if widget is None:
                continue
            for cls_id in self.current_class_thresholds:
                count_label = widget.findChild(QLabel, f"countLabel_{cls_id}")
                if count_label:
                    cls_count = sum(1 for c in filtered_cells if c['cls_id'] == cls_id)
                    cls_name = count_label.text().split(":")[0]
                    count_label.setText(f"{cls_name}: {cls_count:,}")

        # 전체 카운트 / TPS 업데이트 — item.setText가 itemChanged를 발화하므로 시그널 차단
        self.resultList.blockSignals(True)
        for i in range(self.resultList.count()):
            item = self.resultList.item(i)
            if item.data(Qt.UserRole) is None and "Total:" in item.text():
                item.setText(f"Total: {len(filtered_cells):,}")
                break

        if self.is_pdl1_mode:
            positive = sum(1 for c in filtered_cells if c['cls_id'] == 1)
            negative = sum(1 for c in filtered_cells if c['cls_id'] == 0)
            total_tumor = positive + negative
            tps = (positive / total_tumor * 100) if total_tumor > 0 else 0.0
            for i in range(self.resultList.count()):
                item = self.resultList.item(i)
                if item.data(Qt.UserRole) is None and "TPS:" in item.text():
                    item.setText(f"TPS: {tps:.1f}% ({self._get_tps_category(tps)})")
                    break
            self.statusbar.showMessage(f"TPS: {tps:.1f}% ({self._get_tps_category(tps)}) | {len(filtered_cells)} cells")
        self.resultList.blockSignals(False)

        # 오버레이 갱신 (set_cells 내부에서 visibility 보존됨)
        if filtered_cells:
            self.wsi_viewer.set_detection_results(filtered_cells, color_map=self.current_color_map)
        else:
            self.wsi_viewer.clear_detection_overlay()
    
    def on_result_list_item_clicked(self, item):
        """리스트 클릭 시 체크박스 토글(버튼/마우스 클릭 친화적)"""
        # 클릭 시 체크 상태를 반전시켜 itemChanged에서 처리하도록 함
        if item.flags() & Qt.ItemIsUserCheckable:
            if item.checkState() == Qt.Checked:
                item.setCheckState(Qt.Unchecked)
            else:
                item.setCheckState(Qt.Checked)

    def on_result_list_item_changed(self, item):
        """체크박스 상태 변경 처리: 전체/개별 클래스 표시 토글"""
        user_data = item.data(Qt.UserRole)
        visible = item.checkState() == Qt.Checked

        # Segmentation 결과인지 확인
        if isinstance(user_data, tuple) and user_data[0] == 'segmentation':
            cls_id = user_data[1]
            self.wsi_viewer.set_segmentation_class_visibility(cls_id, visible)
            
            # class_names가 리스트인 경우 처리
            class_names_raw = self.current_segmentation_result['class_names']
            if isinstance(class_names_raw, list):
                cls_name = class_names_raw[cls_id] if cls_id < len(class_names_raw) else "Unknown"
            else:
                cls_name = class_names_raw.get(cls_id, "Unknown")
            
            self.statusbar.showMessage(f"Segmentation {cls_name}: {'Visible' if visible else 'Hidden'}")
            return
        
        # Detection 결과
        cls_id = user_data

        # 오버레이 확인
        if not self.wsi_viewer.detection_overlay:
            return

        # 전체 아이템 토글 시 모든 클래스에 반영
        if cls_id is None:
            self.resultList.blockSignals(True)
            for i in range(1, self.resultList.count()):
                class_item = self.resultList.item(i)
                class_user_data = class_item.data(Qt.UserRole)
                # Segmentation 결과는 건너뜀
                if isinstance(class_user_data, tuple):
                    continue
                class_item.setCheckState(Qt.Checked if visible else Qt.Unchecked)
                class_id = class_user_data
                self.wsi_viewer.detection_overlay.set_class_visibility(class_id, visible)
            self.resultList.blockSignals(False)
            self.wsi_viewer.schedule_overlay_update()
            self.statusbar.showMessage("All classes visible" if visible else "All classes hidden")
            return

        # 개별 클래스
        self.wsi_viewer.detection_overlay.set_class_visibility(cls_id, visible)
        self.wsi_viewer.schedule_overlay_update()
        from ai.detection import CLASS_NAMES
        cls_name = CLASS_NAMES.get(cls_id, "Unknown")
        self.statusbar.showMessage(f"{cls_name}: {'Visible' if visible else 'Hidden'}")
    
    def on_ai_progress(self, progress):
        """AI 작업 진행률 업데이트"""
        self.progressBar.setValue(progress)
    
    def on_detection_status(self, status):
        """검출 상태 메시지 업데이트"""
        self.progressLabel.setText(status)
        self.statusbar.showMessage(status)
    
    def on_ai_error(self, error_msg):
        """AI 작업 에러 처리"""
        self.statusbar.showMessage("Error during analysis")
        
        # 검출 버튼 상태 복원
        if hasattr(self, 'is_detection_running') and self.is_detection_running:
            self.btnHneCellDetection.setText("(Integrated) Cell Detection")
            self.is_detection_running = False

        QMessageBox.critical(self, "Error", error_msg)
    
    def save_results(self):
        """분석 결과 저장 (레거시 메뉴 액션용)"""
        self.save_detection_results()
    
    def clear_results(self):
        """검출/세그멘테이션 결과 지우기"""
        if not self.current_detection_result and not self.current_segmentation_result:
            self.statusbar.showMessage("No results to clear")
            return

        reply = QMessageBox.question(
            self,
            "Clear Results",
            "Do you want to clear the AI analysis results?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # Detection 결과 초기화
            self.current_detection_result = None
            self.wsi_viewer.clear_detection_results()

            # Segmentation 결과 초기화
            self.current_segmentation_result = None
            self.wsi_viewer.clear_segmentation_overlay()

            # PD-L1 / 슬라이더 관련 초기화
            self.current_pdl1_result = None
            self.all_raw_cells = []
            self.current_class_thresholds = {}
            self.is_pdl1_mode = False

            # Virtual Stain 초기화
            self.clear_virtual_stain()

            # 결과 리스트 초기화
            self.resultList.clear()

            # Progress 초기화
            self.progressBar.setValue(0)
            self.progressLabel.setText("AI Progress")

            self.statusbar.showMessage("Analysis results cleared")
    
    def _auto_save_detection_result(self):
        """Detection 결과를 WSI 파일 위치에 자동 저장"""
        if not self.current_detection_result or not self.current_image_path:
            return
        try:
            wsi_dir = Path(self.current_image_path).parent
            wsi_stem = Path(self.current_image_path).stem
            save_path = wsi_dir / f"{wsi_stem}_detection_result.json"

            _NON_SERIAL = ('seg_mask', 'seg_metadata', 'seg_class_names', 'plot_arrays')
            result_to_save = {k: v for k, v in self.current_detection_result.items()
                              if k not in _NON_SERIAL}
            result_with_meta = {
                "metadata": {
                    "model_type": "detection",
                    "model_name": "HnE Cell Detection",
                    "version": "1.0",
                    "timestamp": datetime.now().isoformat(),
                    "image_path": str(self.current_image_path),
                    "image_name": Path(self.current_image_path).name
                },
                "result": result_to_save
            }

            with open(str(save_path), 'w', encoding='utf-8') as f:
                json.dump(result_with_meta, f, indent=2, ensure_ascii=False)

            self.statusbar.showMessage(f"Auto-saved: {save_path.name}")
            print(f"Auto-save complete: {save_path}")
        except Exception as e:
            print(f"Auto-save failed: {e}")
            self.statusbar.showMessage(f"Auto-save failed: {e}")

    def _auto_save_segmentation_result(self):
        """Segmentation 결과를 WSI 파일 위치에 자동 저장"""
        if not self.current_segmentation_result or not self.current_image_path:
            return
        try:
            wsi_dir = Path(self.current_image_path).parent
            wsi_stem = Path(self.current_image_path).stem
            save_path = wsi_dir / f"{wsi_stem}_segmentation_result.json"

            seg_result = self.current_segmentation_result
            mask = seg_result['mask']
            metadata = seg_result['metadata']
            class_names_raw = seg_result['class_names']

            if isinstance(class_names_raw, dict):
                class_names_list = [class_names_raw.get(i, f"Class_{i}") for i in range(max(class_names_raw.keys()) + 1)]
            else:
                class_names_list = list(class_names_raw)

            class_polygons = mask_to_polygons(
                mask, metadata, class_names_list,
                simplify_epsilon=2.0, min_area=10
            )

            result_with_meta = {
                "metadata": {
                    "model_type": "segmentation",
                    "model_name": "HnE_Segmentation",
                    "version": "1.0",
                    "timestamp": datetime.now().isoformat(),
                    "image_path": str(self.current_image_path),
                    "image_name": Path(self.current_image_path).name,
                    "tissue_type": self.current_tissue_type
                },
                "result": {
                    "segmentation_metadata": {
                        "wsi_dimensions": list(metadata.get('wsi_dimensions', [0, 0])),
                        "wsi_mpp": metadata.get('wsi_mpp', 0.25),
                        "model_mpp": metadata.get('model_mpp', 1.0),
                        "output_mpp": metadata.get('output_mpp', 4.0),
                        "mask_shape": list(metadata.get('mask_shape', mask.shape)),
                        "class_names": class_names_list,
                        "region_offset": list(metadata.get('region_offset', (0, 0)))
                    },
                    "roi_bounds": list(seg_result['roi_bounds']) if seg_result.get('roi_bounds') else None,
                    "roi_polygons": seg_result.get('roi_polygons'),
                    "class_polygons": class_polygons,
                    "polygon_coordinate_system": "wsi_level0",
                    "simplification_epsilon": 2.0
                }
            }

            with open(str(save_path), 'w', encoding='utf-8') as f:
                json.dump(result_with_meta, f, indent=2, ensure_ascii=False)

            self.statusbar.showMessage(f"Auto-saved: {save_path.name}")
            print(f"Auto-save complete: {save_path}")
        except Exception as e:
            print(f"Segmentation auto-save failed: {e}")
            self.statusbar.showMessage(f"Auto-save failed: {e}")

    def save_detection_results(self):
        """AI 결과를 JSON 파일로 저장 (Detection 또는 Segmentation)"""
        # Detection 결과 없이 Segmentation만 있으면 Segmentation 저장으로 분기
        # (Detection 결과가 있으면 Detection 우선 저장 — 내부 Segmentation은 시각화 전용)
        if self.current_segmentation_result is not None and self.current_detection_result is None:
            self.save_segmentation_results()
            return

        if not self.current_detection_result:
            QMessageBox.information(self, "Notice", "No results to save.")
            return

        # 기본 파일명 생성 (WSI 파일명에서 확장자 제거)
        default_filename = ""
        if self.current_image_path:
            wsi_filename = Path(self.current_image_path).stem  # 확장자 제외한 파일명
            default_filename = f"{wsi_filename}_detection_result.json"
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Detection Results",
            default_filename,
            "JSON Files (*.json);;Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                # 파일 확장자 확인
                if file_path.endswith('.json'):
                    # numpy 배열은 JSON 직렬화 불가 → 시각화 전용 필드 제외
                    _NON_SERIAL = ('seg_mask', 'seg_metadata', 'seg_class_names', 'plot_arrays')
                    result_to_save = {k: v for k, v in self.current_detection_result.items()
                                      if k not in _NON_SERIAL}
                    # 메타데이터 추가
                    result_with_meta = {
                        "metadata": {
                            "model_type": "detection",
                            "model_name": "HnE Cell Detection",
                            "version": "1.0",
                            "timestamp": datetime.now().isoformat(),
                            "image_path": str(self.current_image_path) if self.current_image_path else None,
                            "image_name": Path(self.current_image_path).name if self.current_image_path else None
                        },
                        "result": result_to_save
                    }
                    
                    # JSON 형식으로 저장
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(result_with_meta, f, indent=2, ensure_ascii=False)
                else:
                    # 텍스트 형식으로 저장
                    result_text = self.detection_service.format_detection_result(self.current_detection_result)
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(result_text)
                
                self.statusbar.showMessage(f"Results saved: {Path(file_path).name}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save results:\n{str(e)}")

    def save_segmentation_results(self):
        """Segmentation 결과를 Polygon JSON으로 저장"""
        if not self.current_segmentation_result:
            QMessageBox.information(self, "Notice", "No segmentation results to save.")
            return

        default_filename = ""
        if self.current_image_path:
            wsi_filename = Path(self.current_image_path).stem
            default_filename = f"{wsi_filename}_segmentation_result.json"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Segmentation Results",
            default_filename,
            "JSON Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        try:
            self.statusbar.showMessage("Converting segmentation results...")
            QApplication.processEvents()

            seg_result = self.current_segmentation_result
            mask = seg_result['mask']
            metadata = seg_result['metadata']
            class_names_raw = seg_result['class_names']

            # class_names를 list로 통일
            if isinstance(class_names_raw, dict):
                class_names_list = [class_names_raw.get(i, f"Class_{i}") for i in range(max(class_names_raw.keys()) + 1)]
            else:
                class_names_list = list(class_names_raw)

            # mask → polygon 변환
            class_polygons = mask_to_polygons(
                mask, metadata, class_names_list,
                simplify_epsilon=2.0, min_area=10
            )

            # JSON 구조 생성
            result_with_meta = {
                "metadata": {
                    "model_type": "segmentation",
                    "model_name": "HnE_Segmentation",
                    "version": "1.0",
                    "timestamp": datetime.now().isoformat(),
                    "image_path": str(self.current_image_path) if self.current_image_path else None,
                    "image_name": Path(self.current_image_path).name if self.current_image_path else None,
                    "tissue_type": self.current_tissue_type
                },
                "result": {
                    "segmentation_metadata": {
                        "wsi_dimensions": list(metadata.get('wsi_dimensions', [0, 0])),
                        "wsi_mpp": metadata.get('wsi_mpp', 0.25),
                        "model_mpp": metadata.get('model_mpp', 1.0),
                        "output_mpp": metadata.get('output_mpp', 4.0),
                        "mask_shape": list(metadata.get('mask_shape', mask.shape)),
                        "class_names": class_names_list,
                        "region_offset": list(metadata.get('region_offset', (0, 0)))
                    },
                    "roi_bounds": list(seg_result['roi_bounds']) if seg_result.get('roi_bounds') else None,
                    "roi_polygons": seg_result.get('roi_polygons'),
                    "class_polygons": class_polygons,
                    "polygon_coordinate_system": "wsi_level0",
                    "simplification_epsilon": 2.0
                }
            }

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(result_with_meta, f, indent=2, ensure_ascii=False)

            self.statusbar.showMessage(f"Segmentation results saved: {Path(file_path).name}")

        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Failed to save segmentation results:\n{str(e)}")

    def load_detection_results(self):
        """저장된 AI 결과 불러오기 (모델 타입별 처리)"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load AI Results",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                
                # 새 형식 (메타데이터 포함) vs 레거시 형식 확인
                if "metadata" in loaded_data and "result" in loaded_data:
                    # 새 형식
                    metadata = loaded_data["metadata"]
                    result = loaded_data["result"]
                    model_type = metadata.get("model_type", "unknown")
                    model_name = metadata.get("model_name", "Unknown")
                    
                    # 모델 타입별 처리
                    if model_type == "detection":
                        self._load_detection_result(result, metadata)
                        self.statusbar.showMessage(f"Loaded: {model_name} - {result.get('num_cells', 0):,} cells")
                    elif model_type == "segmentation":
                        self._load_segmentation_result(result, metadata)
                        self.statusbar.showMessage(f"Loaded: {model_name} - Segmentation")
                    elif model_type == "classification":
                        # 향후 구현
                        QMessageBox.information(self, "Notice", f"{model_name} results are not yet supported.")
                    else:
                        raise ValueError(f"Unknown model type: {model_type}")
                else:
                    # 레거시 형식 (메타데이터 없음)
                    required_keys = ['num_cells', 'class_counts', 'cells']
                    if all(key in loaded_data for key in required_keys):
                        # Detection 결과로 처리
                        self._load_detection_result(loaded_data, None)
                        self.statusbar.showMessage(f"Results loaded: {loaded_data.get('num_cells', 0):,} cells")
                    else:
                        raise ValueError("Not a valid AI result file.")
                
            except json.JSONDecodeError:
                QMessageBox.critical(self, "Error", "Invalid JSON file format.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load results:\n{str(e)}")
    
    def _load_detection_result(self, result, metadata=None):
        """Detection 결과 로드 처리"""
        # 결과 데이터 설정
        self.current_detection_result = result

        # all_raw_cells 설정 (visualization/slider용)
        cells = result.get('cells', [])
        self.all_raw_cells = cells
        self.current_class_thresholds = {c['cls_id']: 1 for c in cells}
        self.current_color_map = None
        self.is_pdl1_mode = False
        # 파일에서 로드 시 plot_arrays 없음 → 다이얼로그에서 직접 계산
        self._plot_arrays = None

        # 오버레이에 세포 표시
        if cells:
            self.wsi_viewer.set_detection_results(cells)

        # 결과 리스트 업데이트
        num_cells = result.get('num_cells', 0)
        class_counts = result.get('class_counts', {})
        self.update_result_list(class_counts, num_cells)
        
        # Progress 완료 상태로
        self.progressBar.setValue(100)
        self.btnVisualization.setEnabled(True)

        # 메타데이터가 있으면 표시
        if metadata:
            model_info = f"{metadata.get('model_name', 'Unknown')} v{metadata.get('version', '?')}"
            self.progressLabel.setText(f"Loaded: {model_info}")
        else:
            self.progressLabel.setText("Results loaded")

    def _load_segmentation_result(self, result, metadata=None):
        """Segmentation 결과 로드 처리 (polygon JSON → mask 복원 → overlay 표시)"""
        self.statusbar.showMessage("Restoring segmentation results...")
        QApplication.processEvents()

        seg_metadata = result.get('segmentation_metadata', {})
        class_polygons = result.get('class_polygons', {})
        roi_bounds = result.get('roi_bounds')
        roi_polygons = result.get('roi_polygons')
        class_names = seg_metadata.get('class_names', ["Background", "Stroma", "Non_Tumor", "Tumor"])

        # polygon → mask 복원
        mask = polygons_to_mask(class_polygons, seg_metadata)

        # current_segmentation_result 설정
        self.current_segmentation_result = {
            'mask': mask,
            'metadata': seg_metadata,
            'class_names': class_names,
            'roi_bounds': tuple(roi_bounds) if roi_bounds else None,
            'roi_polygons': roi_polygons
        }

        # 기존 오버레이 제거
        self.current_detection_result = None
        self.wsi_viewer.clear_detection_results()
        self.wsi_viewer.clear_segmentation_overlay()

        # 오버레이 표시
        self.wsi_viewer.set_segmentation_overlay(
            mask, seg_metadata, class_names,
            tuple(roi_bounds) if roi_bounds else None,
            roi_polygons
        )

        # 결과 리스트 업데이트
        self.resultList.clear()
        self.update_segmentation_result_list()

        # Progress
        self.progressBar.setValue(100)
        if metadata:
            model_info = f"{metadata.get('model_name', 'Unknown')} v{metadata.get('version', '?')}"
            self.progressLabel.setText(f"Loaded: {model_info}")
        else:
            self.progressLabel.setText("Segmentation results loaded")

    # === Annotation 기능 ===
    
    def _toggle_draw_mode(self, checked, draw_fn, status_msg, other_actions):
        """그리기 모드 토글 공통 로직"""
        if checked:
            for action in other_actions:
                if hasattr(self, action) and getattr(self, action).isChecked():
                    getattr(self, action).setChecked(False)
            self.wsi_viewer.keep_drawing = True
            draw_fn()
            self.statusbar.showMessage(status_msg)
        else:
            self.wsi_viewer.exit_drawing_mode()
            self.statusbar.showMessage("Ready")

    def toggle_draw_polygon(self, checked):
        """Polygon 그리기 토글"""
        self._toggle_draw_mode(
            checked,
            self.wsi_viewer.start_drawing_polygon,
            "ROI drawing mode (persistent): Click to add points, right-click to complete, ESC to cancel",
            ['actionDrawRectangle', 'actionDrawPoint'],
        )

    def toggle_draw_rectangle(self, checked):
        """Rectangle 그리기 토글"""
        self._toggle_draw_mode(
            checked,
            self.wsi_viewer.start_drawing_rectangle,
            "Rectangle drawing mode (persistent): Drag to create rectangle, ESC to cancel",
            ['actionDrawPolygon', 'actionDrawPoint'],
        )

    def toggle_draw_point(self, checked):
        """Point 그리기 토글"""
        self._toggle_draw_mode(
            checked,
            self.wsi_viewer.start_drawing_point,
            "Point drawing mode (persistent): Click to add points, right-click to finish, ESC to cancel",
            ['actionDrawPolygon', 'actionDrawRectangle'],
        )
    
    def start_draw_roi(self):
        """ROI 그리기 시작 (레거시 지원)"""
        self.actionDrawPolygon.setChecked(True)
    
    def clear_roi(self):
        """모든 ROI 삭제"""
        reply = QMessageBox.question(
            self, 
            "Confirm",
            "Delete all ROIs?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.wsi_viewer.clear_annotations()
            self.annotation_panel.clear_annotations()
            self.statusbar.showMessage("All ROIs deleted")
    
    def save_annotations(self):
        """Annotation 저장"""
        annotations = self.wsi_viewer.get_annotations()
        if len(annotations) == 0:
            QMessageBox.information(self, "Notice", "No ROIs to save.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save ROI",
            "",
            "JSON Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        try:
            self.wsi_viewer.save_annotations(file_path)
            self.statusbar.showMessage(f"ROI saved: {Path(file_path).name} ({len(annotations)} items)")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save ROI:\n{str(e)}")
    
    def load_annotations(self):
        """Annotation 로드"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load ROI",
            "",
            "JSON Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        try:
            self.wsi_viewer.load_annotations(file_path)
            num_annotations = len(self.wsi_viewer.get_annotations())
            self.annotation_panel.refresh_table()
            self.statusbar.showMessage(f"ROI loaded: {Path(file_path).name} ({num_annotations} items)")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load ROI:\n{str(e)}")
    
    def on_annotation_added(self, annotation):
        """Annotation 추가 시 호출"""
        num_annotations = len(self.wsi_viewer.get_annotations())
        self.statusbar.showMessage(f"ROI added: {annotation.name} (total {num_annotations})")
        
        # Annotation 패널 업데이트
        self.annotation_panel.add_annotation(annotation)
        
        # 그리기 완료 후에도 툴이 켜져있다면 지속해서 그릴 수 있음 (자동 해제하지 않음)
    
    def on_annotation_selected(self, annotation):
        """Annotation 선택 시 호출 (뷰어에서)"""
        self.statusbar.showMessage(f"ROI selected: {annotation.name}")
        # 패널의 선택 동기화
        self.annotation_panel.select_annotation(annotation)
    
    def on_panel_annotation_selected(self, annotation):
        """Annotation 선택 시 호출 (패널에서)"""
        self.wsi_viewer.select_annotation(annotation)
    
    def on_annotation_deleted(self, annotation):
        """Annotation 삭제 시 호출 (패널에서)"""
        # 뷰어에서 삭제
        self.wsi_viewer.remove_annotation(annotation)
        # 패널에서 삭제
        self.annotation_panel.remove_annotation(annotation)
        self.statusbar.showMessage(f"ROI deleted: {annotation.name}")
    
    def on_drawing_cancelled(self):
        """그리기 취소 시 호출"""
        # 현재 그리기 중인 아이템이 취소된 상태 알림만 표시 (툴은 유지)
        self.statusbar.showMessage("Current drawing cancelled. Continue with the same tool or press 'Stop Drawing' to exit.")

    def stop_drawing(self):
        """사용자가 명시적으로 그리기 모드를 종료할 때 호출"""
        # 모든 그리기 토글 해제
        if hasattr(self, 'actionDrawPolygon') and self.actionDrawPolygon.isChecked():
            self.actionDrawPolygon.setChecked(False)
        if hasattr(self, 'actionDrawRectangle') and self.actionDrawRectangle.isChecked():
            self.actionDrawRectangle.setChecked(False)
        if hasattr(self, 'actionDrawPoint') and self.actionDrawPoint.isChecked():
            self.actionDrawPoint.setChecked(False)
        
        # 뷰어의 그리기 모드 완전 종료
        self.wsi_viewer.exit_drawing_mode()
        self.statusbar.showMessage("Drawing mode ended.")
    
    # ============================================================================
    # Epithelial 재분류 (WSI Segmentation + Cell Detection)
    # ============================================================================

    def run_epithelial_classification(self):
        """Epithelial cell 재분류 실행 (Segmentation 기반)"""
        if not self.current_image_path:
            QMessageBox.warning(self, "Warning", "Please load an image first.")
            return

        if self.current_detection_result is None:
            QMessageBox.warning(self, "Warning", "Please run Cell Detection first.")
            return

        # AI 시작: 그리기 모드 해제
        self.wsi_viewer.exit_drawing_mode()

        # Load segmentation model if not loaded
        if not self.epithelial_classification_service.is_model_loaded():
            self.statusbar.showMessage("Loading segmentation model...")
            QApplication.processEvents()

            success, msg = self.epithelial_classification_service.load_model()
            if not success:
                QMessageBox.critical(self, "Error", msg)
                return
            self.statusbar.showMessage(msg)
            QApplication.processEvents()

        # Get OpenSlide object from tile manager
        tile_manager = self.wsi_viewer.get_tile_manager()
        if tile_manager is None or tile_manager.slide is None:
            QMessageBox.critical(self, "Error", "Unable to load slide.")
            return

        slide = tile_manager.slide

        # Get detection cells
        detection_cells = self.current_detection_result['cells']

        # Check if there are any Epithelial cells
        epithelial_count = sum(1 for cell in detection_cells if cell['cls_id'] == 1)
        if epithelial_count == 0:
            QMessageBox.information(
                self, "Notice",
                "No Epithelial cells detected.\nNo cells to reclassify."
            )
            return

        # Setup signals
        self.setup_classification_signals()

        # Run classification
        self.epithelial_classification_service.run_classification(slide, detection_cells)
        self.statusbar.showMessage(f"Starting Epithelial reclassification... ({epithelial_count} cells)")
        self.progressBar.setValue(0)
        self.progressLabel.setText("Epithelial reclassification in progress...")

    def setup_classification_signals(self):
        """Setup signals for epithelial classification"""
        classifier = self.epithelial_classification_service.get_classifier()

        # Disconnect if already connected (avoid duplicates)
        try:
            classifier.classificationComplete.disconnect()
            classifier.classificationProgress.disconnect()
            classifier.classificationStatus.disconnect()
            classifier.classificationError.disconnect()
        except:
            pass

        # Connect signals
        classifier.classificationComplete.connect(self.on_epithelial_classification_complete)
        classifier.classificationProgress.connect(self.on_ai_progress)
        classifier.classificationStatus.connect(self.on_detection_status)
        classifier.classificationError.connect(self.on_ai_error)

    def on_epithelial_classification_complete(self, result):
        """Handle epithelial classification completion"""
        self.is_detection_running = False
        self.progressBar.setValue(100)
        self.progressLabel.setText("Reclassification complete")

        # Cache results (replace old detection results)
        self.current_detection_result = result

        # Update UI - reuse existing detection result display
        self.wsi_viewer.set_detection_results(result['cells'])
        self.update_result_list(result)

        # 자동저장
        if self.chkAutoSave.isChecked():
            self._auto_save_detection_result()

        # Show detailed message
        msg = self.format_epithelial_classification_result(result)
        QMessageBox.information(self, "Reclassification Complete", msg)
        self.statusbar.showMessage("Epithelial reclassification complete")

    def format_epithelial_classification_result(self, result):
        """Format epithelial classification result message"""
        epi_breakdown = result.get('epithelial_breakdown', {})
        class_counts = result.get('class_counts', {})

        msg = f"Cell detection and reclassification completed\n\n"
        msg += f"Total cells: {result['num_cells']:,}\n\n"
        msg += "=== Epithelial Cell Distribution ===\n"
        msg += f"Tumor region: {epi_breakdown.get('tumor_epithelial', 0):,}\n"
        msg += f"Non-Tumor region: {epi_breakdown.get('nt_epithelial', 0):,}\n"
        msg += f"Stroma/Background: {epi_breakdown.get('stroma_epithelial', 0):,}\n"
        msg += f"Before reclassification: {epi_breakdown.get('total_epithelial', 0):,}\n\n"

        # Add non-epithelial counts
        msg += "=== Other Cells ===\n"
        other_classes = ['Neutrophil', 'Lymphocyte', 'Plasma', 'Eosinophil', 'Connective tissue']
        for cls_name in other_classes:
            count = class_counts.get(cls_name, 0)
            if count > 0:
                msg += f"{cls_name}: {count:,}\n"

        return msg

    def closeEvent(self, event):
        """윈도우 닫기 시 리소스 정리"""
        self.wsi_viewer.close()

        # AI 작업 취소
        self.detection_service.cancel_detection()
        self.epithelial_classification_service.cancel()
        if self.tissue_segmentation is not None:
            self.tissue_segmentation.cancel()
        if self.tissue_classification is not None:
            self.tissue_classification.cancel()

        event.accept()
