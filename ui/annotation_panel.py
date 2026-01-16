"""
Annotation 목록 패널
ASAP의 annotation panel 참고
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
                             QTableWidgetItem, QPushButton, QHeaderView, QAbstractItemView, QLabel, QSizePolicy,
                             QColorDialog, QInputDialog)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QKeySequence
import sys
from pathlib import Path

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.annotation import Annotation, AnnotationList


class AnnotationPanel(QWidget):
    """
    Annotation 목록을 표시하고 관리하는 패널
    ASAP의 Annotation Panel 참고
    """
    
    # 시그널 정의
    annotationSelected = pyqtSignal(Annotation)
    annotationDeleted = pyqtSignal(Annotation)
    clearAllRequested = pyqtSignal()
    saveRequested = pyqtSignal()
    loadRequested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.annotation_list: AnnotationList = None
        self.setup_ui()
    
    def setup_ui(self):
        """UI 구성"""
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        
        # 제목 레이블
        title_label = QWidget()
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel("Annotations")
        label.setStyleSheet("font-weight: bold; font-size: 12px;")
        title_layout.addWidget(label)
        title_label.setLayout(title_layout)
        layout.addWidget(title_label)
        
        # Annotation 테이블
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Color", "Name", "Type"])
        
        # 테이블 설정
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(2, 80)
        self.table.setMaximumHeight(250)  # 최대 높이 제한으로 스크롤 생성
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)  # 가로 확장
        
        # 스타일시트 설정: 선택 시에도 Color 컬럼의 배경색 유지
        self.table.setStyleSheet("""
            QTableWidget {
                gridline-color: #d0d0d0;
            }
            QTableWidget::item:selected {
                background-color: rgba(51, 153, 255, 80);
                color: black;
            }
        """)
        
        # 테이블 시그널 연결
        self.table.itemSelectionChanged.connect(self.on_table_selection_changed)
        self.table.itemDoubleClicked.connect(self.on_item_double_clicked)
        
        layout.addWidget(self.table)
        
        # 버튼 레이아웃
        button_layout = QHBoxLayout()
        
        # Delete 버튼
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.clicked.connect(self.on_delete_clicked)
        self.btn_delete.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        button_layout.addWidget(self.btn_delete)
        
        # Clear 버튼
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self.on_clear_clicked)
        self.btn_clear.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        button_layout.addWidget(self.btn_clear)
        
        # Load 버튼
        self.btn_load = QPushButton("Load")
        self.btn_load.clicked.connect(self.on_load_clicked)
        self.btn_load.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        button_layout.addWidget(self.btn_load)
        
        # Save 버튼
        self.btn_save = QPushButton("Save")
        self.btn_save.clicked.connect(self.on_save_clicked)
        self.btn_save.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        button_layout.addWidget(self.btn_save)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)  # 다른 위젯과 가로 크기 맞춤
    
    def set_annotation_list(self, annotation_list: AnnotationList):
        """Annotation 리스트 설정"""
        self.annotation_list = annotation_list
        self.refresh_table()
    
    def refresh_table(self):
        """테이블 새로고침"""
        if not self.annotation_list:
            return
        
        # 기존 행 삭제
        self.table.setRowCount(0)
        
        # Annotation 추가
        for i, annotation in enumerate(self.annotation_list.annotations):
            self.add_annotation_row(i, annotation)
    
    def add_annotation_row(self, row: int, annotation: Annotation):
        """테이블에 annotation 행 추가"""
        self.table.insertRow(row)
        
        # Color 컬럼 - 선택 불가(항상 색상 보이게), 더블클릭은 허용
        color_item = QTableWidgetItem()
        color = QColor(*annotation.color)
        color_item.setBackground(color)
        color_item.setForeground(QColor(0, 0, 0, 0))  # 투명 텍스트
        color_item.setText("")
        color_item.setFlags(color_item.flags() & ~Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.table.setItem(row, 0, color_item)
        
        # Name 컬럼
        name_item = QTableWidgetItem(annotation.name)
        self.table.setItem(row, 1, name_item)
        
        # Type 컬럼
        type_item = QTableWidgetItem(annotation.type.value)
        self.table.setItem(row, 2, type_item)
        
        # 행에 annotation ID 저장 (내부 데이터로)
        self.table.item(row, 0).setData(Qt.UserRole, annotation.id)
    
    def add_annotation(self, annotation: Annotation):
        """새 annotation 추가: 추가 후 해당 행으로 스크롤하고 선택함"""
        if not self.annotation_list:
            return
        
        row = self.table.rowCount()
        self.add_annotation_row(row, annotation)
        
        # 새로 추가된 행이 보이도록 스크롤 및 선택
        item = self.table.item(row, 0) or self.table.item(row, 1)
        if item:
            # 가운데 위치로 스크롤
            self.table.scrollToItem(item, QAbstractItemView.PositionAtCenter)
            # 행 선택 - 이로써 선택 시그널이 발생하여 뷰어와 동기화됨
            self.table.selectRow(row)
    
    def remove_annotation(self, annotation: Annotation):
        """Annotation 제거"""
        # 테이블에서 해당 행 찾아서 제거
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == annotation.id:
                self.table.removeRow(row)
                break
    
    def clear_annotations(self):
        """모든 annotation 제거"""
        self.table.setRowCount(0)
    
    def on_table_selection_changed(self):
        """테이블 선택 변경"""
        if not self.annotation_list:
            return
        
        selected_rows = self.table.selectedItems()
        if not selected_rows:
            return
        
        # 선택된 행의 annotation ID 가져오기
        row = selected_rows[0].row()
        annotation_id = self.table.item(row, 0).data(Qt.UserRole)
        
        # Annotation 찾기
        for annotation in self.annotation_list.annotations:
            if annotation.id == annotation_id:
                self.annotationSelected.emit(annotation)
                break
    
    def select_annotation(self, annotation: Annotation):
        """특정 annotation 선택"""
        # 테이블에서 해당 행 찾아서 선택
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == annotation.id:
                self.table.selectRow(row)
                break
    
    def on_item_double_clicked(self, item: QTableWidgetItem):
        """테이블 아이템 더블클릭 처리"""
        if not self.annotation_list:
            return
        
        row = item.row()
        col = item.column()
        annotation_id = self.table.item(row, 0).data(Qt.UserRole)
        
        # Annotation 찾기
        annotation = None
        for ann in self.annotation_list.annotations:
            if ann.id == annotation_id:
                annotation = ann
                break
        
        if not annotation:
            return
        
        self.table.selectRow(row)
        parent = self.parent()
        while parent:
            if hasattr(parent, 'wsi_viewer'):
                viewer = parent.wsi_viewer
                try:
                    viewer.center_on_annotation(annotation)
                except Exception:
                    pass
                break
            parent = parent.parent()
        # 0번 컬럼(Color): 색상 선택 다이얼로그
        if col == 0:
            current_color = QColor(*annotation.color)
            new_color = QColorDialog.getColor(current_color, self, "색상 선택")
            
            if new_color.isValid():
                # Annotation 색상 업데이트
                annotation.color = (new_color.red(), new_color.green(), new_color.blue())
                
                # 테이블 색상 업데이트
                self.table.item(row, 0).setBackground(new_color)
                
                # 뷰어의 그래픽 아이템도 업데이트 (부모 위젯에서 처리)
                self.update_annotation_graphics(annotation)
        
        # 1번 컬럼(Name): 이름 변경 다이얼로그
        elif col == 1:
            new_name, ok = QInputDialog.getText(
                self, 
                "이름 변경", 
                "새 이름을 입력하세요:",
                text=annotation.name
            )
            
            if ok and new_name:
                # Annotation 이름 업데이트
                annotation.name = new_name
                
                # 테이블 이름 업데이트
                self.table.item(row, 1).setText(new_name)

        # 더블클릭(임의 컬럼) 시: 뷰어에서 해당 ROI 위치로 이동
        # (이 동작은 수정/색상 선택과 별개로 항상 수행)
        # 행을 선택 상태로 만들고, 부모 윈도우의 WSI 뷰어에게 이동 요청
        
    
    def update_annotation_graphics(self, annotation: Annotation):
        """Annotation 그래픽 아이템 업데이트 (색상 변경 시)"""
        # 부모 윈도우를 통해 뷰어에 접근하여 업데이트
        parent = self.parent()
        while parent:
            if hasattr(parent, 'wsi_viewer'):
                viewer = parent.wsi_viewer
                if annotation.id in viewer.annotation_items:
                    viewer.annotation_items[annotation.id].update_style()
                break
            parent = parent.parent()
    
    def on_delete_clicked(self):
        """Delete 버튼 클릭 - 선택된 annotation 삭제"""
        selected_rows = self.table.selectedItems()
        if not selected_rows or not self.annotation_list:
            return
        
        # 선택된 행의 annotation ID 가져오기
        row = selected_rows[0].row()
        annotation_id = self.table.item(row, 0).data(Qt.UserRole)
        
        # Annotation 찾기
        for annotation in self.annotation_list.annotations:
            if annotation.id == annotation_id:
                self.annotationDeleted.emit(annotation)
                break
    
    def on_clear_clicked(self):
        """Clear 버튼 클릭"""
        self.clearAllRequested.emit()
    
    def on_save_clicked(self):
        """Save 버튼 클릭"""
        self.saveRequested.emit()
    
    def on_load_clicked(self):
        """Load 버튼 클릭"""
        self.loadRequested.emit()
    
    def keyPressEvent(self, event):
        """키 이벤트 처리 - Delete 키로 선택된 ROI 삭제"""
        if event.key() == Qt.Key_Delete:
            self.on_delete_clicked()
        else:
            super().keyPressEvent(event)
