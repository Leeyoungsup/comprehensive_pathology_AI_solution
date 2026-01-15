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
from backend.services import DetectionService, SlideService, AnnotationService


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
        
        # AI 모듈 변수 초기화 (레거시, 필요시 삭제 가능)
        self.tissue_segmentation = None
        self.tissue_classification = None
        self.is_detection_running = False  # 검출 진행 상태
        
        # 클래스별 검출 결과 캐시
        self.current_detection_result = None
        
        # 시그널 연결
        self.connect_signals()
        
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
        # self.actionClearROI.triggered.connect(self.clear_roi)
        # self.actionSaveROI.triggered.connect(self.save_annotations)
        # self.actionLoadROI.triggered.connect(self.load_annotations)
        
        # AI 버튼
        self.btnSegmentation.clicked.connect(self.run_segmentation)
        self.btnClassification.clicked.connect(self.run_classification)
        self.btnHneCellDetection.clicked.connect(self.run_detection)
        
        # 결과 리스트 아이템 클릭 시그널
        self.resultList.itemClicked.connect(self.on_result_list_item_clicked)
        
        # 결과 관리 버튼
        self.btnClearResults.clicked.connect(self.clear_results)
        self.btnSaveResults.clicked.connect(self.save_detection_results)
        self.btnLoadResults.clicked.connect(self.load_detection_results)
    
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
            self.statusbar.showMessage(f"이미지 로드 완료: {file_name}")
            self.resultList.clear()
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
            
            # 검출 시작 (서비스 이용)
            self.detection_service.start_detection(slide, roi_polygons)
            
        except Exception as e:
            self.statusbar.showMessage("검출 실행 실패")
            self.btnHneCellDetection.setText("(통합)Cell Detection")
            self.is_detection_running = False
    
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
        """검출 결과를 리스트에 표시"""
        from PyQt5.QtWidgets import QListWidgetItem
        from PyQt5.QtCore import Qt
        from ai.detection import CLASS_NAMES, CLASS_COLORS_RGB
        
        self.resultList.clear()
        
        # 총 세포 수 아이템
        total_item = QListWidgetItem(f"✓ 전체: {total_cells:,}개")
        total_item.setData(Qt.UserRole, None)  # 전체는 None으로 표시
        font = total_item.font()
        font.setBold(True)
        total_item.setFont(font)
        self.resultList.addItem(total_item)
        
        # 클래스별 아이템
        for cls_id, cls_name in CLASS_NAMES.items():
            count = class_counts.get(cls_name, 0)
            if count > 0:
                # 클래스 색상
                color_rgb = CLASS_COLORS_RGB.get(cls_id, (255, 255, 255))
                
                item = QListWidgetItem(f"✓ {cls_name}: {count:,}개")
                item.setData(Qt.UserRole, cls_id)  # 클래스 ID 저장
                
                # 색상 표시
                from PyQt5.QtGui import QColor
                item.setForeground(QColor(color_rgb[0], color_rgb[1], color_rgb[2]))
                
                self.resultList.addItem(item)
    
    def on_result_list_item_clicked(self, item):
        """결과 리스트 아이템 클릭 시 클래스 토글"""
        cls_id = item.data(Qt.UserRole)
        
        # 오버레이 체크
        if not self.wsi_viewer.detection_overlay:
            return
        
        # 전체 아이템 클릭 시 모든 클래스 토글
        if cls_id is None:
            text = item.text()
            # 현재 전체 상태 확인 (✓면 보이는 상태, ✗면 숨김 상태)
            current_all_visible = text.startswith("✓")
            new_all_visible = not current_all_visible
            
            # 모든 클래스 visibility 토글
            from ai.detection import CLASS_NAMES
            for cls_id_to_toggle in CLASS_NAMES.keys():
                self.wsi_viewer.detection_overlay.set_class_visibility(cls_id_to_toggle, new_all_visible)
            
            # 전체 아이템 텍스트 업데이트
            if new_all_visible:
                item.setText(text.replace("✗", "✓", 1))
            else:
                item.setText(text.replace("✓", "✗", 1))
            
            # 모든 클래스 아이템 텍스트 업데이트
            for i in range(1, self.resultList.count()):  # 0번은 전체 아이템이므로 1번부터
                class_item = self.resultList.item(i)
                class_text = class_item.text()
                if new_all_visible:
                    if class_text.startswith("✗"):
                        class_item.setText("✓" + class_text[1:])
                else:
                    if class_text.startswith("✓"):
                        class_item.setText("✗" + class_text[1:])
            
            # 오버레이 다시 그리기
            self.wsi_viewer.schedule_overlay_update()
            
            # 상태바 업데이트
            visibility_text = "전체 표시" if new_all_visible else "전체 숨김"
            self.statusbar.showMessage(visibility_text)
            return
        
        # 개별 클래스 토글
        current_visibility = self.wsi_viewer.detection_overlay.class_visibility.get(cls_id, True)
        new_visibility = not current_visibility
        
        # visibility 토글
        self.wsi_viewer.detection_overlay.set_class_visibility(cls_id, new_visibility)
        
        # 아이템 텍스트 업데이트 (체크 표시)
        text = item.text()
        if new_visibility:
            # 보이기
            if text.startswith("✗"):
                text = "✓" + text[1:]
        else:
            # 숨기기
            if text.startswith("✓"):
                text = "✗" + text[1:]
        
        item.setText(text)
        
        # 오버레이 다시 그리기
        self.wsi_viewer.schedule_overlay_update()
        
        # 상태바 업데이트
        from ai.detection import CLASS_NAMES
        cls_name = CLASS_NAMES.get(cls_id, "Unknown")
        visibility_text = "표시" if new_visibility else "숨김"
        self.statusbar.showMessage(f"{cls_name}: {visibility_text}")
    
    def on_ai_progress(self, progress):
        """AI 작업 진행률 업데이트"""
        self.progressBar.setValue(progress)
        msg = f"분석 진행 중... {progress}%"
        self.progressLabel.setText(msg)
        self.statusbar.showMessage(msg)
    
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
        """검출 결과 지우기"""
        if not self.current_detection_result:
            self.statusbar.showMessage("지울 결과가 없습니다")
            return
        
        reply = QMessageBox.question(
            self, 
            "결과 지우기", 
            "검출 결과를 지우시겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 결과 데이터 초기화
            self.current_detection_result = None
            
            # 오버레이 제거
            self.wsi_viewer.clear_detection_results()
            
            # 결과 리스트 초기화
            self.resultList.clear()
            
            # Progress 초기화
            self.progressBar.setValue(0)
            self.progressLabel.setText("AI Progress")
            
            self.statusbar.showMessage("검출 결과가 지워졌습니다")
    
    def save_detection_results(self):
        """검출 결과를 JSON 파일로 저장"""
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
                        # 향후 구현
                        QMessageBox.information(self, "알림", f"{model_name} 결과는 아직 지원되지 않습니다.")
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
    
    # === Annotation 기능 ===
    
    def toggle_draw_polygon(self, checked):
        """Polygon 그리기 토글"""
        if checked:
            # 다른 그리기 버튼 해제
            if hasattr(self, 'actionDrawRectangle') and self.actionDrawRectangle.isChecked():
                self.actionDrawRectangle.setChecked(False)
            if hasattr(self, 'actionDrawPoint') and self.actionDrawPoint.isChecked():
                self.actionDrawPoint.setChecked(False)
            
            # Polygon 그리기 모드 활성화
            self.wsi_viewer.start_drawing_polygon()
            self.statusbar.showMessage("ROI 그리기 모드: 클릭으로 점 추가, 우클릭으로 완성, ESC로 취소")
        else:
            # 일반 모드로 복귀
            self.wsi_viewer.cancel_drawing()
            self.wsi_viewer.set_annotation_mode(AnnotationMode.NONE)
            self.statusbar.showMessage("준비됨")
    
    def toggle_draw_rectangle(self, checked):
        """Rectangle 그리기 토글"""
        if checked:
            # 다른 그리기 버튼 해제
            if self.actionDrawPolygon.isChecked():
                self.actionDrawPolygon.setChecked(False)
            if hasattr(self, 'actionDrawPoint') and self.actionDrawPoint.isChecked():
                self.actionDrawPoint.setChecked(False)
            
            # Rectangle 그리기 모드 활성화
            self.wsi_viewer.start_drawing_rectangle()
            self.statusbar.showMessage("사각형 그리기 모드: 드래그로 사각형 생성, ESC로 취소")
        else:
            # 일반 모드로 복귀
            self.wsi_viewer.cancel_drawing()
            self.wsi_viewer.set_annotation_mode(AnnotationMode.NONE)
            self.statusbar.showMessage("준비됨")
    
    def toggle_draw_point(self, checked):
        """Point 그리기 토글"""
        if checked:
            # 다른 그리기 버튼 해제
            if self.actionDrawPolygon.isChecked():
                self.actionDrawPolygon.setChecked(False)
            if hasattr(self, 'actionDrawRectangle') and self.actionDrawRectangle.isChecked():
                self.actionDrawRectangle.setChecked(False)
            
            # Point 그리기 모드 활성화
            self.wsi_viewer.start_drawing_point()
            self.statusbar.showMessage("포인트 그리기 모드: 클릭으로 점 추가, 우클릭으로 종료, ESC로 취소")
        else:
            # 일반 모드로 복귀
            self.wsi_viewer.set_annotation_mode(AnnotationMode.NONE)
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
        
        # 그리기 완료 후 자동으로 토글 해제
        if self.actionDrawPolygon.isChecked():
            self.actionDrawPolygon.setChecked(False)
        if hasattr(self, 'actionDrawRectangle') and self.actionDrawRectangle.isChecked():
            self.actionDrawRectangle.setChecked(False)
        if hasattr(self, 'actionDrawPoint') and self.actionDrawPoint.isChecked():
            self.actionDrawPoint.setChecked(False)
    
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
        if self.actionDrawPolygon.isChecked():
            self.actionDrawPolygon.setChecked(False)
        if hasattr(self, 'actionDrawRectangle') and self.actionDrawRectangle.isChecked():
            self.actionDrawRectangle.setChecked(False)
        if hasattr(self, 'actionDrawPoint') and self.actionDrawPoint.isChecked():
            self.actionDrawPoint.setChecked(False)
        self.statusbar.showMessage("ROI 그리기 취소됨")
    
    def closeEvent(self, event):
        """윈도우 닫기 시 리소스 정리"""
        self.wsi_viewer.close()
        
        # AI 작업 취소
        self.detection_service.cancel_detection()
        if self.tissue_segmentation is not None:
            self.tissue_segmentation.cancel()
        if self.tissue_classification is not None:
            self.tissue_classification.cancel()
        
        event.accept()
