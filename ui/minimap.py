"""
Minimap Widget (based on ASAP MiniMap)
Displays a small overview of the entire WSI and shows the currently visible area as a rectangle
"""

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QRect, QRectF, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QPixmap


class MiniMap(QWidget):
    """Minimap Widget (based on ASAP MiniMap)"""

    # Signal emitted when clicking on minimap to navigate to that position
    positionClicked = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(250, 250)
        self.setMaximumSize(350, 350)

        # Background settings (semi-transparent)
        self.setStyleSheet("""
            background-color: rgba(30, 30, 30, 220);
            border: 2px solid #888;
            border-radius: 5px;
        """)

        # Thumbnail image
        self.thumbnail = None
        self.thumbnail_rect = QRect()

        # Currently visible area (FOV - Field of View)
        self.fov_rect = QRectF()

        # Image dimensions
        self.image_dimensions = (1, 1)

        # Cached tile info (tile coordinates, level)
        self.cached_tiles = []  # [(tx, ty, level), ...]
        self.tile_size = 512

    def set_thumbnail(self, pixmap):
        """Set thumbnail image"""
        if pixmap:
            self.thumbnail = pixmap
            self.calculate_thumbnail_rect()
            self.update()

    def calculate_thumbnail_rect(self):
        """Calculate thumbnail display position (maintain aspect ratio)"""
        if not self.thumbnail:
            return

        widget_width = self.width()
        widget_height = self.height()
        thumb_width = self.thumbnail.width()
        thumb_height = self.thumbnail.height()

        # Calculate aspect ratio
        widget_ratio = widget_width / widget_height
        thumb_ratio = thumb_width / thumb_height

        if thumb_ratio > widget_ratio:
            # Thumbnail is wider - fit to width
            display_width = widget_width - 10
            display_height = int(display_width / thumb_ratio)
        else:
            # Thumbnail is taller - fit to height
            display_height = widget_height - 10
            display_width = int(display_height * thumb_ratio)

        # Center alignment
        x = (widget_width - display_width) // 2
        y = (widget_height - display_height) // 2

        self.thumbnail_rect = QRect(x, y, display_width, display_height)

    def set_image_dimensions(self, width, height):
        """Set original image dimensions"""
        self.image_dimensions = (width, height)

    def update_field_of_view(self, fov_rect):
        """Update currently visible area"""
        self.fov_rect = fov_rect
        self.update()

    def update_cached_tiles(self, cached_tiles):
        """Update cached tile info"""
        self.cached_tiles = cached_tiles
        self.update()

    def paintEvent(self, event):
        """Widget paint event"""
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw thumbnail
        if self.thumbnail and not self.thumbnail_rect.isEmpty():
            painter.drawPixmap(self.thumbnail_rect, self.thumbnail)

            # Draw FOV rectangle
            if not self.fov_rect.isEmpty():
                self.draw_fov_rectangle(painter)

    def draw_cached_tiles(self, painter):
        """Display cached tiles on minimap - distinct colors per level"""
        if self.thumbnail_rect.isEmpty() or self.image_dimensions[0] <= 0:
            return

        img_width, img_height = self.image_dimensions

        # Distinct high-contrast colors per level (higher opacity)
        level_colors = [
            QColor(0, 100, 255, 200),      # Level 0 (highest resolution): dark blue
            QColor(255, 100, 0, 180),      # Level 1: dark orange
            QColor(0, 255, 0, 160),        # Level 2: bright green
            QColor(255, 255, 0, 140),      # Level 3+ (low resolution): yellow
        ]

        # Group by level and draw from lowest level (low resolution) first
        tiles_by_level = {0: [], 1: [], 2: [], 3: []}
        for tx, ty, level, downsample in self.cached_tiles:
            level_key = min(level, 3)
            tiles_by_level[level_key].append((tx, ty, level, downsample))

        # Draw from low level (3, 2, 1) first so high level (0) is on top
        for level_key in [3, 2, 1, 0]:
            color = level_colors[level_key]
            for tx, ty, level, downsample in tiles_by_level[level_key]:
                # Tile actual coordinates (level 0 basis)
                tile_x_level0 = tx * self.tile_size * downsample
                tile_y_level0 = ty * self.tile_size * downsample
                tile_w_level0 = self.tile_size * downsample
                tile_h_level0 = self.tile_size * downsample

                # Convert to minimap coordinates
                scale_x = self.thumbnail_rect.width() / img_width
                scale_y = self.thumbnail_rect.height() / img_height

                mini_x = self.thumbnail_rect.x() + tile_x_level0 * scale_x
                mini_y = self.thumbnail_rect.y() + tile_y_level0 * scale_y
                mini_w = tile_w_level0 * scale_x
                mini_h = tile_h_level0 * scale_y

                # Fill tile rectangle
                painter.fillRect(int(mini_x), int(mini_y), int(mini_w), int(mini_h), color)

                # Add thin black border to all levels (tile separation)
                painter.setPen(QPen(QColor(0, 0, 0, 100), 1))
                painter.drawRect(int(mini_x), int(mini_y), int(mini_w), int(mini_h))



    def draw_fov_rectangle(self, painter):
        """Display currently visible area as a rectangle"""
        if self.thumbnail_rect.isEmpty() or self.image_dimensions[0] <= 0:
            return

        # Convert image coordinates to minimap coordinates
        img_width, img_height = self.image_dimensions
        thumb_rect = self.thumbnail_rect

        # Convert FOV to thumbnail coordinate system
        scale_x = thumb_rect.width() / img_width
        scale_y = thumb_rect.height() / img_height

        fov_x = thumb_rect.x() + self.fov_rect.x() * scale_x
        fov_y = thumb_rect.y() + self.fov_rect.y() * scale_y
        fov_w = self.fov_rect.width() * scale_x
        fov_h = self.fov_rect.height() * scale_y

        # Draw rectangle
        pen = QPen(QColor(255, 0, 0, 200))
        pen.setWidth(2)
        painter.setPen(pen)

        # Semi-transparent red border
        painter.setBrush(QBrush(QColor(255, 0, 0, 50)))
        painter.drawRect(int(fov_x), int(fov_y), int(fov_w), int(fov_h))

    def mousePressEvent(self, event):
        """Navigate to clicked position on mouse click"""
        if event.button() == Qt.LeftButton and not self.thumbnail_rect.isEmpty():
            self.handle_click(event.pos())
            self.is_dragging = True

    def mouseMoveEvent(self, event):
        """Navigate to position on mouse drag"""
        if hasattr(self, 'is_dragging') and self.is_dragging and not self.thumbnail_rect.isEmpty():
            self.handle_click(event.pos())

    def mouseReleaseEvent(self, event):
        """Mouse release"""
        if event.button() == Qt.LeftButton:
            self.is_dragging = False

    def handle_click(self, click_pos):
        """Handle click/drag position"""
        if self.thumbnail_rect.contains(click_pos):
            # Click inside thumbnail
            img_width, img_height = self.image_dimensions
            thumb_rect = self.thumbnail_rect

            # Calculate relative coordinates
            rel_x = (click_pos.x() - thumb_rect.x()) / thumb_rect.width()
            rel_y = (click_pos.y() - thumb_rect.y()) / thumb_rect.height()

            # Convert to image coordinates
            img_x = rel_x * img_width
            img_y = rel_y * img_height

            # Emit signal
            self.positionClicked.emit(img_x, img_y)

    def resizeEvent(self, event):
        """Handle widget resize"""
        super().resizeEvent(event)
        self.calculate_thumbnail_rect()
