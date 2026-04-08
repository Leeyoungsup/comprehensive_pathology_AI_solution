"""
Virtual Stain Module
CycleGAN-based virtual staining: IHC → H&E, Unstained → H&E
Pipeline: prefetch I/O ↔ FP16 batched GPU inference ↔ blend accumulation.
"""

import os
import numpy as np
import cv2
import torch
import torch.nn as nn
import threading
from PIL import Image
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from PyQt5.QtCore import QThread, pyqtSignal

_vs_thread_local = threading.local()

from skimage.morphology import binary_closing, binary_opening, disk
from scipy.ndimage import binary_fill_holes


# ── CycleGAN Generator Architecture ──

class ResidualBlock(nn.Module):
    def __init__(self, features):
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(features, features, kernel_size=3, padding=1),
            nn.InstanceNorm2d(features),
            nn.ReLU(inplace=True),
            nn.Conv2d(features, features, kernel_size=3, padding=1),
            nn.InstanceNorm2d(features),
            nn.Dropout(0.5),
        )

    def forward(self, x):
        return x + self.block(x)


class Generator(nn.Module):
    def __init__(self, input_channels=3, output_channels=3, n_residual_blocks=9):
        super().__init__()
        layers = [
            nn.Conv2d(input_channels, 64, kernel_size=7, padding=3),
            nn.InstanceNorm2d(64),
            nn.ReLU(inplace=True),
        ]

        in_f = 64
        for _ in range(4):
            out_f = in_f * 2
            layers += [
                nn.Conv2d(in_f, out_f, kernel_size=3, stride=2, padding=1),
                nn.InstanceNorm2d(out_f),
                nn.ReLU(inplace=True),
            ]
            in_f = out_f

        for _ in range(n_residual_blocks):
            layers.append(ResidualBlock(in_f))

        for _ in range(4):
            out_f = in_f // 2
            layers += [
                nn.ConvTranspose2d(in_f, out_f, kernel_size=3, stride=2, padding=1, output_padding=1),
                nn.InstanceNorm2d(out_f),
                nn.ReLU(inplace=True),
            ]
            in_f = out_f

        layers += [nn.Conv2d(64, output_channels, kernel_size=7, padding=3), nn.Tanh()]
        self.model = nn.Sequential(*layers)

    def forward(self, x):
        return self.model(x)


def _make_blend_weight(size, overlap):
    """Raised-cosine 2D blending weight."""
    w = np.ones(size, dtype=np.float32)
    if overlap > 0:
        ramp = np.linspace(0, np.pi / 2, overlap, dtype=np.float32)
        fade = np.sin(ramp) ** 2
        w[:overlap] *= fade
        w[-overlap:] *= fade[::-1]
    return np.outer(w, w)


def _read_patch(image_path, x0, y0, best_level, level_read, ps, icc_transform=None, calibration_flat_lut=None):
    """Read a single patch from the slide (runs in I/O thread).
    Uses thread-local OpenSlide for safe parallel I/O.
    Out-of-bounds pixels are composited onto a white background.
    Applies ICC color profile and Aperio calibration if provided."""
    # 뷰어 타일 로딩 우선 양보
    from core.wsi_tile_manager import viewer_io_priority
    viewer_io_priority.ai_yield_if_needed()

    import openslide as _openslide
    if (not hasattr(_vs_thread_local, 'slide') or
            _vs_thread_local.image_path != image_path):
        _vs_thread_local.slide = _openslide.OpenSlide(image_path)
        _vs_thread_local.image_path = image_path
    slide = _vs_thread_local.slide

    region = slide.read_region((x0, y0), best_level, (level_read, level_read))
    # RGBA → 흰색 배경 합성 (경계 밖 투명 픽셀이 검정이 되는 것 방지)
    white_bg = Image.new('RGB', region.size, (255, 255, 255))
    white_bg.paste(region, mask=region.split()[3])

    # ICC color profile 적용 (slide → sRGB) — C-optimized via Little CMS
    if icc_transform:
        from PIL import ImageCms
        ImageCms.applyTransform(white_bg, icc_transform, inPlace=True)

    # Aperio calibration via PIL.point() — C-optimized, no NumPy roundtrip
    if calibration_flat_lut is not None:
        white_bg = white_bg.point(calibration_flat_lut)

    # cv2.resize (C++/AVX) instead of PIL.resize
    arr = np.asarray(white_bg)
    if arr.shape[0] != ps or arr.shape[1] != ps:
        arr = cv2.resize(arr, (ps, ps), interpolation=cv2.INTER_LINEAR)

    return arr.astype(np.float32)


class VirtualStainWorker(QThread):
    """
    Background worker for WSI-level virtual staining.
    Pipeline architecture:
      - ThreadPool prefetches next batch of patches from disk
      - GPU runs FP16 inference on current batch
      - CPU accumulates blended results
    """

    finished = pyqtSignal(dict)
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, image_path, model_path, stain_type="ihc_membrane",
                 target_mpp=2.0, patch_size=512, batch_size=4,
                 roi_bounds=None, roi_polygons=None,
                 icc_transform=None, calibration_lut=None):
        super().__init__()
        self.image_path = image_path
        self.model_path = model_path
        self.stain_type = stain_type
        self.target_mpp = target_mpp
        self.patch_size = patch_size
        self.batch_size = batch_size
        self.roi_bounds = roi_bounds
        self.roi_polygons = roi_polygons  # [[(x,y), ...], ...] WSI level-0 coords
        self.is_cancelled = False
        self.icc_transform = icc_transform  # ICC color profile transform (slide→sRGB)
        self.calibration_lut = calibration_lut  # Aperio calibration LUT (3, 256) numpy array
        # Pre-build flat LUT for PIL Image.point() (C-optimized)
        self.calibration_flat_lut = None
        if calibration_lut is not None:
            self.calibration_flat_lut = (
                calibration_lut[0].tolist() + calibration_lut[1].tolist() + calibration_lut[2].tolist()
            )

    def cancel(self):
        self.is_cancelled = True

    def run(self):
        import openslide

        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        use_fp16 = (device.type == 'cuda')
        slide = None
        generator = None

        try:
            # ── 1. Load model ──
            self.status.emit("Loading virtual stain model...")
            self.progress.emit(1)

            generator = Generator(3, 3).to(device)
            generator.load_state_dict(torch.load(self.model_path, map_location=device))
            generator.eval()
            if use_fp16:
                generator = generator.half()

            if self.is_cancelled:
                return

            # ── 2. Open slide & compute grid ──
            self.status.emit("Opening slide...")
            self.progress.emit(3)
            slide = openslide.OpenSlide(self.image_path)

            native_mpp = float(slide.properties.get('openslide.mpp-x', 0.25))
            downsample_factor = self.target_mpp / native_mpp
            ps = self.patch_size
            overlap = ps // 4
            stride = ps - overlap
            read_size = int(ps * downsample_factor)
            read_stride = int(stride * downsample_factor)

            best_level = slide.get_best_level_for_downsample(downsample_factor)
            level_ds = slide.level_downsamples[best_level]
            level_read = int(read_size / level_ds)

            W, H = slide.dimensions
            if self.roi_bounds:
                x_min, y_min, x_max, y_max = self.roi_bounds
                x_min, y_min = max(0, x_min), max(0, y_min)
                x_max, y_max = min(W, x_max), min(H, y_max)
            else:
                x_min, y_min, x_max, y_max = 0, 0, W, H

            pos_x = list(range(x_min, x_max - read_size + 1, read_stride))
            pos_y = list(range(y_min, y_max - read_size + 1, read_stride))
            if not pos_x or not pos_y:
                self.error.emit("ROI is too small for virtual staining.")
                return
            # Ensure grid fully covers the ROI bounding box
            if pos_x[-1] + read_size < x_max:
                pos_x.append(max(pos_x[-1] + read_stride, x_max - read_size))
            if pos_y[-1] + read_size < y_max:
                pos_y.append(max(pos_y[-1] + read_stride, y_max - read_size))

            n_px, n_py = len(pos_x), len(pos_y)
            out_w = (n_px - 1) * stride + ps
            out_h = (n_py - 1) * stride + ps
            canvas_l0_w = pos_x[-1] + read_size - x_min
            canvas_l0_h = pos_y[-1] + read_size - y_min

            self.progress.emit(5)
            if self.is_cancelled:
                return

            # ── 3. Tissue mask (patch-level + pixel-level) ──
            self.status.emit("Creating tissue mask...")
            tissue_grid, tissue_pixel_mask = self._build_tissue_grid(
                slide, x_min, y_min, canvas_l0_w, canvas_l0_h,
                n_px, n_py, stride, ps, out_w, out_h
            )
            tissue_total = int(tissue_grid.sum())
            skip_total = n_px * n_py - tissue_total
            self.status.emit(
                f"Grid {n_px}x{n_py}: {tissue_total} tissue, {skip_total} skip"
            )
            self.progress.emit(8)
            if self.is_cancelled:
                return

            # ── 4. Build flat list of all patches with tissue flag ──
            # 경계를 넘는 패치는 추론 스킵 (is_tissue=False)
            all_patches = []
            for yi in range(n_py):
                for xi in range(n_px):
                    x0 = pos_x[xi]
                    y0 = pos_y[yi]
                    out_of_bounds = (x0 + read_size > W) or (y0 + read_size > H)
                    is_tissue = bool(tissue_grid[yi, xi]) and not out_of_bounds
                    all_patches.append((
                        xi, yi,
                        x0, y0,
                        xi * stride, yi * stride,
                        is_tissue,
                    ))

            # ── 5. Pipelined inference ──
            blend_weight = _make_blend_weight(ps, overlap)
            blend_3ch = blend_weight[:, :, None]

            output_acc = np.zeros((out_h, out_w, 3), dtype=np.float32)
            input_acc = np.zeros((out_h, out_w, 3), dtype=np.float32)
            weight_acc = np.zeros((out_h, out_w), dtype=np.float32)

            tissue_count = 0
            total = len(all_patches)
            bs = self.batch_size
            io_workers = min(max(2, os.cpu_count() or 4), 8)

            # Collect tissue patches into sub-batches
            # Process: prefetch I/O → GPU batch → accumulate
            tissue_batch = []   # [(px, py, tensor, region_np), ...]
            processed = 0

            with torch.inference_mode(), ThreadPoolExecutor(max_workers=io_workers) as pool:
                # 전체 패치를 미리 submit하고 future 리스트 구성
                futures = []
                for (xi, yi, x0, y0, px, py_c, is_tissue) in all_patches:
                    f = pool.submit(_read_patch, self.image_path, x0, y0, best_level, level_read, ps,
                                    self.icc_transform, self.calibration_flat_lut)
                    futures.append(f)

                for patch_idx, (xi, yi, x0, y0, px, py_c, is_tissue) in enumerate(all_patches):
                    if self.is_cancelled:
                        return

                    region_np = futures[patch_idx].result()

                    # Accumulate input
                    input_acc[py_c:py_c + ps, px:px + ps] += region_np * blend_3ch

                    if not is_tissue:
                        # Background: copy input directly
                        output_acc[py_c:py_c + ps, px:px + ps] += region_np * blend_3ch
                        weight_acc[py_c:py_c + ps, px:px + ps] += blend_weight
                    else:
                        # Prepare tensor from numpy (no PIL round-trip)
                        t = torch.from_numpy(region_np).permute(2, 0, 1)  # (3,H,W)
                        t = t / 255.0 * 2.0 - 1.0
                        tissue_batch.append((px, py_c, t))

                    # Flush batch when full or at end of row
                    is_end_of_row = (xi == n_px - 1)
                    batch_full = len(tissue_batch) >= bs
                    if tissue_batch and (batch_full or is_end_of_row):
                        self._run_batch(
                            generator, device, use_fp16, tissue_batch,
                            output_acc, weight_acc, blend_3ch, blend_weight, ps
                        )
                        tissue_count += len(tissue_batch)
                        tissue_batch.clear()

                    processed += 1

                    # Progress every row
                    if is_end_of_row:
                        pct = 8 + int(87 * (yi + 1) / n_py)
                        self.progress.emit(pct)
                        self.status.emit(
                            f"Virtual staining... row {yi + 1}/{n_py} "
                            f"({tissue_count} tissue patches)"
                        )

            # Flush remaining
            if tissue_batch:
                self._run_batch(
                    generator, device, use_fp16, tissue_batch,
                    output_acc, weight_acc, blend_3ch, blend_weight, ps
                )
                tissue_count += len(tissue_batch)
                tissue_batch.clear()

            if self.is_cancelled:
                return

            # ── 6. Normalize & compose ──
            self.status.emit("Composing final image...")
            uncovered = weight_acc < 0.01
            weight_acc = np.maximum(weight_acc, 1e-10)
            output_canvas = (output_acc / weight_acc[:, :, None]).clip(0, 255).astype(np.uint8)
            input_canvas = (input_acc / weight_acc[:, :, None]).clip(0, 255).astype(np.uint8)
            output_canvas[uncovered] = 255
            input_canvas[uncovered] = 255

            # 비조직 픽셀은 원본 입력값으로 덮어씌움 (픽셀 단위 정밀 마스킹)
            output_canvas[~tissue_pixel_mask] = input_canvas[~tissue_pixel_mask]

            # ── 7. Polygon ROI masking → RGBA ──
            import cv2
            alpha = np.full((out_h, out_w), 255, dtype=np.uint8)
            if self.roi_polygons:
                # Convert WSI level-0 polygon coords to canvas pixel coords
                scale_x = out_w / canvas_l0_w
                scale_y = out_h / canvas_l0_h
                poly_mask = np.zeros((out_h, out_w), dtype=np.uint8)
                for poly_coords in self.roi_polygons:
                    pts = np.array([
                        [round((x - x_min) * scale_x),
                         round((y - y_min) * scale_y)]
                        for x, y in poly_coords
                    ], dtype=np.int32)
                    cv2.fillPoly(poly_mask, [pts], 255)
                alpha = poly_mask

            rgba_canvas = np.ascontiguousarray(
                np.dstack([output_canvas, alpha])
            )

            self.progress.emit(100)
            self.finished.emit({
                'canvas': rgba_canvas,
                'input_canvas': input_canvas,
                'stain_type': self.stain_type,
                'roi_origin': (x_min, y_min),
                'canvas_l0_w': canvas_l0_w,
                'canvas_l0_h': canvas_l0_h,
                'target_mpp': self.target_mpp,
                'tissue_count': tissue_count,
                'total_patches': n_px * n_py,
            })

        except Exception as e:
            import traceback
            self.error.emit(f"Virtual staining failed: {e}\n{traceback.format_exc()}")

        finally:
            del generator
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if slide is not None:
                try:
                    slide.close()
                except Exception:
                    pass

    @staticmethod
    def _run_batch(generator, device, use_fp16, tissue_batch,
                   output_acc, weight_acc, blend_3ch, blend_weight, ps):
        """Run a single batch through the generator and accumulate results."""
        tensors = [item[2] for item in tissue_batch]
        batch = torch.stack(tensors).to(device, non_blocking=True)
        if use_fp16:
            batch = batch.half()

        fake_batch = generator(batch)

        # Back to float32 CPU
        fake_batch = fake_batch.float().cpu()
        fake_batch = (fake_batch * 0.5 + 0.5).clamp_(0, 1)

        for i, (px, py_c, _) in enumerate(tissue_batch):
            fake_np = (fake_batch[i].permute(1, 2, 0).numpy() * 255.0)
            output_acc[py_c:py_c + ps, px:px + ps] += fake_np * blend_3ch
            weight_acc[py_c:py_c + ps, px:px + ps] += blend_weight

    def _build_tissue_grid(self, slide, x_min, y_min,
                           canvas_l0_w, canvas_l0_h,
                           n_px, n_py, stride, ps, out_w, out_h):
        """Build a (n_py, n_px) boolean grid and pixel-level tissue mask.

        Color Deconvolution + 텍스처 기반 조직 검출:
        1) RGB → OD → H-DAB color deconvolution (Ruifrok & Johnston 2001)
        2) Hematoxylin OD + DAB OD 각각 Otsu → union = 염색 영역
        3) 텍스처(국소 std) → 염색 안 되었지만 구조 있는 조직 추가 검출
        4) 밝기 peak → 확실한 유리 배경 제거

        Returns:
            grid: (n_py, n_px) bool — True if patch contains tissue.
            tissue_full: (out_h, out_w) bool — pixel-level tissue mask.
        """
        import cv2 as _cv2

        mask_level = slide.get_best_level_for_downsample(
            canvas_l0_w / max(out_w // 4, 1)
        )
        mask_ds = slide.level_downsamples[mask_level]
        mask_rw = max(int(canvas_l0_w / mask_ds), 1)
        mask_rh = max(int(canvas_l0_h / mask_ds), 1)

        mask_region = slide.read_region((x_min, y_min), mask_level, (mask_rw, mask_rh))
        mask_np = np.array(mask_region.convert('RGB'), dtype=np.uint8)

        # ── Color Deconvolution (H-DAB) ──
        # Stain vectors (Ruifrok & Johnston, Analytical and Quantitative
        # Cytology and Histology, 2001) — hardcoded, well-established
        # Row 0: Hematoxylin, Row 1: DAB, Row 2: Residual
        stain_matrix = np.array([
            [0.650, 0.704, 0.286],   # Hematoxylin
            [0.268, 0.570, 0.776],   # DAB
            [0.711, 0.423, 0.500],   # Residual
        ], dtype=np.float64)

        # Normalize rows
        stain_matrix = stain_matrix / np.linalg.norm(stain_matrix, axis=1, keepdims=True)
        # Inverse for deconvolution
        deconv_matrix = np.linalg.inv(stain_matrix)

        # RGB → Optical Density (Beer-Lambert)
        rgb_f = mask_np.astype(np.float64)
        rgb_f = np.maximum(rgb_f, 1.0)  # avoid log(0)
        od = -np.log(rgb_f / 255.0)

        # Deconvolve: OD * inv(stain_matrix)^T → per-stain OD
        od_flat = od.reshape(-1, 3)
        stain_od = od_flat @ deconv_matrix.T
        h, w = mask_np.shape[:2]
        stain_od = stain_od.reshape(h, w, 3)

        hematoxylin_od = np.clip(stain_od[:, :, 0], 0, None)
        dab_od = np.clip(stain_od[:, :, 1], 0, None)

        # Scale to 0-255 for Otsu
        hem_max = max(np.percentile(hematoxylin_od, 99.5), 0.01)
        dab_max = max(np.percentile(dab_od, 99.5), 0.01)
        hem_u8 = np.clip(hematoxylin_od / hem_max * 255, 0, 255).astype(np.uint8)
        dab_u8 = np.clip(dab_od / dab_max * 255, 0, 255).astype(np.uint8)

        # Otsu per channel
        _, hem_mask = _cv2.threshold(hem_u8, 0, 255, _cv2.THRESH_BINARY + _cv2.THRESH_OTSU)
        _, dab_mask = _cv2.threshold(dab_u8, 0, 255, _cv2.THRESH_BINARY + _cv2.THRESH_OTSU)

        # ── 텍스처 (국소 std) — 무염색이지만 구조 있는 조직 보완 ──
        gray = _cv2.cvtColor(mask_np, _cv2.COLOR_RGB2GRAY)
        gray_f = gray.astype(np.float32)
        ksize = (15, 15)
        local_mean = _cv2.blur(gray_f, ksize)
        local_sq_mean = _cv2.blur(gray_f ** 2, ksize)
        local_std = np.sqrt(np.maximum(local_sq_mean - local_mean ** 2, 0))
        std_scaled = np.clip(local_std * 10, 0, 255).astype(np.uint8)
        _, texture_mask = _cv2.threshold(
            std_scaled, 0, 255, _cv2.THRESH_BINARY + _cv2.THRESH_OTSU
        )

        # ── 확실한 유리 배경 제거 ──
        hist = _cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
        bg_peak = int(np.argmax(hist[128:]) + 128)
        definite_bg = (gray >= int(bg_peak * 0.95))  # 거의 흰색인 영역만

        # 조직 = (Hematoxylin OR DAB OR 텍스처) AND NOT 확실한_배경
        pixel_tissue = ((hem_mask > 0) | (dab_mask > 0) | (texture_mask > 0)) & (~definite_bg)

        pixel_tissue = binary_closing(pixel_tissue, disk(5))
        pixel_tissue = binary_fill_holes(pixel_tissue)
        pixel_tissue = binary_opening(pixel_tissue, disk(3))

        tissue_full = np.array(
            Image.fromarray(pixel_tissue.astype(np.uint8) * 255).resize(
                (out_w, out_h), Image.NEAREST)
        ) > 127

        grid = np.zeros((n_py, n_px), dtype=bool)
        for yi in range(n_py):
            for xi in range(n_px):
                px = xi * stride
                py = yi * stride
                block = tissue_full[py:py + ps, px:px + ps]
                grid[yi, xi] = block.size > 0 and block.mean() > 0.1

        return grid, tissue_full

