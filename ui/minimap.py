"""
미니맵 위젯 (ASAP MiniMap 참고)
전체 WSI의 작은 오버뷰를 표시하고 현재 보이는 영역을 사각형으로 표시
"""

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QRect, QRectF, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QPixmap


class MiniMap(QWidget):
    """미니맵 위젯 (ASAP MiniMap 참고)"""
    
    # 미니맵에서 클릭 시 해당 위치로 이동하는 시그널
    positionClicked = pyqtSignal(float, float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(250, 250)
        self.setMaximumSize(350, 350)
        
        # 배경 설정 (반투명)
        self.setStyleSheet("""
            background-color: rgba(30, 30, 30, 220);
            border: 2px solid #888;
            border-radius: 5px;
        """)
        
        # 썸네일 이미지
        self.thumbnail = None
        self.thumbnail_rect = QRect()
        
        # 현재 보이는 영역 (FOV - Field of View)
        self.fov_rect = QRectF()
        
        # 이미지 크기
        self.image_dimensions = (1, 1)
        
        # 캐시된 타일 정보 (타일 좌표, 레벨)
        self.cached_tiles = []  # [(tx, ty, level), ...]
        self.tile_size = 512
    
    def set_thumbnail(self, pixmap):
        """썸네일 이미지 설정"""
        if pixmap:
            self.thumbnail = pixmap
            self.calculate_thumbnail_rect()
            self.update()
    
    def calculate_thumbnail_rect(self):
        """썸네일 표시 위치 계산 (종횡비 유지)"""
        if not self.thumbnail:
            return
        
        widget_width = self.width()
        widget_height = self.height()
        thumb_width = self.thumbnail.width()
        thumb_height = self.thumbnail.height()
        
        # 종횡비 계산
        widget_ratio = widget_width / widget_height
        thumb_ratio = thumb_width / thumb_height
        
        if thumb_ratio > widget_ratio:
            # 썸네일이 더 넓음 - 너비 맞춤
            display_width = widget_width - 10
            display_height = int(display_width / thumb_ratio)
        else:
            # 썸네일이 더 높음 - 높이 맞춤
            display_height = widget_height - 10
            display_width = int(display_height * thumb_ratio)
        
        # 중앙 정렬
        x = (widget_width - display_width) // 2
        y = (widget_height - display_height) // 2
        
        self.thumbnail_rect = QRect(x, y, display_width, display_height)
    
    def set_image_dimensions(self, width, height):
        """원본 이미지 크기 설정"""
        self.image_dimensions = (width, height)
    
    def update_field_of_view(self, fov_rect):
        """현재 보이는 영역 업데이트"""
        self.fov_rect = fov_rect
        self.update()
    
    def update_cached_tiles(self, cached_tiles):
        """캐시된 타일 정보 업데이트"""
        self.cached_tiles = cached_tiles
        self.update()
    
    def paintEvent(self, event):
        """위젯 그리기"""
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 썸네일 그리기
        if self.thumbnail and not self.thumbnail_rect.isEmpty():
            painter.drawPixmap(self.thumbnail_rect, self.thumbnail)
            
            # 캐시된 타일 시각화
            self.draw_cached_tiles(painter)
            
            # FOV 사각형 그리기
            if not self.fov_rect.isEmpty():
                self.draw_fov_rectangle(painter)
    
    def draw_cached_tiles(self, painter):
        """캐시된 타일을 미니맵에 표시 - 레벨별 명확한 색상 구분"""
        if self.thumbnail_rect.isEmpty() or self.image_dimensions[0] <= 0:
            return
        
        img_width, img_height = self.image_dimensions
        
        # 레벨별 명확한 대비 색상 (불투명도 높임)
        level_colors = [
            QColor(0, 100, 255, 200),      # 레벨 0 (최고해상도): 진한 파란색
            QColor(255, 100, 0, 180),      # 레벨 1: 진한 주황색
            QColor(0, 255, 0, 160),        # 레벨 2: 밝은 초록색
            QColor(255, 255, 0, 140),      # 레벨 3+ (저해상도): 노란색
        ]
        
        # 레벨별로 그룹화하여 낮은 레벨(저해상도)부터 그리기
        tiles_by_level = {0: [], 1: [], 2: [], 3: []}
        for tx, ty, level, downsample in self.cached_tiles:
            level_key = min(level, 3)
            tiles_by_level[level_key].append((tx, ty, level, downsample))
        
        # 낮은 레벨(3, 2, 1)부터 그려서 높은 레벨(0)이 위에 오도록
        for level_key in [3, 2, 1, 0]:
            color = level_colors[level_key]
            for tx, ty, level, downsample in tiles_by_level[level_key]:
                # 타일의 실제 좌표 (레벨 0 기준)
                tile_x_level0 = tx * self.tile_size * downsample
                tile_y_level0 = ty * self.tile_size * downsample
                tile_w_level0 = self.tile_size * downsample
                tile_h_level0 = self.tile_size * downsample
                
                # 미니맵 좌표로 변환
                scale_x = self.thumbnail_rect.width() / img_width
                scale_y = self.thumbnail_rect.height() / img_height
                
                mini_x = self.thumbnail_rect.x() + tile_x_level0 * scale_x
                mini_y = self.thumbnail_rect.y() + tile_y_level0 * scale_y
                mini_w = tile_w_level0 * scale_x
                mini_h = tile_h_level0 * scale_y
                
                # 타일 사각형 채우기
                painter.fillRect(int(mini_x), int(mini_y), int(mini_w), int(mini_h), color)
                
                # 모든 레벨에 얇은 검은 테두리 추가 (타일 구분)
                painter.setPen(QPen(QColor(0, 0, 0, 100), 1))
                painter.drawRect(int(mini_x), int(mini_y), int(mini_w), int(mini_h))
                

    
    def draw_fov_rectangle(self, painter):
        """현재 보이는 영역을 사각형으로 표시"""
        if self.thumbnail_rect.isEmpty() or self.image_dimensions[0] <= 0:
            return
        
        # 이미지 좌표를 미니맵 좌표로 변환
        img_width, img_height = self.image_dimensions
        thumb_rect = self.thumbnail_rect
        
        # FOV를 썸네일 좌표계로 변환
        scale_x = thumb_rect.width() / img_width
        scale_y = thumb_rect.height() / img_height
        
        fov_x = thumb_rect.x() + self.fov_rect.x() * scale_x
        fov_y = thumb_rect.y() + self.fov_rect.y() * scale_y
        fov_w = self.fov_rect.width() * scale_x
        fov_h = self.fov_rect.height() * scale_y
        
        # 사각형 그리기
        pen = QPen(QColor(255, 0, 0, 200))
        pen.setWidth(2)
        painter.setPen(pen)
        
        # 반투명 빨간색 테두리
        painter.setBrush(QBrush(QColor(255, 0, 0, 50)))
        painter.drawRect(int(fov_x), int(fov_y), int(fov_w), int(fov_h))
    
    def mousePressEvent(self, event):
        """마우스 클릭 시 해당 위치로 이동"""
        if event.button() == Qt.LeftButton and not self.thumbnail_rect.isEmpty():
            # 클릭 위치를 이미지 좌표로 변환
            click_pos = event.pos()
            
            if self.thumbnail_rect.contains(click_pos):
                # 썸네일 내부 클릭
                img_width, img_height = self.image_dimensions
                thumb_rect = self.thumbnail_rect
                
                # 상대 좌표 계산
                rel_x = (click_pos.x() - thumb_rect.x()) / thumb_rect.width()
                rel_y = (click_pos.y() - thumb_rect.y()) / thumb_rect.height()
                
                # 이미지 좌표로 변환
                img_x = rel_x * img_width
                img_y = rel_y * img_height
                
                # 시그널 발생
                self.positionClicked.emit(img_x, img_y)
    
    def resizeEvent(self, event):
        """위젯 크기 변경 시"""
        super().resizeEvent(event)
        self.calculate_thumbnail_rect()
