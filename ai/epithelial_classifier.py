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
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F
from PyQt5.QtCore import QThread, pyqtSignal, QObject
from tqdm import tqdm
import openslide
import cv2
import warnings
warnings.filterwarnings('ignore')

_seg_thread_local = threading.local()
_autocast_enabled = torch.cuda.is_available()

# Segmentation model import
try:
    import segmentation_models_pytorch as smp
except ImportError:
    print("Warning: segmentation_models_pytorch not installed")
    print("Run: pip install segmentation-models-pytorch")
    smp = None



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

    def predict_wsi(self, slide, patch_size=512, overlap_ratio=0.3, batch_size=8, progress_callback=None, status_callback=None, roi_bounds=None, image_path=None, icc_transform=None, calibration_lut=None):
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
            icc_transform: ICC color profile transform (slide→sRGB)
            calibration_lut: Aperio calibration LUT (3, 256) numpy array

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

        # 패치를 output 해상도로 직접 리사이즈하여 누산 → 메모리 output_scale² 배 절약
        # (model_res 크기 대신 output_res 크기로 누산: 예) 8GB → 500MB)
        patch_output_size = max(1, int(patch_size / output_scale))

        prediction_sum = np.zeros((self.num_classes, output_h, output_w), dtype=np.float32)
        weight_sum = np.zeros((output_h, output_w), dtype=np.float32)

        # Create weight mask at output resolution
        weight_mask = create_gaussian_weight_mask(patch_output_size, sigma=0.3)

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

        # ── Pre-scan: tissue mask 기반 유효 패치 필터링 (Detection과 동일 방식) ──
        try:
            # 축소 썸네일로 tissue mask 생성
            thumb_downsample = 128
            thumb_w = max(1, int(region_w / thumb_downsample))
            thumb_h = max(1, int(region_h / thumb_downsample))
            thumbnail = np.array(
                slide.get_thumbnail((max(1, wsi_w // thumb_downsample),
                                     max(1, wsi_h // thumb_downsample)))
            )[:, :, :3]

            # Otsu threshold 기반 조직 마스크 (Detection과 동일)
            gray = cv2.cvtColor(thumbnail, cv2.COLOR_RGB2GRAY)
            tissue_mask = cv2.threshold(255 - gray, 30, 255, cv2.THRESH_BINARY)[1]
            tissue_mask = cv2.morphologyEx(tissue_mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
            tissue_mask = cv2.morphologyEx(tissue_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

            # 패치 크기를 썸네일 좌표로 변환
            thumb_patch_w = max(1, int(patch_size_level0 / thumb_downsample))
            thumb_patch_h = max(1, int(patch_size_level0 / thumb_downsample))

            valid_patch_coords = []
            for (x_abs, y_abs, x_rel, y_rel) in patch_coords:
                # region 오프셋 포함한 절대 좌표 → 썸네일 좌표
                tx = int(x_abs / thumb_downsample)
                ty = int(y_abs / thumb_downsample)
                tx2 = min(tx + thumb_patch_w, tissue_mask.shape[1])
                ty2 = min(ty + thumb_patch_h, tissue_mask.shape[0])
                if tx < tissue_mask.shape[1] and ty < tissue_mask.shape[0] and tx2 > tx and ty2 > ty:
                    # 해당 패치 영역에 조직이 있는지 확인 (mask 합 > 0)
                    if np.sum(tissue_mask[ty:ty2, tx:tx2]) > 0:
                        valid_patch_coords.append((x_abs, y_abs, x_rel, y_rel))
            del thumbnail, tissue_mask
        except Exception:
            valid_patch_coords = patch_coords

        n_valid = len(valid_patch_coords)
        print(f"Valid patches: {n_valid} / {total_patches} (Background skipped: {total_patches - n_valid})")
        if status_callback:
            status_callback(f"Valid patches {n_valid} confirmed, starting inference...")

        # level-0 좌표 → output 해상도 변환 비율 (루프 밖에서 1회 계산)
        combined_scale = read_scale * output_scale

        # ── 병렬 I/O: 연속 submit + 프리페치 큐 + GPU 추론 오버랩 ─────────
        import time

        read_size = int(patch_size_level0 / level_downsample)
        IO_WORKERS = min(max(2, os.cpu_count() or 4), 8) if image_path else 1  # CPU 코어 기반 (2~8)
        PREFETCH_BATCHES = 3

        # Pre-build flat LUT for PIL Image.point() (C-optimized, avoids NumPy roundtrip)
        _calibration_flat_lut = None
        if calibration_lut is not None:
            _calibration_flat_lut = (
                calibration_lut[0].tolist() + calibration_lut[1].tolist() + calibration_lut[2].tolist()
            )

        def _read_patch(coord):
            x_abs, y_abs, x_rel, y_rel = coord
            try:
                if image_path:
                    if getattr(_seg_thread_local, 'path', None) != image_path:
                        _seg_thread_local.slide = openslide.OpenSlide(image_path)
                        _seg_thread_local.path = image_path
                    _sl = _seg_thread_local.slide
                else:
                    _sl = slide
                region = _sl.read_region((x_abs, y_abs), read_level, (read_size, read_size))

                # RGBA → RGB
                rgb = region.convert('RGB')

                # ICC color profile 적용 (slide → sRGB) — C-optimized via Little CMS
                if icc_transform:
                    from PIL import ImageCms
                    ImageCms.applyTransform(rgb, icc_transform, inPlace=True)

                # Aperio calibration via PIL.point() — C-optimized, no NumPy roundtrip
                if _calibration_flat_lut is not None:
                    rgb = rgb.point(_calibration_flat_lut)

                # cv2.resize (C++/AVX) instead of PIL.resize (3-5x faster)
                arr = np.asarray(rgb)
                if arr.shape[0] != patch_size or arr.shape[1] != patch_size:
                    arr = cv2.resize(arr, (patch_size, patch_size), interpolation=cv2.INTER_LINEAR)

                return (torch.from_numpy(arr.copy()).permute(2, 0, 1).float() / 255.0, x_rel, y_rel)
            except Exception:
                return None

        prefetch_q = queue.Queue(maxsize=PREFETCH_BATCHES)
        producer_done = threading.Event()

        def _io_producer():
            """연속 submit 방식: 패치를 개별 제출하고 배치 단위로 큐에 push"""
            try:
                with ThreadPoolExecutor(max_workers=IO_WORKERS) as io_pool:
                    pending = []

                    for coord in valid_patch_coords:
                        future = io_pool.submit(_read_patch, coord)
                        pending.append(future)

                        if len(pending) >= batch_size:
                            batch_imgs, batch_coords = [], []
                            for f in pending:
                                result = f.result(timeout=60)
                                if result is not None:
                                    tensor, x_rel, y_rel = result
                                    batch_imgs.append(tensor)
                                    batch_coords.append((x_rel, y_rel))
                            while True:
                                try:
                                    prefetch_q.put(
                                        (batch_imgs, batch_coords, len(pending)),
                                        timeout=0.5
                                    )
                                    break
                                except queue.Full:
                                    pass
                            pending.clear()

                    # 남은 패치 처리
                    if pending:
                        batch_imgs, batch_coords = [], []
                        for f in pending:
                            result = f.result(timeout=60)
                            if result is not None:
                                tensor, x_rel, y_rel = result
                                batch_imgs.append(tensor)
                                batch_coords.append((x_rel, y_rel))
                        while True:
                            try:
                                prefetch_q.put(
                                    (batch_imgs, batch_coords, len(pending)),
                                    timeout=0.5
                                )
                                break
                            except queue.Full:
                                pass
            except Exception as e:
                print(f"Segmentation I/O producer error: {e}")
            finally:
                producer_done.set()
                prefetch_q.put(None)  # sentinel

        # ── 3-스레드 파이프라인: I/O → GPU 추론 → CPU 누산 ──
        infer_q = queue.Queue(maxsize=PREFETCH_BATCHES)   # I/O → GPU
        accum_q = queue.Queue(maxsize=PREFETCH_BATCHES)   # GPU → 누산
        infer_done = threading.Event()
        accum_done = threading.Event()

        prod_thread = threading.Thread(target=_io_producer, daemon=True)
        prod_thread.start()

        def _gpu_inference():
            """GPU 추론 스레드: prefetch_q → 추론 → accum_q"""
            try:
                while True:
                    try:
                        item = prefetch_q.get(timeout=120)
                    except queue.Empty:
                        if producer_done.is_set():
                            break
                        continue

                    if item is None:
                        break

                    batch_images, valid_coords, patch_count = item

                    if not batch_images:
                        accum_q.put((None, valid_coords, patch_count))
                        continue

                    batch_tensor = torch.stack(batch_images).to(self.device)
                    with torch.no_grad():
                        with torch.amp.autocast('cuda', enabled=_autocast_enabled):
                            predictions = self.model(batch_tensor)
                        predictions = F.softmax(predictions.float(), dim=1)
                        if output_scale > 1.0:
                            predictions = F.interpolate(
                                predictions,
                                size=(patch_output_size, patch_output_size),
                                mode='bilinear',
                                align_corners=False,
                            )
                        predictions = predictions.cpu().numpy()

                    while True:
                        try:
                            accum_q.put((predictions, valid_coords, patch_count), timeout=0.5)
                            break
                        except queue.Full:
                            pass
            except Exception as e:
                print(f"GPU inference thread error: {e}")
            finally:
                infer_done.set()
                accum_q.put(None)

        infer_thread = threading.Thread(target=_gpu_inference, daemon=True)
        infer_thread.start()

        def _accumulator():
            """CPU 누산 스레드: accum_q → prediction_sum/weight_sum에 누산"""
            nonlocal processed_valid
            try:
                while True:
                    try:
                        item = accum_q.get(timeout=120)
                    except queue.Empty:
                        if infer_done.is_set():
                            break
                        continue

                    if item is None:
                        break

                    predictions, valid_coords, patch_count = item
                    processed_valid += patch_count

                    if predictions is not None:
                        for i, (x_rel, y_rel) in enumerate(valid_coords):
                            x_out = int(x_rel / combined_scale)
                            y_out = int(y_rel / combined_scale)
                            x_end = min(x_out + patch_output_size, output_w)
                            y_end = min(y_out + patch_output_size, output_h)
                            ph = y_end - y_out
                            pw = x_end - x_out
                            if ph <= 0 or pw <= 0:
                                continue
                            prediction_sum[:, y_out:y_end, x_out:x_end] += \
                                predictions[i, :, :ph, :pw] * weight_mask[:ph, :pw]
                            weight_sum[y_out:y_end, x_out:x_end] += weight_mask[:ph, :pw]
            except Exception as e:
                print(f"Accumulator thread error: {e}")
            finally:
                accum_done.set()

        processed_valid = 0
        start_time = time.time()
        last_update_time = start_time

        accum_thread = threading.Thread(target=_accumulator, daemon=True)
        accum_thread.start()

        # 메인 스레드: 진행률 보고만 담당
        while not accum_done.is_set():
            accum_done.wait(timeout=1.0)
            current_time = time.time()
            if current_time - last_update_time >= 1.0:
                pct = processed_valid / n_valid if n_valid > 0 else 1.0
                elapsed = current_time - start_time
                if progress_callback:
                    progress_callback(int(pct * 100))
                if status_callback and pct > 0.01 and elapsed > 1.0:
                    patches_per_sec = processed_valid / elapsed if elapsed > 0 else 0
                    remaining = (n_valid - processed_valid) / patches_per_sec if patches_per_sec > 0 else 0
                    if remaining >= 60:
                        eta_str = f"{int(remaining) // 60}m {int(remaining) % 60}s"
                    else:
                        eta_str = f"{int(remaining)}s"
                    status_callback(
                        f"Segmentation {processed_valid}/{n_valid} "
                        f"| {patches_per_sec:.1f}it/s | ~{eta_str} remaining"
                    )
                last_update_time = current_time

        prod_thread.join(timeout=10)
        infer_thread.join(timeout=10)
        accum_thread.join(timeout=10)

        # Normalize by weights
        weight_sum = np.maximum(weight_sum, 1e-6)  # Avoid division by zero
        for c in range(self.num_classes):
            prediction_sum[c] /= weight_sum
        del weight_sum

        # prediction_sum이 이미 output 해상도 → prob_map 및 prediction_mask 바로 생성
        prob_map_output = prediction_sum  # (num_classes, output_h, output_w) — 추가 resize 불필요
        prediction_mask = np.argmax(prediction_sum, axis=0).astype(np.uint8)

        # Metadata
        metadata = {
            'wsi_dimensions': (wsi_w, wsi_h),
            'wsi_mpp': base_mpp,
            'model_mpp': self.model_mpp,
            'output_mpp': self.output_mpp,
            'mask_shape': prediction_mask.shape,
            'class_names': self.class_names,
            'region_offset': (region_offset_x, region_offset_y),  # ROI offset
            'prob_map': prob_map_output,  # (num_classes, H, W) softmax probabilities
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

    def __init__(self, slide, segmentation_model, detection_cells, device='cuda', image_path=None, icc_transform=None, calibration_lut=None):
        super().__init__()
        self.slide = slide
        self.segmentation_model = segmentation_model
        self.detection_cells = detection_cells  # Raw detection results
        self.device = device
        self.image_path = image_path
        self.icc_transform = icc_transform
        self.calibration_lut = calibration_lut
        self.is_cancelled = False

    def run(self):
        """Execute the reclassification pipeline"""
        try:
            # Step 1: Run segmentation (0-50%)
            self.status.emit("WSI segmentation running...")

            def seg_progress_callback(p):
                if not self.is_cancelled:
                    self.progress.emit(int(p * 0.5))

            prediction_mask, seg_metadata = self.segmentation_model.predict_wsi(
                self.slide,
                progress_callback=seg_progress_callback,
                image_path=self.image_path,
                icc_transform=self.icc_transform,
                calibration_lut=self.calibration_lut,
            )

            if self.is_cancelled:
                return

            self.status.emit("Reclassifying epithelial cells...")
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
                'message': f'Detection and reclassification complete: {len(reclassified_cells):,} cells'
            }

            self.finished.emit(result)

        except Exception as e:
            import traceback
            self.error.emit(f"Reclassification error: {str(e)}\n{traceback.format_exc()}")

    def _reclassify_epithelial_cells(self, cells, prediction_mask, wsi_mpp, output_mpp):
        """
        Reclassify epithelial cells based on segmentation mask + DBSCAN clustering

        DBSCAN으로 인접 epithelial 세포를 관(gland) 단위로 묶은 뒤,
        클러스터 내 segmentation 결과의 다수결로 통일하여 관 내 일관성 보장.
        """
        import numpy as np
        from sklearn.cluster import DBSCAN
        from collections import Counter

        scale_factor = wsi_mpp / output_mpp
        mask_h, mask_w = prediction_mask.shape

        # 1단계: 모든 셀 복사 + epithelial 세포별 seg_class 수집
        reclassified = []
        epi_indices = []     # reclassified 리스트 내 인덱스
        epi_coords = []      # [[x, y], ...]
        epi_seg_classes = []  # 각 세포의 원본 seg_class

        for cell in cells:
            cell_copy = cell.copy()
            cls_id = cell['cls_id']

            if cls_id == 1:  # Epithelial
                mask_x = int(cell['x'] * scale_factor)
                mask_y = int(cell['y'] * scale_factor)

                # 단일 픽셀 대신 주변 3×3 영역의 다수결로 seg_class 판정
                # output_mpp=4.0에서 경계 부근 오분류 완화
                NEIGHBORHOOD = 1  # 3×3 (중심 ± 1)
                if 0 <= mask_x < mask_w and 0 <= mask_y < mask_h:
                    y1 = max(0, mask_y - NEIGHBORHOOD)
                    y2 = min(mask_h, mask_y + NEIGHBORHOOD + 1)
                    x1 = max(0, mask_x - NEIGHBORHOOD)
                    x2 = min(mask_w, mask_x + NEIGHBORHOOD + 1)
                    patch = prediction_mask[y1:y2, x1:x2].flatten()
                    # 다수결 (Background=0 제외, 유효 클래스만 투표)
                    non_bg = patch[patch > 0]
                    if len(non_bg) > 0:
                        seg_class = int(np.bincount(non_bg).argmax())
                    else:
                        seg_class = int(patch[len(patch) // 2])  # 전부 Background면 중심값
                else:
                    seg_class = 0  # Out of bounds → Background

                epi_indices.append(len(reclassified))
                epi_coords.append([cell['x'], cell['y']])
                epi_seg_classes.append(seg_class)

            reclassified.append(cell_copy)

        epithelial_count = len(epi_indices)
        print(f"Epithelial cells to reclassify: {epithelial_count}")

        # 2단계: DBSCAN 클러스터링 (관 단위 그룹핑)
        # seg_class를 피처에 포함하여 segmentation 영역이 다른 세포는 클러스터링되지 않도록 함
        if epithelial_count > 0:
            coords_arr = np.array(epi_coords)
            seg_arr_for_cluster = np.array(epi_seg_classes, dtype=np.float64)

            # seg_class에 큰 가중치를 부여하여 다른 영역 세포가 같은 클러스터에 포함되지 않도록 함
            # seg_penalty > eps 이므로 seg_class가 다르면 절대 같은 클러스터 불가
            DBSCAN_EPS = 50
            SEG_PENALTY = 200
            feature_arr = np.column_stack([
                coords_arr,
                seg_arr_for_cluster * SEG_PENALTY
            ])
            clustering = DBSCAN(eps=DBSCAN_EPS, min_samples=3).fit(feature_arr)
            labels = clustering.labels_

            # 3단계: 클러스터별 Tumor 비율 판정 — numpy 벡터화
            # 같은 seg 영역 내에서만 클러스터가 형성되므로 다수결이 안전하게 적용됨
            TUMOR_RATIO_THRESHOLD = 0.5
            epi_seg_arr = np.array(epi_seg_classes, dtype=np.int32)
            valid_mask = labels >= 0  # DBSCAN noise(-1) 제외
            if valid_mask.any():
                valid_labels = labels[valid_mask]
                valid_segs   = epi_seg_arr[valid_mask]
                n_cls        = int(valid_labels.max()) + 1
                tumor_counts = np.bincount(valid_labels, weights=(valid_segs == 3).astype(np.float64), minlength=n_cls)
                total_counts = np.bincount(valid_labels, minlength=n_cls)
                with np.errstate(divide='ignore', invalid='ignore'):
                    tumor_ratio = np.where(total_counts > 0, tumor_counts / total_counts, 0.0)
                cluster_assign = np.where(tumor_ratio >= TUMOR_RATIO_THRESHOLD, 3, 2).astype(np.int32)
                epi_seg_arr[valid_mask] = cluster_assign[valid_labels]
                epi_seg_classes = epi_seg_arr.tolist()

        # 4단계: 최종 cls_id 할당
        for k, idx in enumerate(epi_indices):
            seg_class = epi_seg_classes[k]
            if seg_class == 3:  # Tumor region
                reclassified[idx]['cls_id'] = 6
                reclassified[idx]['seg_region'] = 'Tumor'
            elif seg_class == 2:  # Non_Tumor region
                reclassified[idx]['cls_id'] = 7
                reclassified[idx]['seg_region'] = 'Non_Tumor'
            else:  # Stroma (1) or Background (0)
                reclassified[idx]['cls_id'] = 8
                reclassified[idx]['seg_region'] = 'Stroma/Background'

        print(f"Reclassified {epithelial_count} Epithelial cells (DBSCAN clustering applied)")
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
            self.classificationError.emit(f"Segmentation model load failed: {str(e)}")
            return False

    def run_classification(self, slide, detection_cells, image_path=None, icc_transform=None, calibration_lut=None):
        """
        Run epithelial cell reclassification

        Args:
            slide: OpenSlide object
            detection_cells: List of detected cells from YOLOv11
            image_path: WSI file path for multi-thread I/O
            icc_transform: ICC color profile transform
            calibration_lut: Aperio calibration LUT
        """
        if self.segmentation_model is None:
            self.classificationError.emit("Segmentation model not loaded.")
            return

        if self.worker and self.worker.isRunning():
            self.classificationError.emit("Reclassification is already running.")
            return

        self.worker = EpithelialClassificationWorker(
            slide,
            self.segmentation_model,
            detection_cells,
            self.device,
            image_path=image_path,
            icc_transform=icc_transform,
            calibration_lut=calibration_lut,
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


# ============================================================================
# Tumor Segmentation Worker (Background Thread)
# ============================================================================

class TumorSegmentationWorker(QThread):
    """
    Tumor Segmentation을 백그라운드에서 실행하는 워커 스레드
    UI 블로킹 없이 WSISegmentationModel.predict_wsi()를 실행
    """

    finished = pyqtSignal(dict)  # {'mask', 'metadata', 'class_names', 'roi_bounds', 'roi_polygons'}
    progress = pyqtSignal(int)   # 0-100
    status = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, image_path, tissue_type, roi_bounds=None, roi_polygons=None, icc_transform=None, calibration_lut=None):
        """
        Args:
            image_path: WSI 파일 경로 (str)
            tissue_type: 'Breast' 또는 'Stomach'
            roi_bounds: (x_min, y_min, x_max, y_max) 또는 None
            roi_polygons: [[좌표, ...], ...] 또는 None
            icc_transform: ICC color profile transform (slide→sRGB)
            calibration_lut: Aperio calibration LUT (3, 256) numpy array
        """
        super().__init__()
        self.image_path = image_path
        self.tissue_type = tissue_type
        self.roi_bounds = roi_bounds
        self.roi_polygons = roi_polygons
        self.is_cancelled = False
        self.icc_transform = icc_transform
        self.calibration_lut = calibration_lut

    def run(self):
        """백그라운드 Segmentation 실행"""
        import openslide
        slide = None
        seg_model = None
        try:
            # 모델 경로 결정
            project_root = Path(__file__).parent.parent
            if self.tissue_type == "Breast":
                model_path = project_root / "model" / "HnE_BR_segmentation.pt"
            else:
                model_path = project_root / "model" / "HnE_ST_segmentation.pt"

            self.status.emit("Loading segmentation model...")
            self.progress.emit(1)

            seg_model = WSISegmentationModel(
                model_path=str(model_path),
                model_mpp=1.0,
                output_mpp=4.0,
                device='cuda'
            )

            if self.is_cancelled:
                return

            self.status.emit("Loading slide...")
            slide = openslide.OpenSlide(self.image_path)

            def progress_callback(pct):
                if not self.is_cancelled:
                    self.progress.emit(int(pct))

            def status_callback(msg):
                if not self.is_cancelled:
                    self.status.emit(msg)

            self.status.emit("Running Tumor Segmentation...")
            prediction_mask, metadata = seg_model.predict_wsi(
                slide,
                patch_size=512,
                overlap_ratio=0.4,
                batch_size=8,
                progress_callback=progress_callback,
                status_callback=status_callback,
                roi_bounds=self.roi_bounds,
                image_path=self.image_path,
                icc_transform=self.icc_transform,
                calibration_lut=self.calibration_lut,
            )

            if self.is_cancelled:
                return

            self.progress.emit(100)
            self.finished.emit({
                'mask': prediction_mask,
                'metadata': metadata,
                'class_names': seg_model.class_names,
                'roi_bounds': self.roi_bounds,
                'roi_polygons': self.roi_polygons,
            })

        except Exception as e:
            import traceback
            self.error.emit(f"Segmentation failed: {str(e)}\n{traceback.format_exc()}")

        finally:
            # GPU 메모리 및 슬라이드 정리
            if seg_model is not None:
                del seg_model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if slide is not None:
                try:
                    slide.close()
                except Exception:
                    pass

    def cancel(self):
        """작업 취소 요청"""
        self.is_cancelled = True
