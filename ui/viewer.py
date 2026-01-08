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
from ai import TissueSegmentation, TissueClassification, LesionDetection


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
        
        # Annotation 툴바 추가
        self.setup_annotation_toolbar()
        
        # AI 모듈 초기화
        self.setup_ai_modules()
        
        # 시그널 연결
        self.connect_signals()
        
        # 초기 상태 설정
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
    
    def setup_annotation_toolbar(self):
        """Annotation 툴바 생성"""
        # Annotation 툴바 (기존 툴바 옆에 추가)
        annotation_toolbar = QToolBar("Annotation Tools")
        annotation_toolbar.setObjectName("annotationToolbar")
        self.addToolBar(Qt.TopToolBarArea, annotation_toolbar)
        
        # Polygon 그리기 토글 버튼
        self.actionDrawPolygon = QAction("🖊️ Polygon", self)
        self.actionDrawPolygon.setCheckable(True)
        self.actionDrawPolygon.setToolTip("Polygon 그리기 (클릭: 점 추가, 우클릭: 완성, ESC: 취소)")
        self.actionDrawPolygon.toggled.connect(self.toggle_draw_polygon)
        annotation_toolbar.addAction(self.actionDrawPolygon)
        
        annotation_toolbar.addSeparator()
        
        # ROI 삭제 버튼
        self.actionClearROI = QAction("🗑️ Clear ROI", self)
        self.actionClearROI.setToolTip("모든 ROI 삭제")
        self.actionClearROI.triggered.connect(self.clear_roi)
        annotation_toolbar.addAction(self.actionClearROI)
        
        annotation_toolbar.addSeparator()
        
        # ROI 저장 버튼
        self.actionSaveROI = QAction("💾 Save ROI", self)
        self.actionSaveROI.setToolTip("ROI 저장")
        self.actionSaveROI.triggered.connect(self.save_annotations)
        annotation_toolbar.addAction(self.actionSaveROI)
        
        # ROI 로드 버튼
        self.actionLoadROI = QAction("📁 Load ROI", self)
        self.actionLoadROI.setToolTip("ROI 불러오기")
        self.actionLoadROI.triggered.connect(self.load_annotations)
        annotation_toolbar.addAction(self.actionLoadROI)
    
    def setup_ai_modules(self):
        """AI 모듈 초기화"""
        # 조직 분할
        self.tissue_segmentation = TissueSegmentation()
        self.tissue_segmentation.segmentationComplete.connect(self.on_segmentation_complete)
        self.tissue_segmentation.segmentationProgress.connect(self.on_ai_progress)
        self.tissue_segmentation.segmentationError.connect(self.on_ai_error)
        
        # 암 분류
        self.tissue_classification = TissueClassification()
        self.tissue_classification.classificationComplete.connect(self.on_classification_complete)
        self.tissue_classification.classificationProgress.connect(self.on_ai_progress)
        self.tissue_classification.classificationError.connect(self.on_ai_error)
        
        # 병변 검출
        self.lesion_detection = LesionDetection()
        self.lesion_detection.detectionComplete.connect(self.on_detection_complete)
        self.lesion_detection.detectionProgress.connect(self.on_ai_progress)
        self.lesion_detection.detectionError.connect(self.on_ai_error)
    
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
        
        # AI 버튼
        self.btnSegmentation.clicked.connect(self.run_segmentation)
        self.btnClassification.clicked.connect(self.run_classification)
        self.btnDetection.clicked.connect(self.run_detection)
        
        # Annotation 버튼 (UI에 있는 경우)
        if hasattr(self, 'btnDrawROI'):
            self.btnDrawROI.clicked.connect(self.start_draw_roi)
        if hasattr(self, 'btnClearROI'):
            self.btnClearROI.clicked.connect(self.clear_roi)
        if hasattr(self, 'actionSaveAnnotations'):
            self.actionSaveAnnotations.triggered.connect(self.save_annotations)
        if hasattr(self, 'actionLoadAnnotations'):
            self.actionLoadAnnotations.triggered.connect(self.load_annotations)
    
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
            self.resultText.clear()
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
            self.resultText.setText("먼저 이미지를 로드해주세요.")
            return
        
        self.resultText.setText("조직 분할 분석 실행 중...")
        self.statusbar.showMessage("조직 분할 분석 실행 중...")
        
        tile_manager = self.wsi_viewer.get_tile_manager()
        self.tissue_segmentation.run_segmentation(self.current_image_path, tile_manager)
    
    def run_classification(self):
        """암 분류 실행"""
        if not self.current_image_path:
            self.resultText.setText("먼저 이미지를 로드해주세요.")
            return
        
        self.resultText.setText("암 분류 분석 실행 중...")
        self.statusbar.showMessage("암 분류 분석 실행 중...")
        
        tile_manager = self.wsi_viewer.get_tile_manager()
        self.tissue_classification.run_classification(self.current_image_path, tile_manager)
    
    def run_detection(self):
        """병변 검출 실행"""
        if not self.current_image_path:
            self.resultText.setText("먼저 이미지를 로드해주세요.")
            return
        
        self.resultText.setText("병변 검출 분석 실행 중...")
        self.statusbar.showMessage("병변 검출 분석 실행 중...")
        
        tile_manager = self.wsi_viewer.get_tile_manager()
        self.lesion_detection.run_detection(self.current_image_path, tile_manager)
    
    def on_segmentation_complete(self, result):
        """조직 분할 완료"""
        message = f"조직 분할 완료\n{result.get('message', '')}"
        self.resultText.setText(message)
        self.statusbar.showMessage("조직 분할 완료")
    
    def on_classification_complete(self, result):
        """암 분류 완료"""
        message = f"암 분류 완료\n{result.get('message', '')}"
        if result.get('classification'):
            message += f"\n분류: {result['classification']}"
        self.resultText.setText(message)
        self.statusbar.showMessage("암 분류 완료")
    
    def on_detection_complete(self, result):
        """병변 검출 완료"""
        num_detections = result.get('num_detections', 0)
        message = f"병변 검출 완료\n{result.get('message', '')}"
        message += f"\n검출된 병변 수: {num_detections}"
        self.resultText.setText(message)
        self.statusbar.showMessage("병변 검출 완료")
    
    def on_ai_progress(self, progress):
        """AI 작업 진행률 업데이트"""
        self.statusbar.showMessage(f"분석 진행 중... {progress}%")
    
    def on_ai_error(self, error_msg):
        """AI 작업 에러 처리"""
        self.resultText.setText(f"오류 발생:\n{error_msg}")
        self.statusbar.showMessage("분석 중 오류 발생")
        QMessageBox.critical(self, "오류", error_msg)
    
    def save_results(self):
        """분석 결과 저장"""
        if not self.current_image_path:
            QMessageBox.information(self, "알림", "저장할 결과가 없습니다.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "결과 저장",
            "",
            "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.resultText.toPlainText())
                self.statusbar.showMessage(f"결과 저장 완료: {Path(file_path).name}")
            except Exception as e:
                QMessageBox.critical(self, "오류", f"결과 저장 실패:\n{str(e)}")
    
    # === Annotation 기능 ===
    
    def toggle_draw_polygon(self, checked):
        """Polygon 그리기 토글"""
        if checked:
            # Polygon 그리기 모드 활성화
            self.wsi_viewer.start_drawing_polygon()
            self.statusbar.showMessage("ROI 그리기 모드: 클릭으로 점 추가, 우클릭으로 완성, ESC로 취소")
        else:
            # 일반 모드로 복귀
            self.wsi_viewer.cancel_drawing()
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
        if len(self.wsi_viewer.get_annotations()) == 0:
            QMessageBox.information(self, "알림", "저장할 ROI가 없습니다.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "ROI 저장",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                self.wsi_viewer.save_annotations(file_path)
                self.statusbar.showMessage(f"ROI 저장 완료: {Path(file_path).name}")
            except Exception as e:
                QMessageBox.critical(self, "오류", f"ROI 저장 실패:\n{str(e)}")
    
    def load_annotations(self):
        """Annotation 로드"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "ROI 불러오기",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                self.wsi_viewer.load_annotations(file_path)
                num_annotations = len(self.wsi_viewer.get_annotations())
                # Annotation 패널 새로고침
                self.annotation_panel.refresh_table()
                self.statusbar.showMessage(f"ROI 로드 완료: {num_annotations}개")
            except Exception as e:
                QMessageBox.critical(self, "오류", f"ROI 로드 실패:\n{str(e)}")
    
    def on_annotation_added(self, annotation):
        """Annotation 추가 시 호출"""
        num_annotations = len(self.wsi_viewer.get_annotations())
        self.statusbar.showMessage(f"ROI 추가됨: {annotation.name} (총 {num_annotations}개)")
        
        # Annotation 패널 업데이트
        self.annotation_panel.add_annotation(annotation)
        
        # Polygon 그리기 완료 후 자동으로 토글 해제
        if self.actionDrawPolygon.isChecked():
            self.actionDrawPolygon.setChecked(False)
    
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
        self.statusbar.showMessage("ROI 그리기 취소됨")
    
    def closeEvent(self, event):
        """윈도우 닫기 시 리소스 정리"""
        self.wsi_viewer.close()
        
        # AI 작업 취소
        self.tissue_segmentation.cancel()
        self.tissue_classification.cancel()
        self.lesion_detection.cancel()
        
        event.accept()
