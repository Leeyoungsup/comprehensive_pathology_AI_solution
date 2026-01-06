"""
병리 이미지 뷰어 메인 윈도우
대용량 병리 이미지(WSI) 로드, 표시, 줌/패닝 기능 제공
"""

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QScrollArea,
    QToolBar, QStatusBar, QSplitter, QTextEdit, QSlider
)
from PyQt5.QtCore import Qt, QPoint, QRect, pyqtSignal
from PyQt5.QtGui import (
    QPixmap, QImage, QPainter, QWheelEvent, 
    QMouseEvent, QIcon
)
from PyQt5.QtWidgets import QAction
import numpy as np
import cv2
from pathlib import Path


class ImageViewer(QLabel):
    """이미지 표시 및 마우스 인터랙션을 처리하는 커스텀 위젯"""
    
    zoomChanged = pyqtSignal(float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(800, 600)
        self.setStyleSheet("background-color: #2b2b2b; border: 1px solid #555;")
        
        # 이미지 관련 속성
        self.original_image = None
        self.display_image = None
        self.zoom_level = 1.0
        self.min_zoom = 0.1
        self.max_zoom = 20.0
        
        # 패닝 관련 속성
        self.is_panning = False
        self.last_mouse_pos = QPoint()
        self.image_offset = QPoint(0, 0)
        
        # 마우스 추적 활성화
        self.setMouseTracking(True)
        
    def load_image(self, image_path):
        """이미지 로드 (OpenCV 사용)"""
        try:
            # OpenCV로 이미지 읽기
            img = cv2.imread(str(image_path))
            if img is None:
                return False
            
            # BGR to RGB 변환
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            self.original_image = img
            
            # 초기 줌 레벨 설정 (화면에 맞추기)
            self.fit_to_window()
            return True
            
        except Exception as e:
            print(f"이미지 로드 실패: {e}")
            return False
    
    def fit_to_window(self):
        """이미지를 윈도우 크기에 맞추기"""
        if self.original_image is None:
            return
        
        h, w = self.original_image.shape[:2]
        widget_w, widget_h = self.width(), self.height()
        
        # 화면에 맞는 줌 레벨 계산
        zoom_w = widget_w / w
        zoom_h = widget_h / h
        self.zoom_level = min(zoom_w, zoom_h) * 0.95
        
        self.image_offset = QPoint(0, 0)
        self.update_display()
    
    def set_zoom(self, zoom_level):
        """줌 레벨 설정"""
        self.zoom_level = max(self.min_zoom, min(self.max_zoom, zoom_level))
        self.update_display()
        self.zoomChanged.emit(self.zoom_level)
    
    def zoom_in(self):
        """줌 인"""
        self.set_zoom(self.zoom_level * 1.2)
    
    def zoom_out(self):
        """줌 아웃"""
        self.set_zoom(self.zoom_level / 1.2)
    
    def update_display(self):
        """현재 줌 레벨에 맞춰 이미지 업데이트"""
        if self.original_image is None:
            return
        
        h, w = self.original_image.shape[:2]
        new_w = int(w * self.zoom_level)
        new_h = int(h * self.zoom_level)
        
        # 이미지 리사이즈
        if self.zoom_level < 1.0:
            interpolation = cv2.INTER_AREA
        else:
            interpolation = cv2.INTER_LINEAR
        
        resized = cv2.resize(self.original_image, (new_w, new_h), interpolation=interpolation)
        
        # NumPy 배열을 QImage로 변환
        height, width, channel = resized.shape
        bytes_per_line = 3 * width
        q_image = QImage(resized.data, width, height, bytes_per_line, QImage.Format_RGB888)
        
        # QPixmap으로 변환하여 표시
        self.display_image = QPixmap.fromImage(q_image)
        self.setPixmap(self.display_image)
    
    def wheelEvent(self, event: QWheelEvent):
        """마우스 휠로 줌 인/아웃"""
        if self.original_image is None:
            return
        
        # 휠 방향에 따라 줌
        delta = event.angleDelta().y()
        if delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()
    
    def mousePressEvent(self, event: QMouseEvent):
        """마우스 버튼 누름 - 패닝 시작"""
        if event.button() == Qt.LeftButton:
            self.is_panning = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """마우스 이동 - 패닝"""
        if self.is_panning and self.original_image is not None:
            delta = event.pos() - self.last_mouse_pos
            self.image_offset += delta
            self.last_mouse_pos = event.pos()
            # 패닝 구현 (추가 개선 가능)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """마우스 버튼 놓음 - 패닝 종료"""
        if event.button() == Qt.LeftButton:
            self.is_panning = False
            self.setCursor(Qt.ArrowCursor)


class PathologyViewer(QMainWindow):
    """병리 이미지 뷰어 메인 윈도우"""
    
    def __init__(self):
        super().__init__()
        self.current_image_path = None
        self.init_ui()
        
    def init_ui(self):
        """UI 초기화"""
        self.setWindowTitle("Pathology AI Viewer")
        self.setGeometry(100, 100, 1400, 900)
        
        # 중앙 위젯
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 메인 레이아웃
        main_layout = QHBoxLayout(central_widget)
        
        # 스플리터로 좌우 분할
        splitter = QSplitter(Qt.Horizontal)
        
        # 왼쪽: 이미지 뷰어 영역
        left_widget = self.create_viewer_area()
        splitter.addWidget(left_widget)
        
        # 오른쪽: AI 분석 패널
        right_widget = self.create_ai_panel()
        splitter.addWidget(right_widget)
        
        # 스플리터 비율 설정 (70:30)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        
        main_layout.addWidget(splitter)
        
        # 툴바 생성
        self.create_toolbar()
        
        # 상태바 생성
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("준비됨")
        
    def create_viewer_area(self):
        """이미지 뷰어 영역 생성"""
        viewer_widget = QWidget()
        layout = QVBoxLayout(viewer_widget)
        
        # 이미지 뷰어
        self.image_viewer = ImageViewer()
        self.image_viewer.zoomChanged.connect(self.on_zoom_changed)
        layout.addWidget(self.image_viewer)
        
        # 하단 컨트롤 패널
        control_layout = QHBoxLayout()
        
        # 줌 슬라이더
        zoom_label = QLabel("줌:")
        control_layout.addWidget(zoom_label)
        
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setMinimum(10)  # 0.1x
        self.zoom_slider.setMaximum(2000)  # 20.0x
        self.zoom_slider.setValue(100)  # 1.0x
        self.zoom_slider.setMaximumWidth(200)
        self.zoom_slider.valueChanged.connect(self.on_slider_changed)
        control_layout.addWidget(self.zoom_slider)
        
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(60)
        control_layout.addWidget(self.zoom_label)
        
        control_layout.addStretch()
        
        # 이미지 정보 라벨
        self.info_label = QLabel("이미지 없음")
        control_layout.addWidget(self.info_label)
        
        layout.addLayout(control_layout)
        
        return viewer_widget
    
    def create_ai_panel(self):
        """AI 분석 패널 생성"""
        panel_widget = QWidget()
        layout = QVBoxLayout(panel_widget)
        
        # 패널 제목
        title = QLabel("AI 분석 패널")
        title.setStyleSheet("font-size: 14pt; font-weight: bold; padding: 5px;")
        layout.addWidget(title)
        
        # AI 모델 선택 버튼들
        model_layout = QVBoxLayout()
        
        self.btn_segmentation = QPushButton("조직 분할 (Segmentation)")
        self.btn_segmentation.clicked.connect(self.run_segmentation)
        model_layout.addWidget(self.btn_segmentation)
        
        self.btn_classification = QPushButton("암 분류 (Classification)")
        self.btn_classification.clicked.connect(self.run_classification)
        model_layout.addWidget(self.btn_classification)
        
        self.btn_detection = QPushButton("병변 검출 (Detection)")
        self.btn_detection.clicked.connect(self.run_detection)
        model_layout.addWidget(self.btn_detection)
        
        layout.addLayout(model_layout)
        
        # 분석 결과 표시 영역
        result_label = QLabel("분석 결과:")
        result_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(result_label)
        
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setPlaceholderText("AI 분석 결과가 여기에 표시됩니다...")
        layout.addWidget(self.result_text)
        
        # 분석 설정
        settings_label = QLabel("분석 설정:")
        settings_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(settings_label)
        
        # 설정 옵션들 (추후 확장)
        settings_text = QTextEdit()
        settings_text.setMaximumHeight(100)
        settings_text.setPlaceholderText("분석 파라미터 설정...")
        layout.addWidget(settings_text)
        
        layout.addStretch()
        
        return panel_widget
    
    def create_toolbar(self):
        """툴바 생성"""
        toolbar = QToolBar("메인 툴바")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        # 파일 열기
        open_action = QAction("이미지 열기", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_image)
        toolbar.addAction(open_action)
        
        toolbar.addSeparator()
        
        # 줌 컨트롤
        zoom_in_action = QAction("확대 (+)", self)
        zoom_in_action.setShortcut("Ctrl++")
        zoom_in_action.triggered.connect(self.image_viewer.zoom_in)
        toolbar.addAction(zoom_in_action)
        
        zoom_out_action = QAction("축소 (-)", self)
        zoom_out_action.setShortcut("Ctrl+-")
        zoom_out_action.triggered.connect(self.image_viewer.zoom_out)
        toolbar.addAction(zoom_out_action)
        
        fit_action = QAction("화면 맞춤", self)
        fit_action.setShortcut("Ctrl+0")
        fit_action.triggered.connect(self.image_viewer.fit_to_window)
        toolbar.addAction(fit_action)
        
        toolbar.addSeparator()
        
        # 저장
        save_action = QAction("결과 저장", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_results)
        toolbar.addAction(save_action)
    
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
        if self.image_viewer.load_image(file_path):
            self.current_image_path = file_path
            
            # 이미지 정보 업데이트
            if self.image_viewer.original_image is not None:
                h, w = self.image_viewer.original_image.shape[:2]
                file_name = Path(file_path).name
                self.info_label.setText(f"{file_name} | {w}x{h}px")
                self.status_bar.showMessage(f"이미지 로드 완료: {file_name}")
                self.result_text.clear()
        else:
            self.status_bar.showMessage("이미지 로드 실패")
    
    def on_zoom_changed(self, zoom_level):
        """줌 레벨 변경 시"""
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(int(zoom_level * 100))
        self.zoom_slider.blockSignals(False)
        self.zoom_label.setText(f"{int(zoom_level * 100)}%")
    
    def on_slider_changed(self, value):
        """슬라이더 값 변경 시"""
        zoom_level = value / 100.0
        self.image_viewer.set_zoom(zoom_level)
    
    def run_segmentation(self):
        """조직 분할 AI 실행 (추후 구현)"""
        if self.current_image_path is None:
            self.result_text.setText("먼저 이미지를 로드해주세요.")
            return
        
        self.result_text.setText("조직 분할 분석 실행 중...\n(AI 모델 통합 예정)")
        self.status_bar.showMessage("조직 분할 분석 실행 중...")
    
    def run_classification(self):
        """암 분류 AI 실행 (추후 구현)"""
        if self.current_image_path is None:
            self.result_text.setText("먼저 이미지를 로드해주세요.")
            return
        
        self.result_text.setText("암 분류 분석 실행 중...\n(AI 모델 통합 예정)")
        self.status_bar.showMessage("암 분류 분석 실행 중...")
    
    def run_detection(self):
        """병변 검출 AI 실행 (추후 구현)"""
        if self.current_image_path is None:
            self.result_text.setText("먼저 이미지를 로드해주세요.")
            return
        
        self.result_text.setText("병변 검출 분석 실행 중...\n(AI 모델 통합 예정)")
        self.status_bar.showMessage("병변 검출 분석 실행 중...")
    
    def save_results(self):
        """분석 결과 저장"""
        if self.current_image_path is None:
            self.status_bar.showMessage("저장할 내용이 없습니다.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "결과 저장",
            "",
            "Text Files (*.txt);;JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            # 결과 저장 로직 (추후 구현)
            self.status_bar.showMessage(f"결과 저장 완료: {file_path}")
