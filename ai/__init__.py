"""
AI Module Initialization
Provides AI functionality for pathology image analysis
"""

from .segmentation import TissueSegmentation
from .classification import TissueClassification
from .detection import LesionDetection

__all__ = [
    'TissueSegmentation',
    'TissueClassification',
    'LesionDetection'
]
