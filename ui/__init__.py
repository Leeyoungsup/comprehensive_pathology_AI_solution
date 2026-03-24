"""
UI Module
Viewer and UI components
"""

from .viewer import PathologyViewer
from .wsi_view_widget import WSIViewWidget
from .minimap import MiniMap

# Backward compatibility alias
WSIViewer = WSIViewWidget

__all__ = ['PathologyViewer', 'WSIViewWidget', 'WSIViewer', 'MiniMap']
