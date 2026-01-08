"""
AI 모듈 초기화
병리 이미지 분석을 위한 AI 기능 제공
"""

from .segmentation import TissueSegmentation
from .classification import TissueClassification
from .detection import LesionDetection

__all__ = [
    'TissueSegmentation',
    'TissueClassification',
    'LesionDetection'
]
