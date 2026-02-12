"""
PD-L1 Detection 모듈
병리 이미지에서 PD-L1 양성/음성 종양 세포를 검출하는 AI 기능
YOLOv11m 기반, TPS(Tumor Proportion Score) 계산
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

    def __init__(self, slide, model, roi_polygons=None, device='cuda'):
        super().__init__()
        self.slide = slide
        self.model = model
        self.roi_polygons = roi_polygons
        self.device = device
        self.is_cancelled = False

        self.image_size = 512

        # MPP 정보
        try:
            mpp_x = slide.properties.get('openslide.mpp-x')
            mpp_y = slide.properties.get('openslide.mpp-y')
            if mpp_x and mpp_y:
                self.origin_mpp = (float(mpp_x) + float(mpp_y)) / 2
                print(f"슬라이드 MPP: {self.origin_mpp:.4f} (x={mpp_x}, y={mpp_y})")
            else:
                self.origin_mpp = 0.25
                print(f"MPP 정보 없음, 기본값 사용: {self.origin_mpp}")
        except:
            self.origin_mpp = 0.25
            print(f"MPP 읽기 실패, 기본값 사용: {self.origin_mpp}")

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
        """검출 작업 실행"""
        try:
            import time
            start_total = time.time()

            self.status.emit("PD-L1 검출 시작...")
            self.progress.emit(1)

            all_cells = []
            width, height = self.slide.dimensions

            self.status.emit(f"슬라이드 크기: {width}x{height}")
            self.progress.emit(3)

            # 조직 마스크 생성
            self.status.emit("조직 영역 감지 중... (썸네일 생성)")
            start_mask = time.time()
            thumb_mask = self._create_tissue_mask()
            mask_time = time.time() - start_mask
            self.status.emit(f"조직 마스크 생성 완료 ({mask_time:.2f}s)")
            self.progress.emit(5)

            total_patches = (width // self.original_size) * (height // self.original_size)
            processed_patches = 0
            detected_cells_count = 0
            tissue_patches = 0
            roi_patches = 0

            start_time = time.time()
            last_update_time = start_time

            self.status.emit(f"PD-L1 세포 검출 중... (총 {total_patches}개 패치)")

            for patch_row in range(width // self.original_size - 1):
                if self.is_cancelled:
                    break
                for patch_col in range(height // self.original_size - 1):
                    if self.is_cancelled:
                        break

                    # 마스크 체크 (조직 영역인지)
                    mask_x = (patch_row * self.original_size) // 64
                    mask_y = (patch_col * self.original_size) // 64
                    mask_region = thumb_mask[mask_y:mask_y + self.original_size // 64,
                                            mask_x:mask_x + self.original_size // 64]

                    if np.sum(mask_region) == 0:
                        processed_patches += 1
                        continue

                    tissue_patches += 1
                    patch_x = patch_row * self.original_size
                    patch_y = patch_col * self.original_size

                    # ROI 체크
                    if self.roi_polygons and not self._is_in_roi(patch_x, patch_y):
                        processed_patches += 1
                        continue

                    roi_patches += 1
                    cells = self._process_patch(patch_x, patch_y)
                    all_cells.extend(cells)
                    detected_cells_count = len(all_cells)

                    processed_patches += 1
                    progress = int(5 + (processed_patches / total_patches) * 90)
                    self.progress.emit(progress)

                    # 상태 메시지 업데이트
                    current_time = time.time()
                    if processed_patches % 10 == 0 or (current_time - last_update_time) >= 1.0:
                        elapsed = current_time - start_time
                        patches_per_sec = processed_patches / elapsed if elapsed > 0 else 0
                        remaining = total_patches - processed_patches
                        eta = remaining / patches_per_sec if patches_per_sec > 0 else 0
                        self.status.emit(
                            f"패치 {processed_patches}/{total_patches} | "
                            f"조직:{tissue_patches} ROI:{roi_patches} | "
                            f"세포:{detected_cells_count}개 | {patches_per_sec:.1f}it/s | ETA:{eta:.0f}s"
                        )
                        last_update_time = current_time

            if self.is_cancelled:
                self.error.emit("검출이 취소되었습니다.")
                return

            self.status.emit(f"결과 정리 중... ({detected_cells_count}개 검출)")
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
                'message': f'PD-L1 검출 완료: {len(tumor_cells)}개 종양세포, TPS={tps:.1f}% ({total_time:.1f}s)'
            }

            self.progress.emit(100)
            self.finished.emit(result)

        except Exception as e:
            import traceback
            self.error.emit(f"PD-L1 검출 중 오류: {str(e)}\n{traceback.format_exc()}")

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
            print(f"마스크 생성 실패: {e}")
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
            patch = np.array(patch)[:, :, :3]

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
            print(f"패치 처리 오류 ({start_x}, {start_y}): {e}")

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
                self.detectionError.emit(f"모델 파일을 찾을 수 없습니다: {model_path}")
                return False

            checkpoint = torch.load(model_path, map_location=self.device, weights_only=False)
            self.model.load_state_dict(checkpoint['model_state_dict'])
            print(f"PD-L1 모델 로드 완료: {model_path}")

            self.model.eval()
            return True

        except Exception as e:
            import traceback
            self.detectionError.emit(f"PD-L1 모델 로드 실패: {str(e)}")
            traceback.print_exc()
            return False

    def run_detection(self, slide, roi_polygons=None):
        """PD-L1 검출 실행"""
        if self.model is None:
            self.detectionError.emit("모델이 로드되지 않았습니다.")
            return

        if self.worker and self.worker.isRunning():
            print("이미 PD-L1 검출 작업이 실행 중입니다.")
            return

        self.worker = PDL1DetectionWorker(slide, self.model, roi_polygons, self.device)
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
        print("PD-L1 모델 언로드 완료")

    def is_model_loaded(self):
        return self.model is not None
