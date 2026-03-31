"""
Virtual Stain Module
CycleGAN-based virtual staining: IHC → H&E, Unstained → H&E
Pipeline: prefetch I/O ↔ FP16 batched GPU inference ↔ blend accumulation.
"""

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from PyQt5.QtCore import QThread, pyqtSignal

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


def _read_patch(slide, x0, y0, best_level, level_read, ps):
    """Read a single patch from the slide (runs in I/O thread).
    Out-of-bounds pixels are composited onto a white background."""
    region = slide.read_region((x0, y0), best_level, (level_read, level_read))
    # RGBA → 흰색 배경 합성 (경계 밖 투명 픽셀이 검정이 되는 것 방지)
    white_bg = Image.new('RGB', region.size, (255, 255, 255))
    white_bg.paste(region, mask=region.split()[3])  # alpha 채널을 마스크로 사용
    if white_bg.size != (ps, ps):
        white_bg = white_bg.resize((ps, ps), Image.BILINEAR)
    return np.array(white_bg, dtype=np.float32)


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
                 roi_bounds=None, roi_polygons=None):
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

            # ── 3. Tissue mask (patch-level) ──
            self.status.emit("Creating tissue mask...")
            tissue_grid = self._build_tissue_grid(
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
            io_workers = min(4, bs)

            # Collect tissue patches into sub-batches
            # Process: prefetch I/O → GPU batch → accumulate
            tissue_batch = []   # [(px, py, tensor, region_np), ...]
            processed = 0

            with torch.inference_mode(), ThreadPoolExecutor(max_workers=io_workers) as pool:
                for patch_idx, (xi, yi, x0, y0, px, py_c, is_tissue) in enumerate(all_patches):
                    if self.is_cancelled:
                        return

                    # Submit I/O to thread pool and get result
                    future = pool.submit(_read_patch, slide, x0, y0, best_level, level_read, ps)
                    region_np = future.result()

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

            tissue_mask_full = self._grid_to_pixel_mask(
                tissue_grid, n_px, n_py, stride, ps, out_w, out_h
            )
            # 비조직 영역은 alpha=0으로 투명 처리되므로 원본 덮어쓰기 불필요

            # ── 7. Alpha channel: 조직 영역만 불투명, 비조직은 투명 ──
            import cv2
            # 비조직 영역은 alpha=0 → 원본 WSI 타일이 그대로 보임
            alpha = np.where(tissue_mask_full, 255, 0).astype(np.uint8)

            if self.roi_polygons:
                # ROI 폴리곤 바깥도 투명 처리
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
                alpha = np.minimum(alpha, poly_mask)

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
        """Build a (n_py, n_px) boolean grid: True = tissue patch."""
        mask_level = slide.get_best_level_for_downsample(
            canvas_l0_w / max(out_w // 4, 1)
        )
        mask_ds = slide.level_downsamples[mask_level]
        mask_rw = max(int(canvas_l0_w / mask_ds), 1)
        mask_rh = max(int(canvas_l0_h / mask_ds), 1)

        mask_region = slide.read_region((x_min, y_min), mask_level, (mask_rw, mask_rh))
        mask_np = np.array(mask_region.convert('RGB'), dtype=np.float32)

        rgb_std = np.std(mask_np, axis=2)
        rgb_mean = np.mean(mask_np, axis=2)
        pixel_tissue = (rgb_std > 5.0) | (rgb_mean < 220.0)
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

        return grid

    @staticmethod
    def _grid_to_pixel_mask(grid, n_px, n_py, stride, ps, out_w, out_h):
        """Convert patch-level grid back to pixel-level mask."""
        mask = np.zeros((out_h, out_w), dtype=bool)
        for yi in range(n_py):
            for xi in range(n_px):
                if grid[yi, xi]:
                    px = xi * stride
                    py = yi * stride
                    mask[py:py + ps, px:px + ps] = True
        return mask
