"""
Annotation List Panel
Based on ASAP annotation panel
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QPushButton, QHeaderView, QAbstractItemView, QLabel, QSizePolicy,
                             QColorDialog, QInputDialog)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QKeySequence
import sys
from pathlib import Path

# Add project root
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.annotation import Annotation, AnnotationList


class AnnotationPanel(QWidget):
    """
    Panel for displaying and managing annotation list
    Based on ASAP Annotation Panel
    """

    # Signal definitions
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
        """Set up UI"""
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        # Title label
        title_label = QWidget()
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel("Annotations")
        label.setStyleSheet("font-weight: bold; font-size: 12px;")
        title_layout.addWidget(label)
        title_label.setLayout(title_layout)
        layout.addWidget(title_label)

        # Annotation table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Color", "Name", "Type"])

        # Table settings
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(2, 80)
        self.table.setMaximumHeight(250)  # Max height limit for scrollbar
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)  # Horizontal expansion

        # Stylesheet: preserve Color column background on selection
        self.table.setStyleSheet("""
            QTableWidget {
                gridline-color: #d0d0d0;
            }
            QTableWidget::item:selected {
                background-color: rgba(51, 153, 255, 80);
                color: black;
            }
        """)

        # Table signal connections
        self.table.itemSelectionChanged.connect(self.on_table_selection_changed)
        self.table.itemDoubleClicked.connect(self.on_item_double_clicked)

        layout.addWidget(self.table)

        # Button layout
        button_layout = QHBoxLayout()

        # Delete button
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.clicked.connect(self.on_delete_clicked)
        self.btn_delete.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        button_layout.addWidget(self.btn_delete)

        # Clear button
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self.on_clear_clicked)
        self.btn_clear.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        button_layout.addWidget(self.btn_clear)

        # Load button
        self.btn_load = QPushButton("Load")
        self.btn_load.clicked.connect(self.on_load_clicked)
        self.btn_load.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        button_layout.addWidget(self.btn_load)

        # Save button
        self.btn_save = QPushButton("Save")
        self.btn_save.clicked.connect(self.on_save_clicked)
        self.btn_save.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        button_layout.addWidget(self.btn_save)

        layout.addLayout(button_layout)

        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)  # Match horizontal size with other widgets

    def set_annotation_list(self, annotation_list: AnnotationList):
        """Set annotation list"""
        self.annotation_list = annotation_list
        self.refresh_table()

    def refresh_table(self):
        """Refresh table"""
        if not self.annotation_list:
            return

        # Delete existing rows
        self.table.setRowCount(0)

        # Add annotations
        for i, annotation in enumerate(self.annotation_list.annotations):
            self.add_annotation_row(i, annotation)

    def add_annotation_row(self, row: int, annotation: Annotation):
        """Add an annotation row to the table"""
        self.table.insertRow(row)

        # Color column - not selectable (always show color), double-click allowed
        color_item = QTableWidgetItem()
        color = QColor(*annotation.color)
        color_item.setBackground(color)
        color_item.setForeground(QColor(0, 0, 0, 0))  # Transparent text
        color_item.setText("")
        color_item.setFlags(color_item.flags() & ~Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.table.setItem(row, 0, color_item)

        # Name column
        name_item = QTableWidgetItem(annotation.name)
        self.table.setItem(row, 1, name_item)

        # Type column
        type_item = QTableWidgetItem(annotation.type.value)
        self.table.setItem(row, 2, type_item)

        # Store annotation ID in row (as internal data)
        self.table.item(row, 0).setData(Qt.UserRole, annotation.id)

    def add_annotation(self, annotation: Annotation):
        """Add new annotation: scroll to and select the new row after adding"""
        if not self.annotation_list:
            return

        row = self.table.rowCount()
        self.add_annotation_row(row, annotation)

        # Scroll to and select the newly added row
        item = self.table.item(row, 0) or self.table.item(row, 1)
        if item:
            # Scroll to center position
            self.table.scrollToItem(item, QAbstractItemView.PositionAtCenter)
            # Select row - this triggers selection signal for viewer synchronization
            self.table.selectRow(row)

    def remove_annotation(self, annotation: Annotation):
        """Remove annotation"""
        # Find and remove the corresponding row in table
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == annotation.id:
                self.table.removeRow(row)
                break

    def clear_annotations(self):
        """Remove all annotations"""
        self.table.setRowCount(0)

    def on_table_selection_changed(self):
        """Table selection changed"""
        if not self.annotation_list:
            return

        selected_rows = self.table.selectedItems()
        if not selected_rows:
            return

        # Get annotation ID of selected row
        row = selected_rows[0].row()
        annotation_id = self.table.item(row, 0).data(Qt.UserRole)

        # Find annotation
        for annotation in self.annotation_list.annotations:
            if annotation.id == annotation_id:
                self.annotationSelected.emit(annotation)
                break

    def select_annotation(self, annotation: Annotation):
        """Select a specific annotation"""
        # Find and select the corresponding row in table
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == annotation.id:
                self.table.selectRow(row)
                break

    def on_item_double_clicked(self, item: QTableWidgetItem):
        """Handle table item double-click"""
        if not self.annotation_list:
            return

        row = item.row()
        col = item.column()
        annotation_id = self.table.item(row, 0).data(Qt.UserRole)

        # Find annotation
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
        # Column 0 (Color): color selection dialog
        if col == 0:
            current_color = QColor(*annotation.color)
            new_color = QColorDialog.getColor(current_color, self, "Select Color")

            if new_color.isValid():
                # Update annotation color
                annotation.color = (new_color.red(), new_color.green(), new_color.blue())

                # Update table color
                self.table.item(row, 0).setBackground(new_color)

                # Update graphics item in viewer (handled by parent widget)
                self.update_annotation_graphics(annotation)

        # Column 1 (Name): rename dialog
        elif col == 1:
            new_name, ok = QInputDialog.getText(
                self,
                "Rename",
                "Enter new name:",
                text=annotation.name
            )

            if ok and new_name:
                # Update annotation name
                annotation.name = new_name

                # Update table name
                self.table.item(row, 1).setText(new_name)

        # On double-click (any column): navigate to the ROI position in viewer
        # (This action is always performed regardless of edit/color selection)
        # Select the row and request the parent window's WSI viewer to navigate


    def update_annotation_graphics(self, annotation: Annotation):
        """Update annotation graphics item (on color change)"""
        # Access viewer through parent window to update
        parent = self.parent()
        while parent:
            if hasattr(parent, 'wsi_viewer'):
                viewer = parent.wsi_viewer
                if annotation.id in viewer.annotation_items:
                    viewer.annotation_items[annotation.id].update_style()
                break
            parent = parent.parent()

    def on_delete_clicked(self):
        """Delete button clicked - delete selected annotation"""
        selected_rows = self.table.selectedItems()
        if not selected_rows or not self.annotation_list:
            return

        # Get annotation ID of selected row
        row = selected_rows[0].row()
        annotation_id = self.table.item(row, 0).data(Qt.UserRole)

        # Find annotation
        for annotation in self.annotation_list.annotations:
            if annotation.id == annotation_id:
                self.annotationDeleted.emit(annotation)
                break

    def on_clear_clicked(self):
        """Clear button clicked"""
        self.clearAllRequested.emit()

    def on_save_clicked(self):
        """Save button clicked"""
        self.saveRequested.emit()

    def on_load_clicked(self):
        """Load button clicked"""
        self.loadRequested.emit()

    def keyPressEvent(self, event):
        """Key event handler - delete selected ROI with Delete key"""
        if event.key() == Qt.Key_Delete:
            self.on_delete_clicked()
        else:
            super().keyPressEvent(event)
