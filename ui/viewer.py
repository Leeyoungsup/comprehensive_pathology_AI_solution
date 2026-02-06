"""
병리 이미지 뷰어 메인 윈도우
리팩토링된 간소화 버전 - UI 구성 및 이벤트 처리만 담당
"""

from PyQt5 import uic
from PyQt5.QtWidgets import QMainWindow, QFileDialog, QVBoxLayout, QHBoxLayout, QMessageBox, QAction, QToolBar
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from pathlib import Path
import os
import sys

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from ui.wsi_view_widget import WSIViewWidget, AnnotationMode
from ui.annotation_panel import AnnotationPanel
from ui.dialogs import show_slide_info_dialog

# 서비스 레이어 import
from backend.services import (
    DetectionService,
    SlideService,
    AnnotationService,
    EpithelialClassificationService
)


class PathologyViewer(QMainWindow):
    """병리 이미지 뷰어 메인 윈도우"""
    
    def __init__(self):
        super().__init__()
        self.current_image_path = None
        
        # UI 파일 로드
        ui_path = os.path.join(os.path.dirname(__file__), 'viewer.ui')
        uic.loadUi(ui_path, self)
        
        # WSI 뷰어 위젯 설정
        self.setup_wsi_viewer()
        
        # 서비스 레이어 초기화
        self.detection_service = DetectionService()
        self.slide_service = SlideService()
        self.annotation_service = AnnotationService()
        self.epithelial_classification_service = EpithelialClassificationService()
        
        # AI 모듈 변수 초기화 (레거시, 필요시 삭제 가능)
        self.tissue_segmentation = None
        self.tissue_classification = None
        self.is_detection_running = False  # 검출 진행 상태

        # 클래스별 검출 결과 캐시
        self.current_detection_result = None
        
        # Segmentation 결과 캐시
        self.current_segmentation_result = None
        self.is_segmentation_running = False

        # 조직 타입 (기본값: Stomach)
        self.current_tissue_type = "Stomach"
        
        # 시그널 연결
        self.connect_signals()

        # 추가 UI 요소 설정 (프로그래밍 방식)
        self.setup_ui_additions()

        # 초기 상태 설정
        self.progressBar.setValue(0)
        self.progressLabel.setText("AI Progress")
        self.statusbar.showMessage("준비됨")
    
    def setup_wsi_viewer(self):
        """WSI 뷰어 위젯 설정"""
        # 기존 QLabel을 커스텀 WSIViewWidget으로 교체
        old_viewer = self.imageViewer
        parent = old_viewer.parent()
        layout = old_viewer.parent().layout()
        
        # 기존 위젯 제거
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
        # Cell Detection이 자동으로 Epithelial 재분류를 수행하므로
        # 별도의 재분류 버튼은 필요하지 않음
        pass

    def setup_ai_modules(self):
        """
        AI 모듈 초기화 (Lazy Initialization)
        처음 사용 시에만 호출됨
        """
        # 검출 모듈은 DetectionService를 통해 관리
        detection_module = self.detection_service.get_detection_module()
        detection_module.detectionComplete.connect(self.on_detection_complete)
        detection_module.detectionProgress.connect(self.on_ai_progress)
        detection_module.detectionStatus.connect(self.on_detection_status)
        detection_module.detectionError.connect(self.on_ai_error)
        
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
        # self.actionClearROI.triggered.connect(self.clear_roi)
        # self.actionSaveROI.triggered.connect(self.save_annotations)
        # self.actionLoadROI.triggered.connect(self.load_annotations)
        
        # AI 버튼
        self.btnSegmentation.clicked.connect(self.run_segmentation)
        self.btnClassification.clicked.connect(self.run_classification)
        self.btnHneCellDetection.clicked.connect(self.run_detection)
        self.btnTumorSegmentation.clicked.connect(self.run_tumor_segmentation)

        # 조직 타입 Radio button
        self.radioBreast.toggled.connect(self.on_tissue_type_changed)
        self.radioStomach.toggled.connect(self.on_tissue_type_changed)
        self.radioOther.toggled.connect(self.on_tissue_type_changed)

        # 결과 리스트 아이템 클릭 시그널
        self.resultList.itemClicked.connect(self.on_result_list_item_clicked)
        # 체크박스 변경 시그널 (가시성 토글 처리)
        self.resultList.itemChanged.connect(self.on_result_list_item_changed)
        
        # 결과 관리 버튼
        self.btnClearResults.clicked.connect(self.clear_results)
        self.btnSaveResults.clicked.connect(self.save_detection_results)
        self.btnLoadResults.clicked.connect(self.load_detection_results)

    def on_tissue_type_changed(self):
        """조직 타입 Radio button 변경 시 호출"""
        if self.radioBreast.isChecked():
            self.current_tissue_type = "Breast"
            self.statusbar.showMessage("조직 타입: Breast (Epithelial 재분류 활성화)")
            self.btnTumorSegmentation.setEnabled(True)
        elif self.radioStomach.isChecked():
            self.current_tissue_type = "Stomach"
            self.statusbar.showMessage("조직 타입: Stomach (Epithelial 재분류 활성화)")
            self.btnTumorSegmentation.setEnabled(True)
        elif self.radioOther.isChecked():
            self.current_tissue_type = "Other"
            self.statusbar.showMessage("조직 타입: Other (Epithelial 재분류 비활성화)")
            self.btnTumorSegmentation.setEnabled(False)

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
        """이미지 로드"""
        if self.wsi_viewer.load_wsi(file_path):
            self.current_image_path = file_path
            file_name = Path(file_path).name

            # 그리기 모드 종료 (버튼 상태, 커서 복원)
            self.stop_drawing()

            # 이전 결과 모두 초기화
            self.current_detection_result = None
            self.current_segmentation_result = None
            self.wsi_viewer.clear_detection_results()  # Detection overlay 제거
            self.wsi_viewer.clear_segmentation_overlay()  # Segmentation overlay 제거
            self.wsi_viewer.clear_annotations()        # Annotation/Polygon 제거
            self.annotation_panel.clear_annotations()  # Annotation 패널 테이블 초기화
            self.resultList.clear()                    # 결과 리스트 초기화

            # Progress 초기화
            self.progressBar.setValue(0)
            self.progressLabel.setText("AI Progress")

            self.statusbar.showMessage(f"이미지 로드 완료: {file_name}")
        else:
            self.statusbar.showMessage("이미지 로드 실패")
            QMessageBox.critical(self, "오류", "이미지를 로드할 수 없습니다.")
    
    def on_field_of_view_changed(self, fov_rect, level):
        """보이는 영역 변경 시 호출"""
        # 필요시 추가 처리
        pass
    
    def show_slide_info(self):
        """슬라이드 정보 표시"""
        tile_manager = self.wsi_viewer.get_tile_manager()
        show_slide_info_dialog(tile_manager, self)
    
    # === AI 기능 ===
    
    def run_segmentation(self):
        """조직 분할 실행"""
        if not self.current_image_path:
            self.statusbar.showMessage("먼저 이미지를 로드해주세요.")
            return
        
        # AI 모듈 초기화 (처음 사용 시)
        if self.tissue_segmentation is None:
            self.statusbar.showMessage("조직 분할 모듈 초기화 중...")
            from PyQt5.QtWidgets import QApplication
            QApplication.processEvents()
            self.setup_ai_modules()
        
        self.statusbar.showMessage("조직 분할 분석 실행 중...")
        
        tile_manager = self.wsi_viewer.get_tile_manager()
        self.tissue_segmentation.run_segmentation(self.current_image_path, tile_manager)
    
    def run_classification(self):
        """암 분류 실행"""
        if not self.current_image_path:
            self.statusbar.showMessage("먼저 이미지를 로드해주세요.")
            return
        
        # AI 모듈 초기화 (처음 사용 시)
        if self.tissue_classification is None:
            self.statusbar.showMessage("암 분류 모듈 초기화 중...")
            from PyQt5.QtWidgets import QApplication
            QApplication.processEvents()
            self.setup_ai_modules()
        
        self.statusbar.showMessage("암 분류 분석 실행 중...")
        
        tile_manager = self.wsi_viewer.get_tile_manager()
        self.tissue_classification.run_classification(self.current_image_path, tile_manager)
    
    def run_detection(self):
        """병변 검출 실행 또는 중단"""
        # 진행 중이면 중단
        if self.is_detection_running:
            self.btnHneCellDetection.setText("(통합)Cell Detection")
            self.is_detection_running = False
            
            self.detection_service.cancel_detection()
            self.statusbar.showMessage("검출이 중단되었습니다.")
            return
        
        if not self.current_image_path:
            self.statusbar.showMessage("먼저 이미지를 로드해주세요.")
            return
        
        # 기존 Segmentation 결과 제거
        self.wsi_viewer.clear_segmentation_overlay()
        self.current_segmentation_result = None
        # ResultList 완전 초기화
        self.resultList.clear()
        
        # 버튼 상태 변경
        self.btnHneCellDetection.setText("⏸ 중단")
        self.is_detection_running = True
        
        # Progress 초기화
        self.progressBar.setValue(0)
        self.progressLabel.setText("초기화 중...")
        
        # AI 모듈 초기화
        self.statusbar.showMessage("검출 모듈 초기화 중...")
        from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()
        self.setup_ai_modules()
        
        # 모델 로드
        if not self.detection_service.is_model_loaded():
            self.statusbar.showMessage("모델 로딩 중...")
            QApplication.processEvents()
            
            success, message = self.detection_service.load_model()
            if not success:
                self.statusbar.showMessage("모델 로드 실패")
                QMessageBox.critical(self, "모델 로드 오류", message)
                self.btnHneCellDetection.setText("(통합)Cell Detection")
                self.is_detection_running = False
                return
            
            self.statusbar.showMessage("모델 로드 완료")
        
        self.statusbar.showMessage("세포 검출 분석 실행 중...")
        
        # ROI 영역 가져오기
        roi_polygons = None
        roi_info = "전체 슬라이드"
        if self.wsi_viewer.annotation_list.annotations:
            roi_polygons = self.wsi_viewer.annotation_list.annotations
            roi_count = len(roi_polygons)
            
            # ROI 타입별 카운트
            from core.annotation import AnnotationType
            type_counts = {}
            for ann in roi_polygons:
                type_name = ann.type.value
                type_counts[type_name] = type_counts.get(type_name, 0) + 1
            
            # ROI 정보 문자열 생성
            type_strs = [f"{count}개 {type_name}" for type_name, count in type_counts.items()]
            roi_info = f"ROI {roi_count}개 ({', '.join(type_strs)})"
            
            self.statusbar.showMessage(f"세포 검출 분석 실행 중... [{roi_info}]")
            self.progressLabel.setText(f"검출 대상: {roi_info}")
        else:
            self.progressLabel.setText("검출 대상: 전체 슬라이드")
        
        # 슬라이드 열기 (서비스 이용)
        try:
            QApplication.processEvents()
            
            import time
            start_time = time.time()
            slide, message = self.detection_service.open_slide(self.current_image_path)
            
            if slide is None:
                self.statusbar.showMessage("슬라이드 열기 실패")
                self.btnHneCellDetection.setText("(통합)Cell Detection")
                self.is_detection_running = False
                return
            
            load_time = time.time() - start_time
            self.statusbar.showMessage(f"WSI 로드 완료 ({load_time:.2f}s)")
            QApplication.processEvents()

            # 조직 타입에 따라 Epithelial 재분류 여부 결정
            # Breast, Stomach: 재분류 활성화 / Other: 재분류 비활성화
            auto_classify = (self.current_tissue_type in ["Breast", "Stomach"])

            # 검출 시작 (서비스 이용)
            self.detection_service.start_detection(slide, roi_polygons,
                                                    auto_classify_epithelial=auto_classify,
                                                    tissue_type=self.current_tissue_type)
            
        except Exception as e:
            self.statusbar.showMessage("검출 실행 실패")
            self.btnHneCellDetection.setText("(통합)Cell Detection")
            self.is_detection_running = False
    
    def run_tumor_segmentation(self):
        """Tumor Segmentation 실행"""
        if self.is_segmentation_running:
            self.btnTumorSegmentation.setText("Tumor Segmentation")
            self.is_segmentation_running = False
            self.statusbar.showMessage("Segmentation이 중단되었습니다.")
            return
        
        if not self.current_image_path:
            self.statusbar.showMessage("먼저 이미지를 로드해주세요.")
            return
        
        if self.current_tissue_type == "Other":
            QMessageBox.warning(self, "경고", "Other 타입에서는 Tumor Segmentation을 실행할 수 없습니다.\nBreast 또는 Stomach을 선택해주세요.")
            return
        
        # 기존 Detection 결과 제거
        self.current_detection_result = None
        self.wsi_viewer.clear_detection_overlay()
        # ResultList 완전 초기화
        self.resultList.clear()
        
        # 버튼 상태 변경
        self.btnTumorSegmentation.setText("⏸ 중단")
        self.is_segmentation_running = True
        
        # Progress 초기화
        self.progressBar.setValue(0)
        self.progressLabel.setText("Tumor Segmentation 초기화 중...")
        
        from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()
        
        try:
            # Segmentation 모델 로딩
            from ai.epithelial_classifier import WSISegmentationModel
            from pathlib import Path
            
            project_root = Path(__file__).parent.parent
            if self.current_tissue_type == "Breast":
                model_path = project_root / "model" / "HnE_BR_segmentation.pt"
            elif self.current_tissue_type == "Stomach":
                model_path = project_root / "model" / "HnE_ST_segmentation.pt"
            
            self.statusbar.showMessage("Segmentation 모델 로딩 중...")
            QApplication.processEvents()
            
            seg_model = WSISegmentationModel(
                model_path=str(model_path),
                model_mpp=1.0,
                output_mpp=4.0,
                device='cuda'
            )
            
            # 슬라이드 열기
            import openslide
            slide = openslide.OpenSlide(self.current_image_path)
            
            def progress_callback(progress_pct):
                self.progressBar.setValue(int(progress_pct))
                if int(progress_pct) % 10 == 0:
                    self.progressLabel.setText(f"Segmentation 진행 중... {int(progress_pct)}%")
                    QApplication.processEvents()
            
            self.statusbar.showMessage("Tumor Segmentation 실행 중...")
            
            # ROI polygon 좌표 수집 (있으면)
            roi_polygons = []
            roi_bounds = None
            if self.wsi_viewer.annotation_list.annotations:
                min_x = float('inf')
                min_y = float('inf')
                max_x = float('-inf')
                max_y = float('-inf')
                
                for polygon in self.wsi_viewer.annotation_list.annotations:
                    coords = polygon.coordinates
                    roi_polygons.append(coords)  # polygon 좌표 저장
                    xs = [p[0] for p in coords]
                    ys = [p[1] for p in coords]
                    min_x = min(min_x, min(xs))
                    min_y = min(min_y, min(ys))
                    max_x = max(max_x, max(xs))
                    max_y = max(max_y, max(ys))
                
                roi_bounds = (int(min_x), int(min_y), int(max_x), int(max_y))

            # ROI 좌표 수집 완료 후 annotation 시각적 제거
            if roi_polygons:
                self.wsi_viewer.clear_annotations()
                self.annotation_panel.clear_annotations()

            # Segmentation 실행
            prediction_mask, metadata = seg_model.predict_wsi(
                slide,
                patch_size=512,
                overlap_ratio=0.4,
                batch_size=8,
                progress_callback=progress_callback,
                roi_bounds=roi_bounds
            )
            
            # 결과 저장
            self.current_segmentation_result = {
                'mask': prediction_mask,
                'metadata': metadata,
                'class_names': seg_model.class_names,
                'roi_bounds': roi_bounds,  # ROI bounding box
                'roi_polygons': roi_polygons  # ROI polygon 좌표들
            }
            
            # 오버레이 표시
            self.wsi_viewer.set_segmentation_overlay(prediction_mask, metadata, seg_model.class_names, roi_bounds, roi_polygons)
            
            # 결과 리스트 업데이트
            self.update_segmentation_result_list()
            
            self.progressBar.setValue(100)
            self.progressLabel.setText("Segmentation 완료")
            self.statusbar.showMessage("Tumor Segmentation 완료")
            
            # GPU 메모리 정리
            del seg_model
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            slide.close()
            
        except Exception as e:
            import traceback
            error_msg = f"Segmentation 실행 실패: {str(e)}\n{traceback.format_exc()}"
            print(error_msg)
            QMessageBox.critical(self, "오류", f"Segmentation 실행 실패:\n{str(e)}")
            self.statusbar.showMessage("Segmentation 실행 실패")
        
        finally:
            self.btnTumorSegmentation.setText("Tumor Segmentation")
            self.is_segmentation_running = False
    
    def update_segmentation_result_list(self):
        """Segmentation 결과를 리스트에 표시"""
        if not self.current_segmentation_result:
            return
        
        from PyQt5.QtWidgets import QListWidgetItem
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QIcon, QPixmap, QColor
        
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
        import numpy as np
        
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
                item.setToolTip(f"{cls_name} 영역 표시/숨김")
                self.resultList.addItem(item)
        
        self.resultList.blockSignals(False)
    
    def on_segmentation_complete(self, result):
        """조직 분할 완료"""
        self.statusbar.showMessage(f"조직 분할 완료 - {result.get('message', '')}")
    
    def on_classification_complete(self, result):
        """암 분류 완료"""
        classification = result.get('classification', '')
        self.statusbar.showMessage(f"암 분류 완료 - {classification}")
    
    def on_detection_complete(self, result):
        """병변 검출 완료"""
        num_cells = result.get('num_cells', 0)
        class_counts = result.get('class_counts', {})
        
        # 결과 캐시 저장
        self.current_detection_result = result
        
        # Progress 초기화
        self.progressBar.setValue(100)
        self.progressLabel.setText("검출 완료")
        
        # 상태바 업데이트
        self.statusbar.showMessage(f"세포 검출 완료 - {num_cells:,}개 검출 (GPU 해제됨)")
        
        # 결과 리스트 업데이트
        self.update_result_list(class_counts, num_cells)
        
        # 검출 결과를 오버레이로 표시
        cells = result.get('cells', [])
        if cells:
            self.wsi_viewer.set_detection_results(cells)
        
        # GPU 리소스 해제
        self.detection_service.unload_model()
        
        # 버튼 상태 복원
        self.btnHneCellDetection.setText("(통합)Cell Detection")
        self.is_detection_running = False
    
    def update_result_list(self, class_counts, total_cells):
        """검출 결과를 리스트에 표시 (가시성 향상: 체크박스, 색상 아이콘, 툴팁)"""
        from PyQt5.QtWidgets import QListWidgetItem
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QIcon, QPixmap, QColor
        from ai.detection import CLASS_NAMES, CLASS_COLORS_RGB

        # 업데이트 중에는 시그널 차단
        self.resultList.blockSignals(True)
        self.resultList.clear()

        # 총 세포 수 아이템 (체크박스: 체크=표시, 언체크=숨김)
        total_item = QListWidgetItem(f"전체: {total_cells:,}개")
        total_item.setData(Qt.UserRole, None)
        total_item.setFlags(total_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        total_item.setCheckState(Qt.Checked)
        font = total_item.font()
        font.setBold(True)
        total_item.setFont(font)
        total_item.setToolTip("전체 클래스 표시/숨김")
        self.resultList.addItem(total_item)

        # 클래스별 아이템
        for cls_id, cls_name in CLASS_NAMES.items():
            count = class_counts.get(cls_name, 0)
            if count > 0:
                color_rgb = CLASS_COLORS_RGB.get(cls_id, (255, 255, 255))

                # 컬러 아이콘 생성
                pix = QPixmap(16, 16)
                pix.fill(QColor(*color_rgb))
                icon = QIcon(pix)

                item = QListWidgetItem(icon, f"{cls_name}: {count:,}개")
                item.setData(Qt.UserRole, cls_id)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                item.setCheckState(Qt.Checked)
                # 텍스트 색상은 검은색으로 고정
                item.setForeground(QColor(0, 0, 0))
                item.setToolTip(f"{cls_name}: {count:,}개")
                self.resultList.addItem(item)

        # 시그널 복원
        self.resultList.blockSignals(False)
    
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
        from PyQt5.QtCore import Qt
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
            
            self.statusbar.showMessage(f"Segmentation {cls_name}: {'표시' if visible else '숨김'}")
            return
        
        # Detection 결과
        cls_id = user_data

        # 오버레이 확인
        if not self.wsi_viewer.detection_overlay:
            return

        # 전체 아이템 토글 시 모든 클래스에 반영
        if cls_id is None:
            from ai.detection import CLASS_NAMES
            # 신호 중복 방지
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
            self.statusbar.showMessage("전체 표시" if visible else "전체 숨김")
            return

        # 개별 클래스
        self.wsi_viewer.detection_overlay.set_class_visibility(cls_id, visible)
        self.wsi_viewer.schedule_overlay_update()
        from ai.detection import CLASS_NAMES
        cls_name = CLASS_NAMES.get(cls_id, "Unknown")
        self.statusbar.showMessage(f"{cls_name}: {'표시' if visible else '숨김'}")
    
    def on_ai_progress(self, progress):
        """AI 작업 진행률 업데이트"""
        self.progressBar.setValue(progress)
    
    def on_detection_status(self, status):
        """검출 상태 메시지 업데이트"""
        self.progressLabel.setText(status)
        self.statusbar.showMessage(status)
    
    def on_ai_error(self, error_msg):
        """AI 작업 에러 처리"""
        self.statusbar.showMessage("분석 중 오류 발생")
        
        # 검출 버튼 상태 복원
        if hasattr(self, 'is_detection_running') and self.is_detection_running:
            self.btnHneCellDetection.setText("(통합)Cell Detection")
            self.is_detection_running = False
        
        QMessageBox.critical(self, "오류", error_msg)
    
    def save_results(self):
        """분석 결과 저장 (레거시 메뉴 액션용)"""
        self.save_detection_results()
    
    def clear_results(self):
        """검출/세그멘테이션 결과 지우기"""
        if not self.current_detection_result and not self.current_segmentation_result:
            self.statusbar.showMessage("지울 결과가 없습니다")
            return

        reply = QMessageBox.question(
            self,
            "결과 지우기",
            "AI 분석 결과를 지우시겠습니까?",
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

            # 결과 리스트 초기화
            self.resultList.clear()

            # Progress 초기화
            self.progressBar.setValue(0)
            self.progressLabel.setText("AI Progress")

            self.statusbar.showMessage("분석 결과가 지워졌습니다")
    
    def save_detection_results(self):
        """AI 결과를 JSON 파일로 저장 (Detection 또는 Segmentation)"""
        # Segmentation 결과가 있으면 Segmentation 저장으로 분기
        if self.current_segmentation_result is not None:
            self.save_segmentation_results()
            return

        if not self.current_detection_result:
            QMessageBox.information(self, "알림", "저장할 결과가 없습니다.")
            return
        
        # 기본 파일명 생성 (WSI 파일명에서 확장자 제거)
        default_filename = ""
        if self.current_image_path:
            wsi_filename = Path(self.current_image_path).stem  # 확장자 제외한 파일명
            default_filename = f"{wsi_filename}_detection_result.json"
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "검출 결과 저장",
            default_filename,
            "JSON Files (*.json);;Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                import json
                from datetime import datetime
                
                # 파일 확장자 확인
                if file_path.endswith('.json'):
                    # 메타데이터 추가
                    result_with_meta = {
                        "metadata": {
                            "model_type": "detection",
                            "model_name": "YOLOv11n",
                            "version": "1.0",
                            "timestamp": datetime.now().isoformat(),
                            "image_path": str(self.current_image_path) if self.current_image_path else None,
                            "image_name": Path(self.current_image_path).name if self.current_image_path else None
                        },
                        "result": self.current_detection_result
                    }
                    
                    # JSON 형식으로 저장
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(result_with_meta, f, indent=2, ensure_ascii=False)
                else:
                    # 텍스트 형식으로 저장
                    result_text = self.detection_service.format_detection_result(self.current_detection_result)
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(result_text)
                
                self.statusbar.showMessage(f"결과 저장 완료: {Path(file_path).name}")
            except Exception as e:
                QMessageBox.critical(self, "오류", f"결과 저장 실패:\n{str(e)}")

    def save_segmentation_results(self):
        """Segmentation 결과를 Polygon JSON으로 저장"""
        if not self.current_segmentation_result:
            QMessageBox.information(self, "알림", "저장할 Segmentation 결과가 없습니다.")
            return

        default_filename = ""
        if self.current_image_path:
            wsi_filename = Path(self.current_image_path).stem
            default_filename = f"{wsi_filename}_segmentation_result.json"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Segmentation 결과 저장",
            default_filename,
            "JSON Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        try:
            import json
            from datetime import datetime
            from utils.coordinate_utils import mask_to_polygons

            self.statusbar.showMessage("Segmentation 결과 변환 중...")
            from PyQt5.QtWidgets import QApplication
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

            self.statusbar.showMessage(f"Segmentation 결과 저장 완료: {Path(file_path).name}")

        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "오류", f"Segmentation 결과 저장 실패:\n{str(e)}")

    def load_detection_results(self):
        """저장된 AI 결과 불러오기 (모델 타입별 처리)"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "AI 결과 불러오기",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                import json
                
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
                        self.statusbar.showMessage(f"불러오기 완료: {model_name} - {result.get('num_cells', 0):,}개 세포")
                    elif model_type == "segmentation":
                        self._load_segmentation_result(result, metadata)
                        self.statusbar.showMessage(f"불러오기 완료: {model_name} - Segmentation")
                    elif model_type == "classification":
                        # 향후 구현
                        QMessageBox.information(self, "알림", f"{model_name} 결과는 아직 지원되지 않습니다.")
                    else:
                        raise ValueError(f"알 수 없는 모델 타입: {model_type}")
                else:
                    # 레거시 형식 (메타데이터 없음)
                    required_keys = ['num_cells', 'class_counts', 'cells']
                    if all(key in loaded_data for key in required_keys):
                        # Detection 결과로 처리
                        self._load_detection_result(loaded_data, None)
                        self.statusbar.showMessage(f"결과 불러오기 완료: {loaded_data.get('num_cells', 0):,}개 세포")
                    else:
                        raise ValueError("올바른 AI 결과 파일이 아닙니다.")
                
            except json.JSONDecodeError:
                QMessageBox.critical(self, "오류", "JSON 파일 형식이 올바르지 않습니다.")
            except Exception as e:
                QMessageBox.critical(self, "오류", f"결과 불러오기 실패:\n{str(e)}")
    
    def _load_detection_result(self, result, metadata=None):
        """Detection 결과 로드 처리"""
        # 결과 데이터 설정
        self.current_detection_result = result
        
        # 오버레이에 세포 표시
        cells = result.get('cells', [])
        if cells:
            self.wsi_viewer.set_detection_results(cells)
        
        # 결과 리스트 업데이트
        num_cells = result.get('num_cells', 0)
        class_counts = result.get('class_counts', {})
        self.update_result_list(class_counts, num_cells)
        
        # Progress 완료 상태로
        self.progressBar.setValue(100)
        
        # 메타데이터가 있으면 표시
        if metadata:
            model_info = f"{metadata.get('model_name', 'Unknown')} v{metadata.get('version', '?')}"
            self.progressLabel.setText(f"로드 완료: {model_info}")
        else:
            self.progressLabel.setText("결과 로드 완료")

    def _load_segmentation_result(self, result, metadata=None):
        """Segmentation 결과 로드 처리 (polygon JSON → mask 복원 → overlay 표시)"""
        from utils.coordinate_utils import polygons_to_mask

        self.statusbar.showMessage("Segmentation 결과 복원 중...")
        from PyQt5.QtWidgets import QApplication
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

        # 기존 오버레이 및 annotation 제거
        self.current_detection_result = None
        self.wsi_viewer.clear_detection_results()
        self.wsi_viewer.clear_segmentation_overlay()
        self.wsi_viewer.clear_annotations()
        self.annotation_panel.clear_annotations()

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
            self.progressLabel.setText(f"로드 완료: {model_info}")
        else:
            self.progressLabel.setText("Segmentation 결과 로드 완료")

    # === Annotation 기능 ===
    
    def toggle_draw_polygon(self, checked):
        """Polygon 그리기 토글"""
        if checked:
            # 다른 그리기 버튼 해제
            if hasattr(self, 'actionDrawRectangle') and self.actionDrawRectangle.isChecked():
                self.actionDrawRectangle.setChecked(False)
            if hasattr(self, 'actionDrawPoint') and self.actionDrawPoint.isChecked():
                self.actionDrawPoint.setChecked(False)
            
            # Polygon 그리기 모드 활성화 (지속 그리기)
            self.wsi_viewer.keep_drawing = True
            self.wsi_viewer.start_drawing_polygon()
            self.statusbar.showMessage("ROI 그리기 모드(지속): 클릭으로 점 추가, 우클릭으로 완성, ESC로 취소")
        else:
            # 일반 모드로 복귀
            self.wsi_viewer.exit_drawing_mode()
            self.statusbar.showMessage("준비됨")
    
    def toggle_draw_rectangle(self, checked):
        """Rectangle 그리기 토글"""
        if checked:
            # 다른 그리기 버튼 해제
            if self.actionDrawPolygon.isChecked():
                self.actionDrawPolygon.setChecked(False)
            if hasattr(self, 'actionDrawPoint') and self.actionDrawPoint.isChecked():
                self.actionDrawPoint.setChecked(False)
            
            # Rectangle 그리기 모드 활성화 (지속 그리기)
            self.wsi_viewer.keep_drawing = True
            self.wsi_viewer.start_drawing_rectangle()
            self.statusbar.showMessage("사각형 그리기 모드(지속): 드래그로 사각형 생성, ESC로 취소")
        else:
            # 일반 모드로 복귀
            self.wsi_viewer.exit_drawing_mode()
            self.statusbar.showMessage("준비됨")
    
    def toggle_draw_point(self, checked):
        """Point 그리기 토글"""
        if checked:
            # 다른 그리기 버튼 해제
            if self.actionDrawPolygon.isChecked():
                self.actionDrawPolygon.setChecked(False)
            if hasattr(self, 'actionDrawRectangle') and self.actionDrawRectangle.isChecked():
                self.actionDrawRectangle.setChecked(False)
            
            # Point 그리기 모드 활성화 (지속 그리기)
            self.wsi_viewer.keep_drawing = True
            self.wsi_viewer.start_drawing_point()
            self.statusbar.showMessage("포인트 그리기 모드(지속): 클릭으로 점 추가, 우클릭으로 종료, ESC로 취소")
        else:
            # 일반 모드로 복귀
            self.wsi_viewer.exit_drawing_mode()
            self.statusbar.showMessage("준비됨")
    
    def start_draw_roi(self):
        """ROI 그리기 시작 (레거시 지원)"""
        self.actionDrawPolygon.setChecked(True)
    
    def clear_roi(self):
        """모든 ROI 삭제"""
        reply = QMessageBox.question(
            self, 
            "확인", 
            "모든 ROI를 삭제하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.wsi_viewer.clear_annotations()
            self.annotation_panel.clear_annotations()
            self.statusbar.showMessage("모든 ROI 삭제됨")
    
    def save_annotations(self):
        """Annotation 저장"""
        annotations = self.wsi_viewer.get_annotations()
        if len(annotations) == 0:
            QMessageBox.information(self, "알림", "저장할 ROI가 없습니다.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "ROI 저장",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            # 서비스를 통한 저장
            success, message = self.annotation_service.save_annotations(annotations, file_path)
            
            if success:
                self.statusbar.showMessage(message)
            else:
                QMessageBox.critical(self, "오류", message)
    
    def load_annotations(self):
        """Annotation 로드"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "ROI 불러오기",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            # 서비스를 통한 로드
            data, message = self.annotation_service.load_annotations(file_path)
            
            if data is None:
                QMessageBox.critical(self, "오류", message)
                return
            
            # 데이터 유효성 검사
            valid, validation_msg = self.annotation_service.validate_annotation_data(data)
            if not valid:
                QMessageBox.critical(self, "오류", f"잘못된 데이터:\n{validation_msg}")
                return
            
            try:
                # WSI 뷰어를 통해 annotation 복원
                self.wsi_viewer.load_annotations(file_path)
                num_annotations = len(self.wsi_viewer.get_annotations())
                
                # Annotation 패널 새로고침
                self.annotation_panel.refresh_table()
                self.statusbar.showMessage(message)
                
            except Exception as e:
                QMessageBox.critical(self, "오류", f"ROI 로드 실패:\n{str(e)}")
    
    def on_annotation_added(self, annotation):
        """Annotation 추가 시 호출"""
        num_annotations = len(self.wsi_viewer.get_annotations())
        self.statusbar.showMessage(f"ROI 추가됨: {annotation.name} (총 {num_annotations}개)")
        
        # Annotation 패널 업데이트
        self.annotation_panel.add_annotation(annotation)
        
        # 그리기 완료 후에도 툴이 켜져있다면 지속해서 그릴 수 있음 (자동 해제하지 않음)
    
    def on_annotation_selected(self, annotation):
        """Annotation 선택 시 호출 (뷰어에서)"""
        self.statusbar.showMessage(f"ROI 선택됨: {annotation.name}")
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
        self.statusbar.showMessage(f"ROI 삭제됨: {annotation.name}")
    
    def on_drawing_cancelled(self):
        """그리기 취소 시 호출"""
        # 현재 그리기 중인 아이템이 취소된 상태 알림만 표시 (툴은 유지)
        self.statusbar.showMessage("현재 그리기 중인 항목이 취소되었습니다. 계속하려면 동일 도구를 사용하거나 'Stop Drawing'을 눌러 종료하세요.")

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
        self.statusbar.showMessage("그리기 모드가 종료되었습니다.")
    
    # ============================================================================
    # Epithelial 재분류 (WSI Segmentation + Cell Detection)
    # ============================================================================

    def run_epithelial_classification(self):
        """Epithelial cell 재분류 실행 (Segmentation 기반)"""
        if not self.current_image_path:
            QMessageBox.warning(self, "경고", "먼저 이미지를 로드하세요.")
            return

        if self.current_detection_result is None:
            QMessageBox.warning(self, "경고", "먼저 Cell Detection을 실행하세요.")
            return

        # Load segmentation model if not loaded
        if not self.epithelial_classification_service.is_model_loaded():
            self.statusbar.showMessage("Segmentation 모델 로드 중...")
            from PyQt5.QtWidgets import QApplication
            QApplication.processEvents()

            success, msg = self.epithelial_classification_service.load_model()
            if not success:
                QMessageBox.critical(self, "오류", msg)
                return
            self.statusbar.showMessage(msg)
            QApplication.processEvents()

        # Get OpenSlide object from tile manager
        tile_manager = self.wsi_viewer.get_tile_manager()
        if tile_manager is None or tile_manager.slide is None:
            QMessageBox.critical(self, "오류", "슬라이드를 로드할 수 없습니다.")
            return

        slide = tile_manager.slide

        # Get detection cells
        detection_cells = self.current_detection_result['cells']

        # Check if there are any Epithelial cells
        epithelial_count = sum(1 for cell in detection_cells if cell['cls_id'] == 1)
        if epithelial_count == 0:
            QMessageBox.information(
                self, "알림",
                "Epithelial cell이 검출되지 않았습니다.\n재분류할 세포가 없습니다."
            )
            return

        # Setup signals
        self.setup_classification_signals()

        # Run classification
        self.epithelial_classification_service.run_classification(slide, detection_cells)
        self.statusbar.showMessage(f"Epithelial 재분류 시작... ({epithelial_count}개 세포)")
        self.progressBar.setValue(0)
        self.progressLabel.setText("Epithelial 재분류 중...")

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
        self.progressLabel.setText("재분류 완료")

        # Cache results (replace old detection results)
        self.current_detection_result = result

        # Update UI - reuse existing detection result display
        self.wsi_viewer.set_detection_results(result['cells'])
        self.update_result_list(result)

        # Show detailed message
        msg = self.format_epithelial_classification_result(result)
        QMessageBox.information(self, "재분류 완료", msg)
        self.statusbar.showMessage("Epithelial 재분류 완료")

    def format_epithelial_classification_result(self, result):
        """Format epithelial classification result message"""
        epi_breakdown = result.get('epithelial_breakdown', {})
        class_counts = result.get('class_counts', {})

        msg = f"세포 검출 및 재분류 완료\n\n"
        msg += f"총 세포 수: {result['num_cells']:,}개\n\n"
        msg += "=== Epithelial 세포 분포 ===\n"
        msg += f"Tumor 영역: {epi_breakdown.get('tumor_epithelial', 0):,}개\n"
        msg += f"Non-Tumor 영역: {epi_breakdown.get('nt_epithelial', 0):,}개\n"
        msg += f"Stroma/Background: {epi_breakdown.get('stroma_epithelial', 0):,}개\n"
        msg += f"재분류 전: {epi_breakdown.get('total_epithelial', 0):,}개\n\n"

        # Add non-epithelial counts
        msg += "=== 기타 세포 ===\n"
        other_classes = ['Neutrophil', 'Lymphocyte', 'Plasma', 'Eosinophil', 'Connective tissue']
        for cls_name in other_classes:
            count = class_counts.get(cls_name, 0)
            if count > 0:
                msg += f"{cls_name}: {count:,}개\n"

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
