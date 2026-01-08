"""
UI 모듈
뷰어 및 UI 컴포넌트
"""

from .viewer import PathologyViewer
from .wsi_view_widget import WSIViewWidget
from .minimap import MiniMap

# Backward compatibility alias
WSIViewer = WSIViewWidget

__all__ = ['PathologyViewer', 'WSIViewWidget', 'WSIViewer', 'MiniMap']
