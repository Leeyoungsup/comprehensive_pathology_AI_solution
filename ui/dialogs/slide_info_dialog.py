"""
슬라이드 정보 다이얼로그
WSI 파일의 상세 정보를 표시하는 다이얼로그
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                              QLineEdit, QTextEdit, QPushButton, QGroupBox, 
                              QFormLayout)
from PyQt5.QtCore import Qt


class SlideInfoDialog(QDialog):
    """슬라이드 정보를 표시하는 다이얼로그"""
    
    def __init__(self, slide_info, parent=None):
        """
        Args:
            slide_info: 슬라이드 정보 딕셔너리
            parent: 부모 위젯
        """
        super().__init__(parent)
        self.slide_info = slide_info
        self.init_ui()
    
    def init_ui(self):
        """UI 초기화"""
        self.setWindowTitle("슬라이드 정보")
        self.setMinimumWidth(600)
        
        main_layout = QVBoxLayout(self)
        
        # 기본 정보 그룹
        basic_group = self.create_basic_info_group()
        main_layout.addWidget(basic_group)
        
        # 크기 정보 그룹
        size_group = self.create_size_info_group()
        main_layout.addWidget(size_group)
        
        # 레벨 정보 그룹
        level_group = self.create_level_info_group()
        main_layout.addWidget(level_group)
        
        # 닫기 버튼
        close_button = QPushButton("닫기")
        close_button.clicked.connect(self.accept)
        main_layout.addWidget(close_button)
    
    def create_basic_info_group(self):
        """기본 정보 그룹 생성"""
        group = QGroupBox("기본 정보")
        layout = QFormLayout()
        
        # 파일명
        filename_edit = QLineEdit(self.slide_info.get('filename', 'Unknown'))
        filename_edit.setReadOnly(True)
        layout.addRow("파일명:", filename_edit)
        
        # 벤더
        vendor_edit = QLineEdit(self.slide_info.get('vendor', 'Unknown'))
        vendor_edit.setReadOnly(True)
        layout.addRow("벤더:", vendor_edit)
        
        # 배율
        objective = self.slide_info.get('objective_power', 'Unknown')
        objective_edit = QLineEdit(f"{objective}x")
        objective_edit.setReadOnly(True)
        layout.addRow("배율:", objective_edit)
        
        group.setLayout(layout)
        return group
    
    def create_size_info_group(self):
        """크기 정보 그룹 생성"""
        group = QGroupBox("크기 정보")
        layout = QFormLayout()
        
        # 픽셀 크기
        dimensions = self.slide_info.get('dimensions', (0, 0))
        dimensions_edit = QLineEdit(f"{dimensions[0]} x {dimensions[1]} pixels")
        dimensions_edit.setReadOnly(True)
        layout.addRow("픽셀 크기 (Level 0):", dimensions_edit)
        
        # MPP 정보
        mpp_x = self.slide_info.get('mpp_x')
        mpp_y = self.slide_info.get('mpp_y')
        if mpp_x and mpp_y:
            mpp_edit = QLineEdit(f"{mpp_x:.4f} x {mpp_y:.4f} µm/pixel")
            mpp_edit.setReadOnly(True)
            layout.addRow("MPP:", mpp_edit)
            
            # 물리적 크기
            width_mm = self.slide_info.get('physical_width_mm')
            height_mm = self.slide_info.get('physical_height_mm')
            if width_mm and height_mm:
                physical_edit = QLineEdit(f"{width_mm:.2f} x {height_mm:.2f} mm")
                physical_edit.setReadOnly(True)
                layout.addRow("물리적 크기:", physical_edit)
        
        group.setLayout(layout)
        return group
    
    def create_level_info_group(self):
        """레벨 정보 그룹 생성"""
        group = QGroupBox("레벨 정보")
        layout = QVBoxLayout()
        
        # 레벨 수
        level_count = self.slide_info.get('level_count', 0)
        level_count_label = QLabel(f"총 레벨 수: {level_count}")
        layout.addWidget(level_count_label)
        
        # 레벨 상세 정보
        level_text = QTextEdit()
        level_text.setReadOnly(True)
        level_text.setMaximumHeight(150)
        
        level_info_str = ""
        level_dimensions = self.slide_info.get('level_dimensions', [])
        level_downsamples = self.slide_info.get('level_downsamples', [])
        
        for i, (dim, downsample) in enumerate(zip(level_dimensions, level_downsamples)):
            level_info_str += f"Level {i}: {dim[0]} x {dim[1]} pixels (downsample: {downsample:.2f})\n"
        
        level_text.setPlainText(level_info_str)
        layout.addWidget(level_text)
        
        group.setLayout(layout)
        return group


def show_slide_info_dialog(tile_manager, parent=None):
    """
    슬라이드 정보 다이얼로그 표시 헬퍼 함수
    
    Args:
        tile_manager: WSITileManager 객체
        parent: 부모 위젯
    
    Returns:
        QDialog.Accepted 또는 QDialog.Rejected
    """
    if not tile_manager:
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.information(parent, "정보", "먼저 이미지를 로드해주세요.")
        return None
    
    slide_info = tile_manager.get_slide_info()
    if not slide_info:
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning(parent, "오류", "슬라이드 정보를 가져올 수 없습니다.")
        return None
    
    dialog = SlideInfoDialog(slide_info, parent)
    return dialog.exec_()
