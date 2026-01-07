"""
UI 모듈
뷰어 및 UI 컴포넌트
"""

from .viewer import WSIViewer, PathologyViewer
from .minimap import MiniMap

__all__ = ['WSIViewer', 'PathologyViewer', 'MiniMap']
