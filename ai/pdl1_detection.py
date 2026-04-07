"""
PD-L1 Detection Module
AI module for detecting PD-L1 positive/negative tumor cells in pathology images
Based on YOLOv11m, calculates TPS (Tumor Proportion Score)
"""

import os
import numpy as np
import torch
import torchvision
import cv2
from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSignal, QThread

# AI 모델 경로 설정
AI_ROOT = Path(__file__).parent

import sys
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from nets import nn


def wh2xy(x):
    """Width-Height를 XY 좌표로 변환"""
    y = x.clone() if isinstance(x, torch.Tensor) else np.copy(x)
    y[:, 0] = x[:, 0] - x[:, 2] / 2
    y[:, 1] = x[:, 1] - x[:, 3] / 2
    y[:, 2] = x[:, 0] + x[:, 2] / 2
    y[:, 3] = x[:, 1] + x[:, 3] / 2
    return y


def non_max_suppression(outputs, confidence_threshold=0.201, iou_threshold=0.6, class_thresholds=None):
    """PD-L1용 클래스별 NMS (3 classes)"""
    max_wh = 7680
    bs = outputs.shape[0]
    nc = outputs.shape[1] - 4

    min_conf = confidence_threshold
    if class_thresholds:
        min_conf = min(min(class_thresholds.values()), confidence_threshold)

    xc = outputs[:, 4:4 + nc].amax(1) > min_conf
    output = [torch.zeros((0, 6), device=outputs.device)] * bs

    for xi, x in enumerate(outputs):
        x = x.transpose(0, -1)[xc[xi]]
        if not x.shape[0]:
            continue

        box, cls = x.split((4, nc), 1)
        box = wh2xy(box)
        conf, j = cls.max(1, keepdim=True)
        x = torch.cat((box, conf, j.float()), 1)

        if class_thresholds:
            keep = torch.zeros(x.shape[0], dtype=torch.bool, device=x.device)
            for i, detection in enumerate(x):
                class_id = int(detection[5].item())
                threshold = class_thresholds.get(class_id, confidence_threshold)
                if detection[4].item() >= threshold:
                    keep[i] = True
            x = x[keep]
        else:
            x = x[x[:, 4] > confidence_threshold]

        if not x.shape[0]:
            continue

        x = x[x[:, 4].argsort(descending=True)]
        c = x[:, 5:6] * max_wh
        boxes = x[:, :4] + c
        scores = x[:, 4]
        keep = torchvision.ops.nms(boxes, scores, iou_threshold)
        output[xi] = x[keep]

    return output

# PD-L1 클래스 설정 (3 classes, 표시는 Tumor만)
PDL1_CLASS_NAMES = {
    0: "PD-L1 Negative Tumor",
    1: "PD-L1 Positive Tumor",
}

# 내부 카운팅용 (Non-Tumor 포함)
_PDL1_ALL_CLASS_NAMES = {
    0: "PD-L1 Negative Tumor",
    1: "PD-L1 Positive Tumor",
    2: "Non-Tumor Cell",
}

PDL1_CLASS_COLORS = {
    0: "#0000FF",  # Negative - 파란색
    1: "#FF0000",  # Positive - 빨간색
}

PDL1_CLASS_COLORS_RGB = {
    0: (0, 0, 255),    # Negative - 파란색
    1: (255, 0, 0),    # Positive - 빨간색
}


class PDL1DetectionWorker(QThread):
    """PD-L1 검출 작업을 백그라운드에서 수행하는 워커 스레드"""

    finished = pyqtSignal(dict)
    progress = pyqtSignal(int)
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, slide, model, roi_polygons=None, device='cuda', icc_transform=None, calibration_lut=None, image_path=None):
        super().__init__()
        self.slide = slide
        self.model = model
        self.roi_polygons = roi_polygons
        self.device = device
        self.is_cancelled = False
        self.image_path = image_path  # 병렬 I/O용 슬라이드 경로
        self.icc_transform = icc_transform  # ICC color profile transform (slide→sRGB)
        self.calibration_lut = calibration_lut  # Aperio calibration LUT (3, 256) numpy array
        # Pre-build flat LUT for PIL Image.point() (C-optimized)
        self.calibration_flat_lut = None
        if calibration_lut is not None:
            self.calibration_flat_lut = (
                calibration_lut[0].tolist() + calibration_lut[1].tolist() + calibration_lut[2].tolist()
            )

        self.image_size = 512

        # MPP 정보
        try:
            mpp_x = slide.properties.get('openslide.mpp-x')
            mpp_y = slide.properties.get('openslide.mpp-y')
            if mpp_x and mpp_y:
                self.origin_mpp = (float(mpp_x) + float(mpp_y)) / 2
                print(f"Slide MPP: {self.origin_mpp:.4f} (x={mpp_x}, y={mpp_y})")
            else:
                self.origin_mpp = 0.25
                print(f"MPP info not found, using default: {self.origin_mpp}")
        except:
            self.origin_mpp = 0.25
            print(f"MPP read failed, using default: {self.origin_mpp}")

        self.output_mpp = 0.5
        self.original_size = int(self.image_size * self.output_mpp / self.origin_mpp)
        self.magnification = self.original_size / self.image_size

        # 클래스별 confidence threshold
        self.class_thresholds = {
            0: 0.05,  # PD-L1 Negative Tumor
            1: 0.05,  # PD-L1 Positive Tumor
            2: 0.05,  # Non-Tumor Cell
        }

    def run(self):
        """검출 작업 실행 (배치 병렬 I/O + GPU 추론 파이프라인)"""
        import time
        import threading
        import queue
        from concurrent.futures import ThreadPoolExecutor

        _pdl1_thread_local = threading.local()

        try:
            start_total = time.time()

            self.status.emit("Starting PD-L1 detection...")
            self.progress.emit(1)

            width, height = self.slide.dimensions

            self.status.emit(f"Slide size: {width}x{height}")
            self.progress.emit(3)

            # 조직 마스크 생성
            self.status.emit("Detecting tissue regions... (generating thumbnail)")
            start_mask = time.time()
            thumb_mask = self._create_tissue_mask()
            mask_time = time.time() - start_mask
            self.status.emit(f"Tissue mask created ({mask_time:.2f}s)")
            self.progress.emit(5)

            # ── Pre-scan: 유효 패치 사전 집계 ──
            self.status.emit("Counting valid patches...")
            valid_patch_list = []
            for patch_row in range(width // self.original_size - 1):
                for patch_col in range(height // self.original_size - 1):
                    mask_x = (patch_row * self.original_size) // 64
                    mask_y = (patch_col * self.original_size) // 64
                    mask_region = thumb_mask[mask_y:mask_y + self.original_size // 64,
                                            mask_x:mask_x + self.original_size // 64]
                    if np.sum(mask_region) == 0:
                        continue
                    px = patch_row * self.original_size
                    py = patch_col * self.original_size
                    if self.roi_polygons and not self._is_in_roi(px, py):
                        continue
                    valid_patch_list.append((px, py))

            n_valid = len(valid_patch_list)
            total_grid = (width // self.original_size) * (height // self.original_size)
            self.status.emit(f"Found {n_valid} valid patches (out of {total_grid} total)")

            # ── 배치 병렬 I/O + GPU 추론 파이프라인 ──
            BATCH_SIZE = 8
            IO_WORKERS = min(max(2, os.cpu_count() or 4), 8)
            PREFETCH_BATCHES = 3

            _chunks_cells = []
            detected_cells_count = 0
            processed_valid = 0
            start_time = time.time()
            last_update_time = start_time

            prefetch_queue = queue.Queue(maxsize=PREFETCH_BATCHES)
            producer_done = threading.Event()

            def _read_patch_tensor(patch_x, patch_y):
                """I/O 스레드: 패치 읽기 → CPU 텐서 반환"""
                try:
                    if self.image_path:
                        if (not hasattr(_pdl1_thread_local, 'slide') or
                                _pdl1_thread_local.image_path != self.image_path):
                            import openslide as _openslide
                            _pdl1_thread_local.slide = _openslide.OpenSlide(self.image_path)
                            _pdl1_thread_local.image_path = self.image_path
                        slide = _pdl1_thread_local.slide
                    else:
                        slide = self.slide

                    patch = slide.read_region(
                        (patch_x, patch_y), 0, (self.original_size, self.original_size)
                    )
                    patch_rgb = patch.convert('RGB')

                    if self.icc_transform:
                        from PIL import ImageCms
                        ImageCms.applyTransform(patch_rgb, self.icc_transform, inPlace=True)
                    if self.calibration_flat_lut is not None:
                        patch_rgb = patch_rgb.point(self.calibration_flat_lut)

                    patch_arr = np.asarray(patch_rgb)
                    patch_arr = cv2.resize(patch_arr, (self.image_size, self.image_size))
                    return torch.from_numpy(patch_arr.copy()).permute(2, 0, 1).float() / 255.
                except Exception as e:
                    print(f"PD-L1 patch read error ({patch_x}, {patch_y}): {e}")
                    return None

            def _io_producer():
                """I/O 스레드: 패치 병렬 읽기 → 배치 구성 → 프리페치 큐"""
                try:
                    with ThreadPoolExecutor(max_workers=IO_WORKERS) as io_pool:
                        pending = []

                        for px, py in valid_patch_list:
                            if self.is_cancelled:
                                break
                            future = io_pool.submit(_read_patch_tensor, px, py)
                            pending.append((px, py, future))

                            if len(pending) >= BATCH_SIZE:
                                batch_coords, batch_tensors = [], []
                                for bx, by, f in pending:
                                    t = f.result(timeout=60)
                                    if t is not None:
                                        batch_coords.append((bx, by))
                                        batch_tensors.append(t)
                                if batch_coords:
                                    while True:
                                        try:
                                            prefetch_queue.put(
                                                (batch_coords, batch_tensors, len(pending)),
                                                timeout=0.5
                                            )
                                            break
                                        except queue.Full:
                                            if self.is_cancelled:
                                                return
                                pending.clear()

                        if pending and not self.is_cancelled:
                            batch_coords, batch_tensors = [], []
                            for bx, by, f in pending:
                                t = f.result(timeout=60)
                                if t is not None:
                                    batch_coords.append((bx, by))
                                    batch_tensors.append(t)
                            if batch_coords:
                                while True:
                                    try:
                                        prefetch_queue.put(
                                            (batch_coords, batch_tensors, len(pending)),
                                            timeout=0.5
                                        )
                                        break
                                    except queue.Full:
                                        if self.is_cancelled:
                                            return
                except Exception as e:
                    print(f"PD-L1 I/O producer error: {e}")
                finally:
                    producer_done.set()
                    prefetch_queue.put(None)

            producer_thread = threading.Thread(target=_io_producer, daemon=True)
            producer_thread.start()

            # GPU 추론 루프
            self.model.eval()
            while True:
                try:
                    item = prefetch_queue.get(timeout=120)
                except queue.Empty:
                    if producer_done.is_set():
                        break
                    continue

                if item is None:
                    break

                if self.is_cancelled:
                    while True:
                        try:
                            prefetch_queue.get_nowait()
                        except queue.Empty:
                            break
                    break

                batch_coords, batch_tensors, patch_count = item
                batch_tensor = torch.stack(batch_tensors).to(self.device)

                with torch.no_grad():
                    with torch.amp.autocast('cuda'):
                        pred = self.model(batch_tensor)

                    results = non_max_suppression(pred, confidence_threshold=0.35,
                                                  iou_threshold=0.6,
                                                  class_thresholds=self.class_thresholds)

                for bi, (start_x, start_y) in enumerate(batch_coords):
                    if len(results[bi]) > 0:
                        detections = results[bi]
                        xyxy = detections[:, :4]
                        confs = detections[:, 4]
                        cls_ids = detections[:, 5]

                        centers_x = (xyxy[:, 0] + xyxy[:, 2]) / 2
                        centers_y = (xyxy[:, 1] + xyxy[:, 3]) / 2

                        actual_x = start_x + centers_x * (self.original_size / self.image_size)
                        actual_y = start_y + centers_y * (self.original_size / self.image_size)

                        for i in range(len(detections)):
                            cell_x = actual_x[i].item()
                            cell_y = actual_y[i].item()

                            if self.roi_polygons:
                                in_roi = any(p.contains_point(cell_x, cell_y) for p in self.roi_polygons)
                                if not in_roi:
                                    continue

                            _chunks_cells.append({
                                'x': cell_x,
                                'y': cell_y,
                                'cls_id': int(cls_ids[i].item()),
                                'confidence': confs[i].item()
                            })

                detected_cells_count = len(_chunks_cells)
                processed_valid += patch_count
                pct = processed_valid / n_valid if n_valid > 0 else 1.0
                self.progress.emit(int(5 + pct * 90))

                current_time = time.time()
                if current_time - last_update_time >= 1.0:
                    elapsed = current_time - start_time
                    patches_per_sec = processed_valid / elapsed if elapsed > 0 else 0
                    remaining = n_valid - processed_valid
                    eta = remaining / patches_per_sec if patches_per_sec > 0 else 0
                    if eta >= 60:
                        eta_str = f"{int(eta) // 60}m {int(eta) % 60}s"
                    else:
                        eta_str = f"{int(eta)}s"
                    self.status.emit(
                        f"Patch {processed_valid}/{n_valid} | Cells: {detected_cells_count} "
                        f"| {patches_per_sec:.1f}it/s | ~{eta_str} remaining"
                    )
                    last_update_time = current_time

            producer_thread.join(timeout=10)

            if self.is_cancelled:
                self.error.emit("Detection cancelled.")
                return

            all_cells = _chunks_cells
            self.status.emit(f"Finalizing results... ({len(all_cells)} detected)")
            self.progress.emit(95)

            # TPS 계산 (Non-Tumor 포함 전체 세포로 계산)
            class_counts = self._count_by_class(all_cells)
            tps = self._calculate_tps(all_cells)

            # Non-Tumor Cell 제거 (표시 및 결과에서 제외)
            tumor_cells = [c for c in all_cells if c['cls_id'] != 2]

            total_time = time.time() - start_total
            result = {
                'status': 'success',
                'cells': tumor_cells,
                'num_cells': len(tumor_cells),
                'class_counts': class_counts,
                'tps': tps,
                'message': f'PD-L1 detection complete: {len(tumor_cells)} tumor cells, TPS={tps:.1f}% ({total_time:.1f}s)'
            }

            self.progress.emit(100)
            self.finished.emit(result)

        except Exception as e:
            import traceback
            self.error.emit(f"PD-L1 detection error: {str(e)}\n{traceback.format_exc()}")

    def _create_tissue_mask(self):
        """조직 영역 마스크 생성 (고속 최적화)"""
        try:
            downsample = 128
            thumbnail = self.slide.get_thumbnail((self.slide.dimensions[0] // downsample,
                                                  self.slide.dimensions[1] // downsample))
            thumbnail = np.array(thumbnail)

            if len(thumbnail.shape) == 3:
                gray = cv2.cvtColor(thumbnail[:, :, :3], cv2.COLOR_RGB2GRAY)
            else:
                gray = thumbnail

            mask = cv2.threshold(255 - gray, 30, 255, cv2.THRESH_BINARY)[1]
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

            target_width = self.slide.dimensions[0] // 64
            target_height = self.slide.dimensions[1] // 64
            mask = cv2.resize(mask, (target_width, target_height), interpolation=cv2.INTER_NEAREST)
            return mask
        except Exception as e:
            print(f"Mask creation failed: {e}")
            width, height = self.slide.dimensions
            return np.ones((height // 64, width // 64), dtype=np.uint8) * 255

    def _is_in_roi(self, patch_x, patch_y):
        """패치가 ROI 영역과 겹치는지 확인 (교차 판정)"""
        if not self.roi_polygons:
            return True

        patch_corners = [
            (patch_x, patch_y),
            (patch_x + self.original_size, patch_y),
            (patch_x + self.original_size, patch_y + self.original_size),
            (patch_x, patch_y + self.original_size)
        ]

        patch_center_x = patch_x + self.original_size // 2
        patch_center_y = patch_y + self.original_size // 2

        for polygon in self.roi_polygons:
            if polygon.contains_point(patch_center_x, patch_center_y):
                return True
            for cx, cy in patch_corners:
                if polygon.contains_point(cx, cy):
                    return True
        return False

    def _process_patch(self, start_x, start_y):
        """단일 패치 처리"""
        cells = []
        try:
            patch = self.slide.read_region((start_x, start_y), 0,
                                           (self.original_size, self.original_size))

            # RGBA → RGB + color correction in PIL (C-optimized)
            patch_rgb = patch.convert('RGB')

            if self.icc_transform:
                from PIL import ImageCms
                ImageCms.applyTransform(patch_rgb, self.icc_transform, inPlace=True)

            if self.calibration_flat_lut is not None:
                patch_rgb = patch_rgb.point(self.calibration_flat_lut)

            patch = np.asarray(patch_rgb)

            # 리사이즈 (original_size → model input size)
            patch = cv2.resize(patch, (self.image_size, self.image_size))

            # 텐서 변환
            torch_patch = torch.from_numpy(patch).permute(2, 0, 1).unsqueeze(0).float() / 255.
            torch_patch = torch_patch.to(self.device)

            # 추론
            self.model.eval()
            with torch.no_grad():
                with torch.amp.autocast('cuda'):
                    pred = self.model(torch_patch)

                results = non_max_suppression(pred, confidence_threshold=0.35,
                                             iou_threshold=0.6,
                                             class_thresholds=self.class_thresholds)

                if len(results[0]) > 0:
                    detections = results[0]
                    xyxy = detections[:, :4]
                    confs = detections[:, 4]
                    cls_ids = detections[:, 5]

                    # 중심점 계산
                    centers_x = (xyxy[:, 0] + xyxy[:, 2]) / 2
                    centers_y = (xyxy[:, 1] + xyxy[:, 3]) / 2

                    # 실제 좌표 계산 (모델 출력 512 → original_size로 스케일)
                    actual_x = start_x + centers_x * (self.original_size / self.image_size)
                    actual_y = start_y + centers_y * (self.original_size / self.image_size)

                    for i in range(len(detections)):
                        cell_x = actual_x[i].item()
                        cell_y = actual_y[i].item()

                        # ROI 체크
                        if self.roi_polygons:
                            in_roi = any(p.contains_point(cell_x, cell_y) for p in self.roi_polygons)
                            if not in_roi:
                                continue

                        cells.append({
                            'x': cell_x,
                            'y': cell_y,
                            'cls_id': int(cls_ids[i].item()),
                            'confidence': confs[i].item()
                        })

        except Exception as e:
            print(f"Patch processing error ({start_x}, {start_y}): {e}")

        return cells

    def _count_by_class(self, cells):
        """클래스별 세포 수 카운트"""
        counts = {name: 0 for name in _PDL1_ALL_CLASS_NAMES.values()}
        for cell in cells:
            cls_name = _PDL1_ALL_CLASS_NAMES.get(cell['cls_id'], 'Unknown')
            counts[cls_name] = counts.get(cls_name, 0) + 1
        return counts

    def _calculate_tps(self, cells):
        """
        TPS (Tumor Proportion Score) 계산
        TPS = PD-L1 Positive Tumor / (Positive + Negative Tumor) × 100
        """
        positive = sum(1 for c in cells if c['cls_id'] == 1)
        negative = sum(1 for c in cells if c['cls_id'] == 0)
        total_tumor = positive + negative
        if total_tumor == 0:
            return 0.0
        return (positive / total_tumor) * 100

    def cancel(self):
        self.is_cancelled = True


class PDL1Detection(QObject):
    """PD-L1 세포 검출 클래스 (YOLOv11m 기반)"""

    detectionComplete = pyqtSignal(dict)
    detectionProgress = pyqtSignal(int)
    detectionStatus = pyqtSignal(str)
    detectionError = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.worker = None
        self.model = None
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

        project_root = Path(__file__).parent.parent
        self.default_model_path = project_root / "model" / "PDL1_TPS_detection.pt"

        print(f"PD-L1 Detection device: {self.device}")
        print(f"PD-L1 model path: {self.default_model_path}")

    def load_model(self, model_path=None):
        """모델 로드 (YOLOv11m, 3 classes)"""
        try:
            num_classes = 3
            self.model = nn.yolo_v11_m(num_classes).to(self.device)

            if model_path is None:
                model_path = str(self.default_model_path)

            if not os.path.exists(model_path):
                self.detectionError.emit(f"Model file not found: {model_path}")
                return False

            checkpoint = torch.load(model_path, map_location=self.device, weights_only=False)
            self.model.load_state_dict(checkpoint['model_state_dict'])
            print(f"PD-L1 model loaded: {model_path}")

            self.model.eval()
            return True

        except Exception as e:
            import traceback
            self.detectionError.emit(f"PD-L1 model load failed: {str(e)}")
            traceback.print_exc()
            return False

    def run_detection(self, slide, roi_polygons=None, icc_transform=None, calibration_lut=None, image_path=None):
        """PD-L1 검출 실행"""
        if self.model is None:
            self.detectionError.emit("Model not loaded.")
            return

        if self.worker and self.worker.isRunning():
            print("PD-L1 detection is already running.")
            return

        self.worker = PDL1DetectionWorker(slide, self.model, roi_polygons, self.device,
                                          icc_transform=icc_transform,
                                          calibration_lut=calibration_lut,
                                          image_path=image_path)
        self.worker.finished.connect(self._on_finished)
        self.worker.progress.connect(self._on_progress)
        self.worker.status.connect(self._on_status)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_finished(self, result):
        self.detectionComplete.emit(result)

    def _on_progress(self, progress):
        self.detectionProgress.emit(progress)

    def _on_status(self, status):
        self.detectionStatus.emit(status)

    def _on_error(self, error_msg):
        self.detectionError.emit(error_msg)

    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()

    def unload_model(self):
        if self.model is not None:
            del self.model
            self.model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        import gc
        gc.collect()
        print("PD-L1 model unloaded")

    def is_model_loaded(self):
        return self.model is not None
