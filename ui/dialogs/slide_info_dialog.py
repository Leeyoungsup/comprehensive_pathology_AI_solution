"""
Slide Information Dialog
Dialog for displaying detailed information about WSI files
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                              QLineEdit, QTextEdit, QPushButton, QGroupBox,
                              QFormLayout)
from PyQt5.QtCore import Qt


class SlideInfoDialog(QDialog):
    """Dialog for displaying slide information"""

    def __init__(self, slide_info, parent=None):
        """
        Args:
            slide_info: Slide information dictionary
            parent: Parent widget
        """
        super().__init__(parent)
        self.slide_info = slide_info
        self.init_ui()

    def init_ui(self):
        """Initialize UI"""
        self.setWindowTitle("Slide Information")
        self.setMinimumWidth(600)

        main_layout = QVBoxLayout(self)

        # Basic info group
        basic_group = self.create_basic_info_group()
        main_layout.addWidget(basic_group)

        # Size info group
        size_group = self.create_size_info_group()
        main_layout.addWidget(size_group)

        # Level info group
        level_group = self.create_level_info_group()
        main_layout.addWidget(level_group)

        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        main_layout.addWidget(close_button)

    def create_basic_info_group(self):
        """Create basic info group"""
        group = QGroupBox("Basic Information")
        layout = QFormLayout()

        # Filename
        filename_edit = QLineEdit(self.slide_info.get('filename', 'Unknown'))
        filename_edit.setReadOnly(True)
        layout.addRow("Filename:", filename_edit)

        # Vendor
        vendor_edit = QLineEdit(self.slide_info.get('vendor', 'Unknown'))
        vendor_edit.setReadOnly(True)
        layout.addRow("Vendor:", vendor_edit)

        # Magnification
        objective = self.slide_info.get('objective_power', 'Unknown')
        objective_edit = QLineEdit(f"{objective}x")
        objective_edit.setReadOnly(True)
        layout.addRow("Magnification:", objective_edit)

        group.setLayout(layout)
        return group

    def create_size_info_group(self):
        """Create size info group"""
        group = QGroupBox("Size Information")
        layout = QFormLayout()

        # Pixel dimensions
        dimensions = self.slide_info.get('dimensions', (0, 0))
        dimensions_edit = QLineEdit(f"{dimensions[0]} x {dimensions[1]} pixels")
        dimensions_edit.setReadOnly(True)
        layout.addRow("Pixel Size (Level 0):", dimensions_edit)

        # MPP info
        mpp_x = self.slide_info.get('mpp_x')
        mpp_y = self.slide_info.get('mpp_y')
        if mpp_x and mpp_y:
            mpp_edit = QLineEdit(f"{mpp_x:.4f} x {mpp_y:.4f} \u00b5m/pixel")
            mpp_edit.setReadOnly(True)
            layout.addRow("MPP:", mpp_edit)

            # Physical dimensions
            width_mm = self.slide_info.get('physical_width_mm')
            height_mm = self.slide_info.get('physical_height_mm')
            if width_mm and height_mm:
                physical_edit = QLineEdit(f"{width_mm:.2f} x {height_mm:.2f} mm")
                physical_edit.setReadOnly(True)
                layout.addRow("Physical Size:", physical_edit)

        group.setLayout(layout)
        return group

    def create_level_info_group(self):
        """Create level info group"""
        group = QGroupBox("Level Information")
        layout = QVBoxLayout()

        # Level count
        level_count = self.slide_info.get('level_count', 0)
        level_count_label = QLabel(f"Total Levels: {level_count}")
        layout.addWidget(level_count_label)

        # Level detail info
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
    Helper function to display slide info dialog

    Args:
        tile_manager: WSITileManager object
        parent: Parent widget

    Returns:
        QDialog.Accepted or QDialog.Rejected
    """
    if not tile_manager:
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.information(parent, "Info", "Please load an image first.")
        return None

    slide_info = tile_manager.get_slide_info()
    if not slide_info:
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning(parent, "Error", "Unable to retrieve slide information.")
        return None

    dialog = SlideInfoDialog(slide_info, parent)
    dialog.setWindowModality(Qt.NonModal)
    dialog.show()
    return dialog
