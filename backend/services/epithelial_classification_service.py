"""
Epithelial Classification Service

WSI segmentation과 cell detection을 조합하여
Epithelial cell을 조직 영역별로 재분류하는 서비스
"""

import torch


class EpithelialClassificationService:
    """
    Service layer for epithelial cell reclassification

    Provides business logic abstraction for:
    - Loading segmentation model
    - Running epithelial cell reclassification
    - Managing model lifecycle
    """

    def __init__(self):
        self.classifier = None
        self._model_loaded = False

    def _ensure_classifier(self):
        """Lazy initialization of classifier"""
        if self.classifier is None:
            from ai.epithelial_classifier import EpithelialClassifier
            self.classifier = EpithelialClassifier()
        return self.classifier

    def load_model(self, model_path=None):
        """
        Load segmentation model

        Args:
            model_path: Optional path to segmentation model
                       (default: ./model/HnE_ST_segmentation.pt)

        Returns:
            (bool, str): (success, message)
        """
        classifier = self._ensure_classifier()

        try:
            if classifier.load_segmentation_model(model_path):
                self._model_loaded = True
                return True, "Segmentation 모델 로드 완료"
            else:
                return False, "Segmentation 모델 로드 실패"
        except Exception as e:
            return False, f"Segmentation 모델 로드 실패: {str(e)}"

    def is_model_loaded(self):
        """Check if segmentation model is loaded"""
        return self._model_loaded

    def run_classification(self, slide, detection_cells):
        """
        Run epithelial cell reclassification

        Args:
            slide: OpenSlide object
            detection_cells: List of detected cells from YOLOv11

        Raises:
            RuntimeError: If model is not loaded
        """
        classifier = self._ensure_classifier()

        if not self.is_model_loaded():
            raise RuntimeError("Segmentation 모델이 로드되지 않았습니다.")

        classifier.run_classification(slide, detection_cells)

    def get_classifier(self):
        """
        Get classifier instance for signal connections

        Returns:
            EpithelialClassifier instance
        """
        return self._ensure_classifier()

    def cancel(self):
        """Cancel running classification operation"""
        if self.classifier is not None:
            self.classifier.cancel()

    def unload_model(self):
        """Unload model and free GPU memory"""
        if self.classifier is not None:
            self.classifier.unload_model()
            self._model_loaded = False

        # Force garbage collection
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()

    def get_model_info(self):
        """
        Get information about the segmentation model

        Returns:
            dict: Model information (loaded status, device, etc.)
        """
        info = {
            'loaded': self._model_loaded,
            'device': 'cuda' if torch.cuda.is_available() else 'cpu',
        }

        if self.classifier and self.classifier.segmentation_model:
            model = self.classifier.segmentation_model
            info.update({
                'model_mpp': model.model_mpp,
                'output_mpp': model.output_mpp,
                'num_classes': model.num_classes,
                'class_names': model.class_names,
            })

        return info
