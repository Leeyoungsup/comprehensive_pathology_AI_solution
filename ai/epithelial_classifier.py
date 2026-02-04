"""
Epithelial Cell Reclassification using WSI Segmentation

조직 분할(segmentation) 결과와 세포 검출을 조합하여
Epithelial cell을 조직 영역별로 재분류하는 모듈

- Tumor-epithelial: Tumor 영역의 상피세포
- NT-epithelial: Non_Tumor 영역의 상피세포
- Stroma-epithelial: Stroma/Background 영역의 상피세포
"""

import os
import sys
from pathlib import Path
import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F
from PyQt5.QtCore import QThread, pyqtSignal, QObject
from tqdm import tqdm
import openslide
import warnings
warnings.filterwarnings('ignore')

# Segmentation model import
try:
    import segmentation_models_pytorch as smp
except ImportError:
    print("Warning: segmentation_models_pytorch not installed")
    print("Run: pip install segmentation-models-pytorch")
    smp = None

# Torchvision import
from torchvision.transforms import ToTensor


# ============================================================================
# Utility Functions (from notebook)
# ============================================================================

def create_gaussian_weight_mask(size, sigma=0.25):
    """
    Create a 2D Gaussian weight mask for smooth blending.
    Center has higher weight, edges have lower weight.
    """
    x = np.linspace(-1, 1, size)
    y = np.linspace(-1, 1, size)
    xx, yy = np.meshgrid(x, y)

    # Gaussian distribution
    gaussian = np.exp(-(xx**2 + yy**2) / (2 * sigma**2))

    # Normalize to [0, 1]
    gaussian = (gaussian - gaussian.min()) / (gaussian.max() - gaussian.min())

    return gaussian.astype(np.float32)


def get_wsi_mpp(slide):
    """Get MPP (microns per pixel) from WSI metadata."""
    try:
        mpp_x = float(slide.properties.get(openslide.PROPERTY_NAME_MPP_X, 0))
        mpp_y = float(slide.properties.get(openslide.PROPERTY_NAME_MPP_Y, 0))
        if mpp_x > 0 and mpp_y > 0:
            return (mpp_x + mpp_y) / 2
    except:
        pass

    # Try to get from NDPI specific properties
    try:
        if 'tiff.XResolution' in slide.properties:
            x_res = float(slide.properties['tiff.XResolution'])
            # Convert to mpp (assuming resolution is in pixels per cm)
            return 10000 / x_res
    except:
        pass

    # Default assumption for 40x objective
    print("Warning: Could not determine MPP, using default 0.25")
    return 0.25


def find_best_level(slide, target_mpp, base_mpp):
    """Find the best level to read from based on target MPP."""
    level_count = slide.level_count
    level_downsamples = slide.level_downsamples

    target_downsample = target_mpp / base_mpp

    best_level = 0
    best_diff = float('inf')

    for level in range(level_count):
        diff = abs(level_downsamples[level] - target_downsample)
        if level_downsamples[level] <= target_downsample and diff < best_diff:
            best_level = level
            best_diff = diff

    return best_level


# ============================================================================
# WSI Segmentation Model
# ============================================================================

class WSISegmentationModel:
    """
    Wrapper for DeepLabV3Plus segmentation model
    Handles model loading and inference on WSI slides using overlapping patches
    """

    def __init__(self, model_path=None, model_mpp=1.0, output_mpp=4.0, device='cuda'):
        """
        Args:
            model_path: Path to HnE_ST_segmentation.pt (default: ./model/HnE_ST_segmentation.pt)
            model_mpp: MPP at which model was trained (1.0)
            output_mpp: Desired output mask MPP (4.0)
            device: torch device
        """
        self.model_mpp = model_mpp
        self.output_mpp = output_mpp
        self.device = torch.device(device if torch.cuda.is_available() else "cpu")

        # Model setup
        self.num_classes = 4  # Background, Stroma, Non_Tumor, Tumor
        self.class_names = ["Background", "Stroma", "Non_Tumor", "Tumor"]

        # Model path
        if model_path is None:
            project_root = Path(__file__).parent.parent
            model_path = project_root / "model" / "HnE_ST_segmentation.pt"

        self.model_path = Path(model_path)
        self.model = None

        # Load model
        self._load_model()

    def _load_model(self):
        """Create and load DeepLabV3Plus model"""
        if smp is None:
            raise ImportError("segmentation_models_pytorch is not installed")

        # Create model
        self.model = smp.DeepLabV3Plus(
            encoder_name="efficientnet-b5",
            encoder_weights=None,
            in_channels=3,
            classes=self.num_classes,
        ).to(self.device)

        # Load weights
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Segmentation model not found: {self.model_path}\n"
                f"Please ensure the model file exists at this location."
            )

        checkpoint = torch.load(str(self.model_path), map_location=self.device)
        self.model.load_state_dict(checkpoint)
        self.model.eval()

        print(f"Segmentation model loaded from: {self.model_path}")

    def predict_wsi(self, slide, patch_size=512, overlap_ratio=0.3, batch_size=8, progress_callback=None, roi_bounds=None):
        """
        Predict on entire WSI or ROI region using overlapping patches with weighted blending

        Args:
            slide: OpenSlide object
            patch_size: Size of patches for model input (default: 512)
            overlap_ratio: Overlap ratio between adjacent patches (default: 0.4)
            batch_size: Batch size for inference (default: 8)
            progress_callback: Optional callback(progress_percent) for progress updates
            roi_bounds: Optional (x_min, y_min, x_max, y_max) tuple for ROI region at level 0
                       If None, processes entire WSI

        Returns:
            prediction_mask: numpy array (H, W) with class IDs at output_mpp resolution
            metadata: dict with dimensions, mpp info, etc.
        """
        if self.model is None:
            raise RuntimeError("Model not loaded")

        # Get WSI properties
        base_mpp = get_wsi_mpp(slide)
        wsi_w, wsi_h = slide.dimensions

        # Determine processing region
        if roi_bounds is not None:
            # Add buffer (10% on each side)
            x_min, y_min, x_max, y_max = roi_bounds
            buffer_x = int((x_max - x_min) * 0.1)
            buffer_y = int((y_max - y_min) * 0.1)
            
            x_min = max(0, x_min - buffer_x)
            y_min = max(0, y_min - buffer_y)
            x_max = min(wsi_w, x_max + buffer_x)
            y_max = min(wsi_h, y_max + buffer_y)
            
            region_w = x_max - x_min
            region_h = y_max - y_min
            region_offset_x = x_min
            region_offset_y = y_min
            
            print(f"ROI region: ({x_min}, {y_min}) to ({x_max}, {y_max})")
            print(f"ROI size: {region_w} x {region_h} (with 10% buffer)")
        else:
            # Process entire WSI
            region_w = wsi_w
            region_h = wsi_h
            region_offset_x = 0
            region_offset_y = 0
            print(f"Processing entire WSI: {wsi_w} x {wsi_h}")

        print(f"WSI base MPP: {base_mpp:.4f}")

        # Calculate scale factors
        read_scale = self.model_mpp / base_mpp  # Scale from base to model resolution
        output_scale = self.output_mpp / self.model_mpp  # Scale from model to output resolution

        # Patch size at level 0 (base resolution)
        patch_size_level0 = int(patch_size * read_scale)

        # Step size with overlap
        step_size = int(patch_size * (1 - overlap_ratio))
        step_size_level0 = int(step_size * read_scale)

        # Output dimensions at model_mpp resolution (for processing region)
        model_res_w = int(region_w / read_scale)
        model_res_h = int(region_h / read_scale)

        # Output dimensions at output_mpp resolution
        output_w = int(model_res_w / output_scale)
        output_h = int(model_res_h / output_scale)

        print(f"Model resolution size: {model_res_w} x {model_res_h}")
        print(f"Output mask size: {output_w} x {output_h}")
        print(f"Patch size at level 0: {patch_size_level0}")
        print(f"Step size at level 0: {step_size_level0}")

        # Find best level for reading
        read_level = find_best_level(slide, self.model_mpp, base_mpp)
        level_downsample = slide.level_downsamples[read_level]

        print(f"Reading from level {read_level} (downsample: {level_downsample:.2f})")

        # Initialize accumulators at model resolution
        prediction_sum = np.zeros((self.num_classes, model_res_h, model_res_w), dtype=np.float32)
        weight_sum = np.zeros((model_res_h, model_res_w), dtype=np.float32)

        # Create weight mask
        weight_mask = create_gaussian_weight_mask(patch_size, sigma=0.3)

        # Calculate number of patches (for processing region)
        n_patches_x = max(1, int(np.ceil((region_w - patch_size_level0) / step_size_level0)) + 1)
        n_patches_y = max(1, int(np.ceil((region_h - patch_size_level0) / step_size_level0)) + 1)
        total_patches = n_patches_x * n_patches_y

        print(f"Total patches: {n_patches_x} x {n_patches_y} = {total_patches}")

        # Generate patch coordinates (relative to processing region)
        patch_coords = []
        for y_idx in range(n_patches_y):
            for x_idx in range(n_patches_x):
                # Calculate position relative to region
                x_rel = min(x_idx * step_size_level0, region_w - patch_size_level0)
                y_rel = min(y_idx * step_size_level0, region_h - patch_size_level0)
                x_rel = max(0, x_rel)
                y_rel = max(0, y_rel)
                
                # Convert to absolute WSI coordinates
                x_abs = region_offset_x + x_rel
                y_abs = region_offset_y + y_rel
                
                patch_coords.append((x_abs, y_abs, x_rel, y_rel))  # (abs_x, abs_y, rel_x, rel_y)

        # Process patches in batches
        tf = ToTensor()
        processed_patches = 0

        for batch_start in range(0, len(patch_coords), batch_size):
            batch_coords = patch_coords[batch_start:batch_start + batch_size]
            batch_images = []
            valid_coords = []

            for (x_abs, y_abs, x_rel, y_rel) in batch_coords:
                # Read patch at the best level (using absolute coordinates)
                try:
                    patch = slide.read_region(
                        (x_abs, y_abs),
                        read_level,
                        (int(patch_size_level0 / level_downsample),
                         int(patch_size_level0 / level_downsample))
                    ).convert('RGB')

                    # Resize to model input size
                    patch = patch.resize((patch_size, patch_size), Image.BILINEAR)
                    patch_tensor = tf(patch)

                    # Check if patch is mostly background (white)
                    patch_array = np.array(patch)
                    white_ratio = np.mean(patch_array > 220)

                    if white_ratio < 0.9:  # Skip mostly white patches
                        batch_images.append(patch_tensor)
                        valid_coords.append((x_rel, y_rel))  # Store relative coordinates
                except Exception as e:
                    continue

            if len(batch_images) == 0:
                processed_patches += len(batch_coords)
                if progress_callback:
                    progress = int(100 * processed_patches / len(patch_coords))
                    progress_callback(progress)
                continue

            # Stack and predict
            batch_tensor = torch.stack(batch_images).to(self.device).float()

            with torch.no_grad():
                predictions = self.model(batch_tensor)
                predictions = F.softmax(predictions, dim=1)
                predictions = predictions.cpu().numpy()

            # Accumulate predictions with weights
            for i, (x_rel, y_rel) in enumerate(valid_coords):
                # Calculate position in model resolution (using relative coordinates)
                x_model = int(x_rel / read_scale)
                y_model = int(y_rel / read_scale)

                # Get the region to update
                x_end = min(x_model + patch_size, model_res_w)
                y_end = min(y_model + patch_size, model_res_h)

                patch_w = x_end - x_model
                patch_h = y_end - y_model

                if patch_w <= 0 or patch_h <= 0:
                    continue

                # Add weighted prediction
                for c in range(self.num_classes):
                    prediction_sum[c, y_model:y_end, x_model:x_end] += \
                        predictions[i, c, :patch_h, :patch_w] * weight_mask[:patch_h, :patch_w]

                weight_sum[y_model:y_end, x_model:x_end] += weight_mask[:patch_h, :patch_w]

            # Update progress
            processed_patches += len(batch_coords)
            if progress_callback:
                progress = int(100 * processed_patches / len(patch_coords))
                progress_callback(progress)

        # Normalize by weights
        weight_sum = np.maximum(weight_sum, 1e-6)  # Avoid division by zero
        for c in range(self.num_classes):
            prediction_sum[c] /= weight_sum

        # Get final prediction (argmax)
        prediction_model_res = np.argmax(prediction_sum, axis=0).astype(np.uint8)

        # Downsample to output resolution
        prediction_mask = Image.fromarray(prediction_model_res).resize(
            (output_w, output_h),
            Image.NEAREST
        )
        prediction_mask = np.array(prediction_mask)

        # Metadata
        metadata = {
            'wsi_dimensions': (wsi_w, wsi_h),
            'wsi_mpp': base_mpp,
            'model_mpp': self.model_mpp,
            'output_mpp': self.output_mpp,
            'mask_shape': prediction_mask.shape,
            'class_names': self.class_names,
            'region_offset': (region_offset_x, region_offset_y),  # ROI offset
        }

        return prediction_mask, metadata


# ============================================================================
# Epithelial Classification Worker (Background Thread)
# ============================================================================

class EpithelialClassificationWorker(QThread):
    """
    Background worker for epithelial cell reclassification
    Combines segmentation and detection results
    """

    finished = pyqtSignal(dict)  # Results with reclassified cells
    progress = pyqtSignal(int)   # 0-100
    status = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, slide, segmentation_model, detection_cells, device='cuda'):
        super().__init__()
        self.slide = slide
        self.segmentation_model = segmentation_model
        self.detection_cells = detection_cells  # Raw detection results
        self.device = device
        self.is_cancelled = False

    def run(self):
        """Execute the reclassification pipeline"""
        try:
            # Step 1: Run segmentation (0-50%)
            self.status.emit("WSI segmentation 실행 중...")

            def seg_progress_callback(p):
                if not self.is_cancelled:
                    self.progress.emit(int(p * 0.5))

            prediction_mask, seg_metadata = self.segmentation_model.predict_wsi(
                self.slide,
                progress_callback=seg_progress_callback
            )

            if self.is_cancelled:
                return

            self.status.emit("Epithelial cell 재분류 중...")
            self.progress.emit(60)

            # Step 2: Get WSI MPP
            wsi_mpp = get_wsi_mpp(self.slide)
            output_mpp = self.segmentation_model.output_mpp

            # Step 3: Reclassify epithelial cells (60-90%)
            reclassified_cells = self._reclassify_epithelial_cells(
                self.detection_cells,
                prediction_mask,
                wsi_mpp,
                output_mpp
            )

            if self.is_cancelled:
                return

            self.progress.emit(95)

            # Step 4: Count statistics
            stats = self._calculate_statistics(reclassified_cells)

            self.progress.emit(100)

            # Return results
            result = {
                'status': 'success',
                'cells': reclassified_cells,
                'num_cells': len(reclassified_cells),
                'class_counts': stats['class_counts'],
                'epithelial_breakdown': stats['epithelial_breakdown'],
                'segmentation_metadata': seg_metadata,
                'message': f'총 {len(reclassified_cells):,}개 세포 검출 및 재분류 완료'
            }

            self.finished.emit(result)

        except Exception as e:
            import traceback
            self.error.emit(f"재분류 중 오류: {str(e)}\n{traceback.format_exc()}")

    def _reclassify_epithelial_cells(self, cells, prediction_mask, wsi_mpp, output_mpp):
        """
        Reclassify epithelial cells based on segmentation mask

        Coordinate transformation:
        - Cells have (x, y) in level 0 coordinates
        - Mask is at output_mpp resolution
        - Transform: level0 → mask coordinates
        """
        reclassified = []
        scale_factor = wsi_mpp / output_mpp  # e.g., 0.25 / 8.0 = 0.03125

        mask_h, mask_w = prediction_mask.shape

        epithelial_count = 0
        for cell in cells:
            cell_copy = cell.copy()
            cls_id = cell['cls_id']

            # Only reclassify Epithelial cells (cls_id == 1)
            if cls_id == 1:
                epithelial_count += 1
                # Transform to mask coordinates
                mask_x = int(cell['x'] * scale_factor)
                mask_y = int(cell['y'] * scale_factor)

                # Boundary check
                if 0 <= mask_x < mask_w and 0 <= mask_y < mask_h:
                    seg_class = prediction_mask[mask_y, mask_x]

                    # Reclassify based on segmentation result
                    if seg_class == 3:  # Tumor region
                        cell_copy['cls_id'] = 6  # Tumor-epithelial
                        cell_copy['seg_region'] = 'Tumor'
                    elif seg_class == 2:  # Non_Tumor region
                        cell_copy['cls_id'] = 7  # NT-epithelial
                        cell_copy['seg_region'] = 'Non_Tumor'
                    else:  # Stroma (1) or Background (0)
                        cell_copy['cls_id'] = 8  # Stroma-epithelial
                        cell_copy['seg_region'] = 'Stroma/Background'
                else:
                    # Out of bounds - classify as Stroma-epithelial
                    cell_copy['cls_id'] = 8
                    cell_copy['seg_region'] = 'OutOfBounds'

            reclassified.append(cell_copy)

        print(f"Reclassified {epithelial_count} Epithelial cells")
        return reclassified

    def _calculate_statistics(self, cells):
        """Calculate class counts and epithelial breakdown"""
        from ai.detection import CLASS_NAMES

        class_counts = {name: 0 for name in CLASS_NAMES.values()}
        for cell in cells:
            cls_name = CLASS_NAMES.get(cell['cls_id'], 'Unknown')
            class_counts[cls_name] += 1

        # Epithelial breakdown
        epithelial_breakdown = {
            'total_epithelial': class_counts.get('Epithelial', 0),
            'tumor_epithelial': class_counts.get('Tumor-epithelial', 0),
            'nt_epithelial': class_counts.get('NT-epithelial', 0),
            'stroma_epithelial': class_counts.get('Stroma-epithelial', 0),
        }

        return {
            'class_counts': class_counts,
            'epithelial_breakdown': epithelial_breakdown
        }

    def cancel(self):
        """Cancel the operation"""
        self.is_cancelled = True


# ============================================================================
# Epithelial Classifier (Main Orchestrator)
# ============================================================================

class EpithelialClassifier(QObject):
    """
    Main orchestrator for epithelial cell reclassification
    Combines WSI segmentation with cell detection
    """

    classificationComplete = pyqtSignal(dict)
    classificationProgress = pyqtSignal(int)
    classificationStatus = pyqtSignal(str)
    classificationError = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.segmentation_model = None
        self.worker = None
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    def load_segmentation_model(self, model_path=None):
        """Load segmentation model"""
        try:
            self.segmentation_model = WSISegmentationModel(
                model_path=model_path,
                model_mpp=1.0,
                output_mpp=4.0,
                device=self.device
            )
            return True
        except Exception as e:
            self.classificationError.emit(f"Segmentation 모델 로드 실패: {str(e)}")
            return False

    def run_classification(self, slide, detection_cells):
        """
        Run epithelial cell reclassification

        Args:
            slide: OpenSlide object
            detection_cells: List of detected cells from YOLOv11
        """
        if self.segmentation_model is None:
            self.classificationError.emit("Segmentation 모델이 로드되지 않았습니다.")
            return

        if self.worker and self.worker.isRunning():
            self.classificationError.emit("이미 재분류 작업이 실행 중입니다.")
            return

        self.worker = EpithelialClassificationWorker(
            slide,
            self.segmentation_model,
            detection_cells,
            self.device
        )

        # Connect signals
        self.worker.finished.connect(self._on_finished)
        self.worker.progress.connect(self._on_progress)
        self.worker.status.connect(self._on_status)
        self.worker.error.connect(self._on_error)

        self.worker.start()

    def _on_finished(self, result):
        self.classificationComplete.emit(result)

    def _on_progress(self, progress):
        self.classificationProgress.emit(progress)

    def _on_status(self, status):
        self.classificationStatus.emit(status)

    def _on_error(self, error_msg):
        self.classificationError.emit(error_msg)

    def cancel(self):
        """Cancel running operation"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()

    def unload_model(self):
        """Unload model and free GPU memory"""
        if self.segmentation_model is not None:
            del self.segmentation_model.model
            del self.segmentation_model
            self.segmentation_model = None

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
