"""
UI Dialog Module
"""

from .slide_info_dialog import SlideInfoDialog, show_slide_info_dialog
from .detection_visualization_dialog import DetectionVisualizationDialog, show_detection_visualization

__all__ = ['SlideInfoDialog', 'show_slide_info_dialog',
           'DetectionVisualizationDialog', 'show_detection_visualization']
