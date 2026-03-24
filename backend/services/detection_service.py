"""
Cell detection service
Service layer handling detection-related business logic
"""

import openslide
from pathlib import Path
from typing import Optional, List, Dict, Any


class DetectionService:
    """Service handling cell detection business logic"""

    def __init__(self):
        self.detection_module = None
        self._model_loaded = False

    def _ensure_detection_module(self):
        """Detection module lazy initialization"""
        if self.detection_module is None:
            from ai.detection import CellDetection
            self.detection_module = CellDetection()
        return self.detection_module

    def load_model(self, model_path: Optional[str] = None) -> tuple[bool, str]:
        """
        Load AI model

        Args:
            model_path: Model file path (uses default path if None)

        Returns:
            (success, message)
        """
        try:
            detection = self._ensure_detection_module()

            if detection.load_model(model_path):
                self._model_loaded = True
                return True, "Model loaded successfully"
            else:
                return False, f"Failed to load model: {detection.default_model_path}"

        except Exception as e:
            return False, f"Error loading model: {str(e)}"

    def is_model_loaded(self) -> bool:
        """Check model load status"""
        if self.detection_module is None:
            return False
        return self.detection_module.is_model_loaded()

    def open_slide(self, slide_path: str) -> tuple[Optional[openslide.OpenSlide], str]:
        """
        Open WSI slide

        Args:
            slide_path: Slide file path

        Returns:
            (slide object, message)
        """
        try:
            slide = openslide.OpenSlide(slide_path)
            return slide, "Slide opened successfully"
        except Exception as e:
            return None, f"Failed to open slide: {str(e)}"

    def start_detection(self, slide: openslide.OpenSlide, roi_polygons: Optional[List] = None,
                        auto_classify_epithelial: bool = True, tissue_type: str = "Stomach",
                        image_path: Optional[str] = None):
        """
        Start detection

        Args:
            slide: OpenSlide object
            roi_polygons: ROI polygon list (entire area if None)
            auto_classify_epithelial: Whether to auto-reclassify epithelial cells (default: True)
            tissue_type: Tissue type (Breast, Stomach, Other)
            image_path: WSI file path (enables parallel I/O)
        """
        detection = self._ensure_detection_module()

        if not self.is_model_loaded():
            raise RuntimeError("Model is not loaded.")

        detection.run_detection(slide, roi_polygons,
                                auto_classify_epithelial=auto_classify_epithelial,
                                tissue_type=tissue_type,
                                image_path=image_path)

    def cancel_detection(self):
        """Cancel ongoing detection"""
        if self.detection_module is not None:
            self.detection_module.cancel()

    def unload_model(self):
        """Unload model and release GPU resources"""
        if self.detection_module is not None:
            self.detection_module.unload_model()
            self._model_loaded = False

    def get_detection_module(self):
        """Return detection module (for signal connections)"""
        return self._ensure_detection_module()

    def format_detection_result(self, result: Dict[str, Any]) -> str:
        """
        Format detection result as a display string for the user

        Args:
            result: Detection result dictionary

        Returns:
            Formatted result string
        """
        num_cells = result.get('num_cells', 0)
        message = f"Cell detection complete\n{result.get('message', '')}"

        # Display per-class counts
        class_counts = result.get('class_counts', {})
        total_from_classes = 0

        if class_counts:
            message += "\n\nDetection count by class:"
            for cls_name, count in class_counts.items():
                if count > 0:
                    message += f"\n  {cls_name}: {count:,}"
                    total_from_classes += count

            # Display totals
            message += f"\n\nClass subtotal: {total_from_classes:,}"
            message += f"\nTotal cells: {num_cells:,}"

            if total_from_classes != num_cells:
                message += f"\nCount mismatch detected!"

        return message

    def format_detection_progress(self, status: str) -> str:
        """
        Format detection progress as a display string for the user (with progress bar)

        Args:
            status: Status message

        Returns:
            Formatted progress string
        """
        if "patch" in status.lower() and "/" in status:
            try:
                parts = status.split("|")
                patch_info = parts[0].strip()

                # Extract progress
                nums = patch_info.split()[1].split("/")
                current = int(nums[0])
                total = int(nums[1])
                percent = (current / total) * 100

                # Text-based progress bar
                bar_length = 30
                filled = int(bar_length * current / total)
                bar = "\u2588" * filled + "\u2591" * (bar_length - filled)

                return f"""Cell detection in progress...

[Patch Processing]
{bar} {percent:.1f}%

{status}
"""
            except:
                pass

        return f"Cell detection in progress...\n\n{status}"
