"""
병리 이미지 뷰어 메인 윈도우
리팩토링된 간소화 버전 - UI 구성 및 이벤트 처리만 담당
"""

from PyQt5 import uic
from PyQt5.QtWidgets import QMainWindow, QFileDialog, QVBoxLayout, QHBoxLayout, QMessageBox
from PyQt5.QtCore import Qt
from pathlib import Path
import os
import sys

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from ui.wsi_view_widget import WSIViewWidget
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
        
        # 새로운 WSIViewWidget 생성 및 추가
        main_layout = QHBoxLayout()
        self.wsi_viewer = WSIViewWidget(parent)
        main_layout.addWidget(self.wsi_viewer, stretch=1)
        
        # 레이아웃 적용
        layout.insertLayout(0, main_layout)
        
        # 시그널 연결
        self.wsi_viewer.fieldOfViewChanged.connect(self.on_field_of_view_changed)
    
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
    
    def closeEvent(self, event):
        """윈도우 닫기 시 리소스 정리"""
        self.wsi_viewer.close()
        
        # AI 작업 취소
        self.tissue_segmentation.cancel()
        self.tissue_classification.cancel()
        self.lesion_detection.cancel()
        
        event.accept()
