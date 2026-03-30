"""
Virtual Stain Module
CycleGAN-based virtual staining: IHC → H&E, Unstained → H&E
Uses overlap-tile blending with batched GPU inference.
"""

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from pathlib import Path

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


def _pil_to_tensor(pil_img):
    """PIL RGB image → normalized tensor [-1, 1], shape (3, H, W)."""
    arr = np.array(pil_img, dtype=np.float32)       # (H, W, 3)
    t = torch.from_numpy(arr).permute(2, 0, 1)      # (3, H, W)
    t = t / 255.0 * 2.0 - 1.0                       # [0,255] → [-1,1]
    return t


class VirtualStainWorker(QThread):
    """
    Background worker for WSI-level virtual staining.
    Optimized: tissue-mask pre-filtering, batched GPU inference,
    no redundant resize, float32 accumulation.
    """

    finished = pyqtSignal(dict)
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, image_path, model_path, stain_type="ihc_membrane",
                 target_mpp=2.0, patch_size=512, batch_size=4, roi_bounds=None):
        super().__init__()
        self.image_path = image_path
        self.model_path = model_path
        self.stain_type = stain_type
        self.target_mpp = target_mpp
        self.patch_size = patch_size
        self.batch_size = batch_size
        self.roi_bounds = roi_bounds
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True

    def run(self):
        import openslide

        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        slide = None
        generator = None

        try:
            # ── 1. Load model ──
            self.status.emit("Loading virtual stain model...")
            self.progress.emit(1)

            generator = Generator(3, 3).to(device)
            generator.load_state_dict(torch.load(self.model_path, map_location=device))
            generator.eval()

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

            n_px, n_py = len(pos_x), len(pos_y)
            out_w = (n_px - 1) * stride + ps
            out_h = (n_py - 1) * stride + ps
            canvas_l0_w = pos_x[-1] + read_size - x_min
            canvas_l0_h = pos_y[-1] + read_size - y_min

            self.progress.emit(5)
            if self.is_cancelled:
                return

            # ── 3. Tissue mask (patch-level, fast) ──
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

            # ── 4. Batched inference with overlap blending ──
            blend_weight = _make_blend_weight(ps, overlap)
            blend_3ch = blend_weight[:, :, None]  # pre-broadcast

            output_acc = np.zeros((out_h, out_w, 3), dtype=np.float32)
            input_acc = np.zeros((out_h, out_w, 3), dtype=np.float32)
            weight_acc = np.zeros((out_h, out_w), dtype=np.float32)

            # Collect tissue patches for batched processing
            tissue_count = 0
            processed_rows = 0

            with torch.no_grad():
                for yi in range(n_py):
                    if self.is_cancelled:
                        return

                    # Collect this row's tissue patches into a batch
                    batch_tensors = []
                    batch_coords = []     # (px, py) canvas coords
                    batch_regions_np = [] # for input_acc

                    for xi in range(n_px):
                        px = xi * stride
                        py_c = yi * stride
                        x0 = pos_x[xi]
                        y0 = pos_y[yi]

                        is_tissue = tissue_grid[yi, xi]

                        if not is_tissue:
                            # Background: read & blend directly (skip GPU)
                            region = slide.read_region((x0, y0), best_level,
                                                       (level_read, level_read))
                            region = region.convert('RGB')
                            if region.size != (ps, ps):
                                region = region.resize((ps, ps), Image.BILINEAR)
                            region_np = np.array(region, dtype=np.float32)

                            input_acc[py_c:py_c + ps, px:px + ps] += region_np * blend_3ch
                            output_acc[py_c:py_c + ps, px:px + ps] += region_np * blend_3ch
                            weight_acc[py_c:py_c + ps, px:px + ps] += blend_weight
                            continue

                        # Tissue patch: read, prepare tensor
                        region = slide.read_region((x0, y0), best_level,
                                                   (level_read, level_read))
                        region = region.convert('RGB')
                        if region.size != (ps, ps):
                            region = region.resize((ps, ps), Image.BILINEAR)

                        region_np = np.array(region, dtype=np.float32)
                        input_acc[py_c:py_c + ps, px:px + ps] += region_np * blend_3ch

                        batch_tensors.append(_pil_to_tensor(region))
                        batch_coords.append((px, py_c))
                        batch_regions_np.append(region_np)

                    # Process tissue batch for this row
                    if batch_tensors:
                        # Sub-batch to stay within VRAM
                        for b_start in range(0, len(batch_tensors), self.batch_size):
                            if self.is_cancelled:
                                return
                            b_end = min(b_start + self.batch_size, len(batch_tensors))
                            batch = torch.stack(batch_tensors[b_start:b_end]).to(device)

                            fake_batch = generator(batch)  # (B, 3, H, W)
                            fake_batch = (fake_batch.cpu() * 0.5 + 0.5).clamp(0, 1)

                            for i in range(fake_batch.shape[0]):
                                idx = b_start + i
                                px, py_c = batch_coords[idx]
                                fake_np = (fake_batch[i].permute(1, 2, 0).numpy() * 255.0)

                                output_acc[py_c:py_c + ps, px:px + ps] += fake_np * blend_3ch
                                weight_acc[py_c:py_c + ps, px:px + ps] += blend_weight

                        tissue_count += len(batch_tensors)

                    processed_rows += 1
                    pct = 8 + int(87 * processed_rows / n_py)
                    self.progress.emit(pct)
                    self.status.emit(
                        f"Virtual staining... row {processed_rows}/{n_py} "
                        f"({tissue_count} tissue patches)"
                    )

            if self.is_cancelled:
                return

            # ── 5. Normalize & compose ──
            self.status.emit("Composing final image...")
            uncovered = weight_acc < 0.01
            weight_acc = np.maximum(weight_acc, 1e-10)
            output_canvas = (output_acc / weight_acc[:, :, None]).clip(0, 255).astype(np.uint8)
            input_canvas = (input_acc / weight_acc[:, :, None]).clip(0, 255).astype(np.uint8)
            output_canvas[uncovered] = 255
            input_canvas[uncovered] = 255

            # Restore background from input
            tissue_mask_full = self._grid_to_pixel_mask(
                tissue_grid, n_px, n_py, stride, ps, out_w, out_h
            )
            output_canvas[~tissue_mask_full] = input_canvas[~tissue_mask_full]

            self.progress.emit(100)
            self.finished.emit({
                'canvas': output_canvas,
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

    def _build_tissue_grid(self, slide, x_min, y_min,
                           canvas_l0_w, canvas_l0_h,
                           n_px, n_py, stride, ps, out_w, out_h):
        """
        Build a (n_py, n_px) boolean grid: True = tissue patch.
        Uses a low-res thumbnail for speed.
        """
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

        # Resize to canvas size
        tissue_full = np.array(
            Image.fromarray(pixel_tissue.astype(np.uint8) * 255).resize(
                (out_w, out_h), Image.NEAREST)
        ) > 127

        # Downsample to patch grid
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
        """Convert patch-level grid back to pixel-level mask for background restore."""
        mask = np.zeros((out_h, out_w), dtype=bool)
        for yi in range(n_py):
            for xi in range(n_px):
                if grid[yi, xi]:
                    px = xi * stride
                    py = yi * stride
                    mask[py:py + ps, px:px + ps] = True
        return mask
