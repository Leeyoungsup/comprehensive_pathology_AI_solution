"""
Service layer
Service classes that separate UI from business logic
"""

from .detection_service import DetectionService
from .slide_service import SlideService
from .annotation_service import AnnotationService
from .epithelial_classification_service import EpithelialClassificationService

__all__ = [
    'DetectionService',
    'SlideService',
    'AnnotationService',
    'EpithelialClassificationService'
]
