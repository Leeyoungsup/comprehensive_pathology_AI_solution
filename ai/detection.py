"""
병변 검출 (Lesion Detection) 모듈
병리 이미지에서 세포를 검출하는 AI 기능
YOLOv11 기반 HnE 세포 검출
"""

import os
import json
import shutil
import xml.etree.ElementTree as ET
from xml.dom import minidom
from glob import glob
from pathlib import Path

import threading
import queue

import numpy as np
import torch
import torchvision
import cv2

from PyQt5.QtCore import QObject, pyqtSignal, QThread

# I/O 워커 스레드별 독립 OpenSlide 객체 (스레드 안전 병렬 읽기)
_patch_thread_local = threading.local()

# AI 모델 경로 설정
AI_ROOT = Path(__file__).parent
NETS_PATH = AI_ROOT / "nets"
UTILS_PATH = AI_ROOT / "utils"

import sys
# AI 폴더를 sys.path에 추가 (nets, utils 접근용)
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from nets import nn


# 클래스 설정
CLASS_NAMES = {
    0: "Neutrophil",
    1: "Epithelial",
    2: "Lymphocyte",
    3: "Plasma",
    4: "Eosinophil",
    5: "Connective tissue",
    6: "Tumor Epithelial",
    7: "Benign Epithelial",
}

CLASS_COLORS = {
    0: "#FF4500",  # Neutrophil - 붉은 주황색
    1: "#00FF00",  # Epithelial - 밝은 녹색
    2: "#0000FF",  # Lymphocyte - 파란색
    3: "#FFFF00",  # Plasma - 밝은 노란색
    4: "#8A2BE2",  # Eosinophil - 청보라
    5: "#808080",  # Connective tissue - 회색
    6: "#FF0000",  # Tumor Epithelial - 빨간색
    7: "#00BFFF",  # Benign Epithelial - 하늘색
}

# RGB 색상 (마스크 생성용)
CLASS_COLORS_RGB = {
    0: (255, 69, 0),     # Neutrophil - 붉은 주황색
    1: (0, 255, 0),      # Epithelial - 밝은 녹색
    2: (0, 0, 255),      # Lymphocyte - 파란색
    3: (255, 255, 0),    # Plasma - 밝은 노란색
    4: (138, 43, 226),   # Eosinophil - 청보라
    5: (128, 128, 128),  # Connective tissue - 회색
    6: (255, 0, 0),      # Tumor Epithelial - 빨간색
    7: (0, 191, 255),    # Benign Epithelial - 하늘색
}


def wh2xy(x):
    """Width-Height를 XY 좌표로 변환"""
    y = x.clone() if isinstance(x, torch.Tensor) else np.copy(x)
    y[:, 0] = x[:, 0] - x[:, 2] / 2  # top left x
    y[:, 1] = x[:, 1] - x[:, 3] / 2  # top left y
    y[:, 2] = x[:, 0] + x[:, 2] / 2  # bottom right x
    y[:, 3] = x[:, 1] + x[:, 3] / 2  # bottom right y
    return y


def non_max_suppression(outputs, confidence_threshold=0.01, iou_threshold=0.35, class_thresholds=None):
    """
    빠른 클래스별 NMS - 성능 최적화 버전
    """
    max_wh = 7680

    bs = outputs.shape[0]
    nc = outputs.shape[1] - 4

    # 빠른 필터링을 위해 가장 낮은 threshold 사용
    min_conf = confidence_threshold
    if class_thresholds:
        min_conf = min(min(class_thresholds.values()), confidence_threshold)

    # 전체 confidence가 낮은 것들 먼저 제거
    xc = outputs[:, 4:4 + nc].amax(1) > min_conf

    # 클래스별 threshold 텐서 사전 구성 (루프 외부에서 1회)
    thresh_t = None
    if class_thresholds:
        thresh_t = torch.full((nc,), confidence_threshold,
                              dtype=torch.float32, device=outputs.device)
        for cid, thr in class_thresholds.items():
            if 0 <= cid < nc:
                thresh_t[cid] = thr

    output = [torch.zeros((0, 6), device=outputs.device)] * bs

    for xi, x in enumerate(outputs):
        x = x.transpose(0, -1)[xc[xi]]

        if not x.shape[0]:
            continue

        # 박스와 클래스 분리
        box, cls = x.split((4, nc), 1)
        box = wh2xy(box)

        # 각 검출의 최고 클래스와 confidence 찾기
        conf, j = cls.max(1, keepdim=True)
        x = torch.cat((box, conf, j.float()), 1)

        # 클래스별 threshold 적용 — 벡터화 (Python 루프 없음)
        if thresh_t is not None:
            cls_idx = x[:, 5].long().clamp(0, nc - 1)
            x = x[x[:, 4] >= thresh_t[cls_idx]]
        else:
            x = x[x[:, 4] > confidence_threshold]
        
        if not x.shape[0]:
            continue
            
        # confidence로 정렬하고 상위 max_nms개만 유지
        x = x[x[:, 4].argsort(descending=True)]
        
        # 빠른 NMS - PyTorch 내장 함수 사용
        c = x[:, 5:6] * max_wh  # 클래스별 offset
        boxes = x[:, :4] + c
        scores = x[:, 4]
        
        # NMS 적용
        keep = torchvision.ops.nms(boxes, scores, iou_threshold)
        
        output[xi] = x[keep]
    
    return output


class DetectionWorker(QThread):
    """병변 검출 작업을 백그라운드에서 수행하는 워커 스레드"""
    
    finished = pyqtSignal(dict)  # 결과 딕셔너리 전달
    progress = pyqtSignal(int)   # 진행률 (0-100)
    error = pyqtSignal(str)      # 에러 메시지
    status = pyqtSignal(str)     # 상태 메시지
    
    def __init__(self, slide, model, roi_polygons=None, device='cuda', auto_classify_epithelial=True, tissue_type="Stomach", image_path=None):
        super().__init__()
        self.slide = slide  # pyvips 또는 openslide 이미지
        self.model = model
        self.roi_polygons = roi_polygons  # ROI 폴리곤 리스트
        self.device = device
        self.is_cancelled = False
        self.auto_classify_epithelial = auto_classify_epithelial  # 자동 Epithelial 재분류
        self.tissue_type = tissue_type  # 조직 타입 (Breast, Stomach, Other)
        self.image_path = image_path  # 병렬 I/O용 슬라이드 경로

        # 설정
        self.image_size = 1024
        
        # MPP 정보 가져오기 (OpenSlide)
        try:
            mpp_x = slide.properties.get('openslide.mpp-x')
            mpp_y = slide.properties.get('openslide.mpp-y')
            if mpp_x and mpp_y:
                self.origin_mpp = (float(mpp_x) + float(mpp_y)) / 2
            else:
                self.origin_mpp = 0.25
        except:
            self.origin_mpp = 0.25
        
        self.output_mpp = 0.5
        self.original_size = int(self.image_size * self.output_mpp / self.origin_mpp)
        self.magnification = self.original_size / self.image_size
        
        # 클래스별 confidence threshold
        self.class_thresholds = {
            0: 0.01,  # Neutrophil
            1: 0.01,  # Epithelial
            2: 0.01,  # Lymphocyte
            3: 0.01,  # Plasma
            4: 0.01,  # Eosinophil
            5: 0.01   # Connective tissue
        }
    
    def run(self):
        """검출 작업 실행"""
        try:
            import time
            start_total = time.time()
            
            self.status.emit("검출 시작...")
            self.progress.emit(1)

            # numpy 청크 누적 (list-of-dicts 대신 사용 → Python GC 압력 제거)
            _chunks_x:    list[np.ndarray] = []
            _chunks_y:    list[np.ndarray] = []
            _chunks_cls:  list[np.ndarray] = []
            _chunks_conf: list[np.ndarray] = []
            
            # 슬라이드 크기 가져오기 (openslide)
            self.status.emit("슬라이드 정보 확인 중...")
            width, height = self.slide.dimensions
            
            self.status.emit(f"슬라이드 크기: {width}x{height}")
            self.progress.emit(3)
            
            # 마스크 생성 (조직 영역만 처리)
            self.status.emit("조직 영역 감지 중... (썸네일 생성)")
            start_mask = time.time()
            thumb_mask = self._create_tissue_mask()
            mask_time = time.time() - start_mask
            self.status.emit(f"조직 마스크 생성 완료 ({mask_time:.2f}s)")
            self.progress.emit(5)
            
            # ── Pre-scan: 조직+ROI 통과 패치 사전 집계 ──
            self.status.emit("유효 패치 수 계산 중...")
            valid_patch_list = []
            for pr in range(width // self.image_size - 1):
                for pc in range(height // self.image_size - 1):
                    mx = (pr * self.image_size) // 64
                    my = (pc * self.image_size) // 64
                    if np.sum(thumb_mask[my:my + self.image_size // 64,
                                        mx:mx + self.image_size // 64]) == 0:
                        continue
                    px, py = pr * self.image_size, pc * self.image_size
                    if self.roi_polygons and not self._is_in_roi(px, py):
                        continue
                    valid_patch_list.append((px, py))

            n_valid = len(valid_patch_list)
            total_grid = (width // self.image_size) * (height // self.image_size)
            self.status.emit(f"유효 패치 {n_valid}개 확인 완료 (전체 {total_grid}개 중)")

            detected_cells_count = 0
            processed_valid = 0

            start_time = time.time()
            last_update_time = start_time

            # ── 배치 병렬처리: I/O 프리페치(멀티스레드) + 배치 GPU 추론 ──
            BATCH_SIZE = 8        # GPU 한 번에 처리할 패치 수
            IO_WORKERS = 4        # 동시 슬라이드 I/O 스레드 수
            PREFETCH_BATCHES = 3  # 큐에 미리 쌓아둘 배치 수 (메모리 상한)

            from concurrent.futures import ThreadPoolExecutor

            prefetch_queue = queue.Queue(maxsize=PREFETCH_BATCHES)
            producer_done = threading.Event()

            def _io_producer():
                """I/O 스레드: 패치 병렬 읽기 → 배치 구성 → 프리페치 큐 삽입"""
                try:
                    with ThreadPoolExecutor(max_workers=IO_WORKERS) as io_pool:
                        pending = []  # [(px, py, future), ...]

                        for px, py in valid_patch_list:
                            if self.is_cancelled:
                                break
                            future = io_pool.submit(self._read_patch_tensor, px, py)
                            pending.append((px, py, future))

                            # 배치가 채워지면 결과를 모아 큐에 삽입
                            if len(pending) >= BATCH_SIZE:
                                batch_coords, batch_tensors = [], []
                                for bx, by, f in pending:
                                    t = f.result(timeout=60)
                                    if t is not None:
                                        batch_coords.append((bx, by))
                                        batch_tensors.append(t)
                                if batch_coords:
                                    # 큐가 가득 차면 블로킹 (메모리 상한 적용)
                                    # 취소 시 블로킹 해제를 위해 타임아웃 폴링
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

                        # 남은 패치 처리 (마지막 부분 배치)
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
                    print(f"I/O 프로듀서 오류: {e}")
                finally:
                    producer_done.set()
                    prefetch_queue.put(None)  # sentinel

            producer_thread = threading.Thread(target=_io_producer, daemon=True)
            producer_thread.start()

            # GPU 추론 루프 (메인 워커 스레드에서 실행)
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
                    # 큐를 비워서 프로듀서 블로킹 해제
                    while True:
                        try:
                            prefetch_queue.get_nowait()
                        except queue.Empty:
                            break
                    break

                batch_coords, batch_tensors, patch_count = item
                bx, by, bcls, bconf = self._infer_batch(batch_coords, batch_tensors)
                k = len(bx)
                if k > 0:
                    _chunks_x.append(bx)
                    _chunks_y.append(by)
                    _chunks_cls.append(bcls)
                    _chunks_conf.append(bconf)
                    detected_cells_count += k

                processed_valid += patch_count
                pct = processed_valid / n_valid if n_valid > 0 else 1.0
                self.progress.emit(int(5 + pct * 45))

                current_time = time.time()
                if current_time - last_update_time >= 1.0:
                    elapsed = current_time - start_time
                    patches_per_sec = processed_valid / elapsed if elapsed > 0 else 0
                    remaining = n_valid - processed_valid
                    eta = remaining / patches_per_sec if patches_per_sec > 0 else 0
                    if eta >= 60:
                        eta_str = f"{int(eta) // 60}분 {int(eta) % 60}초"
                    else:
                        eta_str = f"{int(eta)}초"
                    self.status.emit(
                        f"패치 {processed_valid}/{n_valid} | 세포:{detected_cells_count}개 "
                        f"| {patches_per_sec:.1f}it/s | ~{eta_str} 남음"
                    )
                    last_update_time = current_time

            producer_thread.join(timeout=10)

            if self.is_cancelled:
                self.error.emit("검출이 취소되었습니다.")
                return

            self.status.emit(f"결과 정리 중... ({detected_cells_count}개 검출)")
            self.progress.emit(50)

            # 청크 병합 → 연속 numpy 배열
            import gc
            if _chunks_x:
                all_x    = np.concatenate(_chunks_x)
                all_y    = np.concatenate(_chunks_y)
                all_cls  = np.concatenate(_chunks_cls)
                all_conf = np.concatenate(_chunks_conf)
            else:
                all_x = all_y = all_conf = np.empty(0, dtype=np.float32)
                all_cls = np.empty(0, dtype=np.int32)
            # 청크 리스트 즉시 해제
            del _chunks_x, _chunks_y, _chunks_cls, _chunks_conf
            gc.collect()

            # Epithelial 재분류 (자동 실행) — cls 배열 in-place 수정
            if self.auto_classify_epithelial:
                epithelial_count = int(np.sum(all_cls == 1))
                if epithelial_count > 0:
                    self.status.emit(f"Epithelial 세포 재분류 시작... ({epithelial_count}개)")
                    self._run_epithelial_classification(all_x, all_y, all_cls)
                else:
                    self.status.emit("Epithelial 세포가 없어 재분류를 건너뜁니다.")

            # 결과 정리 (numpy 배열 기반)
            class_counts = self._count_by_class(all_cls)

            # 시각화 다이얼로그용 plot 배열 사전 계산
            plot_arrays = self._build_plot_arrays(all_x, all_y, all_cls, all_conf)

            # JSON 저장 / UI 렌더링용 list-of-dicts 재구성 (1회)
            n_cells = len(all_x)
            all_cells = [
                {'x': float(all_x[i]), 'y': float(all_y[i]),
                 'cls_id': int(all_cls[i]), 'confidence': float(all_conf[i])}
                for i in range(n_cells)
            ]

            result = {
                'status': 'success',
                'cells': all_cells,
                'num_cells': n_cells,
                'class_counts': class_counts,
                'message': f'총 {n_cells}개 세포 검출 완료 (재분류 포함)',
                'seg_mask': getattr(self, 'last_prediction_mask', None),
                'seg_metadata': getattr(self, 'last_seg_metadata', None),
                'seg_class_names': getattr(self, 'last_seg_class_names', None),
                'plot_arrays': plot_arrays,
            }

            self.progress.emit(100)
            self.finished.emit(result)
            
        except Exception as e:
            import traceback
            self.error.emit(f"병변 검출 중 오류 발생: {str(e)}\n{traceback.format_exc()}")
    
    def _create_tissue_mask(self):
        """조직 영역 마스크 생성 (고속 최적화)"""
        try:
            # 더 큰 다운샘플로 빠르게 처리 (64 -> 128)
            downsample = 128
            
            # openslide get_thumbnail
            thumbnail = self.slide.get_thumbnail((self.slide.dimensions[0] // downsample,
                                                  self.slide.dimensions[1] // downsample))
            thumbnail = np.array(thumbnail)
            
            # 그레이스케일 변환 및 이진화
            if len(thumbnail.shape) == 3:
                gray = cv2.cvtColor(thumbnail[:, :, :3], cv2.COLOR_RGB2GRAY)
            else:
                gray = thumbnail
            
            # 빠른 이진화 (작은 커널)
            mask = cv2.threshold(255 - gray, 30, 255, cv2.THRESH_BINARY)[1]
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            
            # 원래 크기로 리사이즈 (64 downsample 기준)
            target_width = self.slide.dimensions[0] // 64
            target_height = self.slide.dimensions[1] // 64
            mask = cv2.resize(mask, (target_width, target_height), interpolation=cv2.INTER_NEAREST)
            
            return mask
            
        except Exception as e:
            print(f"마스크 생성 실패: {e}")
            # 실패 시 전체 영역 처리
            width, height = self.slide.dimensions
            return np.ones((height // 64, width // 64), dtype=np.uint8) * 255
    
    def _is_in_roi(self, patch_x, patch_y):
        """패치가 ROI 영역과 겹치는지 확인 (교차 판정)"""
        if not self.roi_polygons:
            return True
        
        # 패치의 4개 모서리 좌표
        patch_corners = [
            (patch_x, patch_y),  # 좌상
            (patch_x + self.image_size, patch_y),  # 우상
            (patch_x + self.image_size, patch_y + self.image_size),  # 우하
            (patch_x, patch_y + self.image_size)  # 좌하
        ]
        
        # 패치 중심점도 체크
        patch_center_x = patch_x + self.image_size // 2
        patch_center_y = patch_y + self.image_size // 2
        
        for polygon in self.roi_polygons:
            # 중심점이 안에 있는지 체크
            if polygon.contains_point(patch_center_x, patch_center_y):
                return True
            
            # 4개 모서리 중 하나라도 안에 있는지 체크
            for corner_x, corner_y in patch_corners:
                if polygon.contains_point(corner_x, corner_y):
                    return True
        
        return False

    def _read_patch_tensor(self, patch_x, patch_y):
        """
        I/O + CPU 전처리: 패치 읽기 → CPU 텐서 반환 (ThreadPoolExecutor 에서 실행)
        각 스레드가 독립적인 OpenSlide 객체를 사용해 thread-safe 병렬 읽기 보장.

        Returns:
            CPU tensor (C, H, W) float32 [0,1]  또는  None (읽기 실패)
        """
        try:
            if self.image_path:
                # 스레드별 독립 OpenSlide (thread-safe)
                if (not hasattr(_patch_thread_local, 'slide') or
                        _patch_thread_local.image_path != self.image_path):
                    import openslide as _openslide
                    _patch_thread_local.slide = _openslide.OpenSlide(self.image_path)
                    _patch_thread_local.image_path = self.image_path
                slide = _patch_thread_local.slide
            else:
                # image_path 미제공 시 메인 slide 사용 (단일 스레드에서만 안전)
                slide = self.slide

            patch = slide.read_region(
                (patch_x, patch_y), 0, (self.image_size, self.image_size)
            )
            patch = np.array(patch)[:, :, :3]
            patch = cv2.resize(patch, (512, 512))
            # .copy()로 numpy 배열 해제 후에도 텐서가 유효하도록 보장
            return torch.from_numpy(patch.copy()).permute(2, 0, 1).float() / 255.
        except Exception as e:
            print(f"패치 읽기 오류 ({patch_x}, {patch_y}): {e}")
            return None

    def _infer_batch(self, batch_coords, batch_tensors):
        """
        배치 단위 GPU 추론 + 결과 파싱

        Args:
            batch_coords: [(start_x, start_y), ...] 패치 좌상단 WSI 좌표
            batch_tensors: CPU 텐서 리스트 (각 shape: [C, H, W])

        Returns:
            (x, y, cls, conf) — numpy arrays (float32, float32, int32, float32)
            검출이 없으면 길이 0인 빈 배열 반환
        """
        _ef = np.empty(0, dtype=np.float32)
        _ei = np.empty(0, dtype=np.int32)

        batch_xs: list[np.ndarray] = []
        batch_ys: list[np.ndarray] = []
        batch_clss: list[np.ndarray] = []
        batch_confs: list[np.ndarray] = []

        try:
            batch = torch.stack(batch_tensors).to(self.device)  # (B, C, H, W)

            with torch.no_grad():
                with torch.amp.autocast('cuda'):
                    preds = self.model(batch)

            results = non_max_suppression(
                preds,
                confidence_threshold=0.01,
                iou_threshold=0.3,
                class_thresholds=self.class_thresholds,
            )

            # 512 → image_size(1024) → WSI level-0 좌표 스케일
            coord_scale = self.image_size / 512  # = 2.0

            for i, (start_x, start_y) in enumerate(batch_coords):
                if i >= len(results) or len(results[i]) == 0:
                    continue

                detections = results[i]
                xyxy    = detections[:, :4]
                confs_t = detections[:, 4]
                cls_ids = detections[:, 5]

                # GPU 텐서 → numpy (단일 D2H 전송)
                cx_np = ((xyxy[:, 0] + xyxy[:, 2]) / 2 * coord_scale + start_x).cpu().numpy().astype(np.float32)
                cy_np = ((xyxy[:, 1] + xyxy[:, 3]) / 2 * coord_scale + start_y).cpu().numpy().astype(np.float32)
                cls_np  = cls_ids.cpu().numpy().astype(np.int32)
                conf_np = confs_t.cpu().numpy().astype(np.float32)

                if self.roi_polygons:
                    keep = np.array([
                        any(poly.contains_point(float(cx_np[j]), float(cy_np[j]))
                            for poly in self.roi_polygons)
                        for j in range(len(cx_np))
                    ], dtype=bool)
                    cx_np   = cx_np[keep]
                    cy_np   = cy_np[keep]
                    cls_np  = cls_np[keep]
                    conf_np = conf_np[keep]

                if len(cx_np) > 0:
                    batch_xs.append(cx_np)
                    batch_ys.append(cy_np)
                    batch_clss.append(cls_np)
                    batch_confs.append(conf_np)

        except Exception as e:
            import traceback
            print(f"배치 추론 오류: {e}\n{traceback.format_exc()}")

        if not batch_xs:
            return _ef, _ef.copy(), _ei, _ef.copy()

        return (
            np.concatenate(batch_xs),
            np.concatenate(batch_ys),
            np.concatenate(batch_clss),
            np.concatenate(batch_confs),
        )

    def _process_patch(self, start_x, start_y):
        """단일 패치 처리"""
        cells = []
        
        try:
            # 패치 추출 (openslide)
            patch = self.slide.read_region((start_x, start_y), 0,
                                           (self.image_size, self.image_size))
            patch = np.array(patch)[:, :, :3]
            
            # 리사이즈
            patch = cv2.resize(patch[:, :, :3], (512, 512))
            
            # 텐서 변환
            torch_patch = torch.from_numpy(patch).permute(2, 0, 1).unsqueeze(0).float() / 255.
            torch_patch = torch_patch.to(self.device)
            
            # 추론
            self.model.eval()
            with torch.no_grad():
                with torch.amp.autocast('cuda'):
                    pred = self.model(torch_patch)
                
                results = non_max_suppression(pred, confidence_threshold=0.01,
                                             iou_threshold=0.3,
                                             class_thresholds=self.class_thresholds)
                
                if len(results[0]) > 0:
                    detections = results[0]
                    xyxy = detections[:, :4]
                    confs = detections[:, 4]
                    cls_ids = detections[:, 5]
                    
                    # 중심점 계산
                    centers_x = (xyxy[:, 0] + xyxy[:, 2]) / 2
                    centers_y = (xyxy[:, 1] + xyxy[:, 3]) / 2
                    
                    # 실제 좌표 계산
                    actual_x = start_x + centers_x * 2  # magnification
                    actual_y = start_y + centers_y * 2
                    
                    for i in range(len(detections)):
                        cell_x = actual_x[i].item()
                        cell_y = actual_y[i].item()
                        
                        # ROI가 지정된 경우, 세포가 ROI 내부에 있는지 체크
                        if self.roi_polygons:
                            in_roi = False
                            for polygon in self.roi_polygons:
                                if polygon.contains_point(cell_x, cell_y):
                                    in_roi = True
                                    break
                            if not in_roi:
                                continue  # ROI 밖의 세포는 제외
                        
                        cell_data = {
                            'x': cell_x,
                            'y': cell_y,
                            'cls_id': int(cls_ids[i].item()),
                            'confidence': confs[i].item()
                        }
                        cells.append(cell_data)
        
        except Exception as e:
            print(f"패치 처리 오류 ({start_x}, {start_y}): {e}")
        
        return cells
    
    def _count_by_class(self, cls_arr):
        """클래스별 세포 수 카운트 (numpy 배열 입력)"""
        counts = {name: 0 for name in CLASS_NAMES.values()}
        if len(cls_arr) == 0:
            return counts
        max_id = max(CLASS_NAMES.keys()) + 1
        bc = np.bincount(cls_arr, minlength=max_id)
        for cls_id, name in CLASS_NAMES.items():
            if cls_id < len(bc):
                counts[name] = int(bc[cls_id])
        return counts

    def _build_plot_arrays(self, all_x, all_y, all_cls, all_conf):
        """
        시각화 다이얼로그용 numpy 배열 사전 계산 (워커 스레드에서 1회 수행)
        all_x, all_y, all_cls, all_conf는 이미 numpy 배열로 전달됨.

        반환:
            {
                'all_x':          np.ndarray (float32) - 전체 x 좌표
                'all_y':          np.ndarray (float32) - 전체 y 좌표
                'xs_by_class':    {cls_id: np.ndarray} - 클래스별 x 좌표
                'ys_by_class':    {cls_id: np.ndarray} - 클래스별 y 좌표
                'confs_by_class': {cls_id: np.ndarray} - 클래스별 confidence
                'counts_by_id':   {cls_id: int}        - 클래스별 셀 수 (int 키)
                'thumbnail':      np.ndarray | None    - RGB 썸네일 (HxWx3 uint8)
                'thumb_roi_bounds': tuple | None       - 썸네일에 해당하는 WSI ROI (x0,y0,x1,y1)
            }
        """
        if len(all_x) == 0:
            thumbnail, thumb_roi = self._generate_thumbnail_for_plot()
            return {
                'all_x': all_x, 'all_y': all_y,
                'xs_by_class': {}, 'ys_by_class': {}, 'confs_by_class': {},
                'counts_by_id': {},
                'thumbnail': thumbnail, 'thumb_roi_bounds': thumb_roi,
            }

        # 클래스별 분리 (numpy boolean indexing — fromiter 제거)
        unique_cls = np.unique(all_cls).tolist()
        xs_by_class    = {}
        ys_by_class    = {}
        confs_by_class = {}
        counts_by_id   = {}
        for cls_id in unique_cls:
            mask = all_cls == cls_id
            xs_by_class[cls_id]    = all_x[mask]
            ys_by_class[cls_id]    = all_y[mask]
            confs_by_class[cls_id] = all_conf[mask]
            counts_by_id[cls_id]   = int(mask.sum())

        # 썸네일 생성 (best level 사용 → level-0 전체 읽기 병목 제거)
        thumbnail, thumb_roi = self._generate_thumbnail_for_plot()

        return {
            'all_x':            all_x,
            'all_y':            all_y,
            'xs_by_class':      xs_by_class,
            'ys_by_class':      ys_by_class,
            'confs_by_class':   confs_by_class,
            'counts_by_id':     counts_by_id,
            'thumbnail':        thumbnail,
            'thumb_roi_bounds': thumb_roi,
        }

    def _generate_thumbnail_for_plot(self, target_size=600):
        """
        슬라이드 썸네일 생성 — get_best_level_for_downsample 을 사용해
        level-0 전체 읽기 없이 적절한 피라미드 레벨에서 직접 읽는다.

        Returns:
            (thumbnail_np, roi_bounds) 또는 (None, None)
            thumbnail_np: uint8 RGB ndarray (H, W, 3)
            roi_bounds:   (x0, y0, x1, y1) | None
        """
        try:
            if self.roi_polygons:
                all_coords = [p for ann in self.roi_polygons for p in ann.coordinates]
                xs_c = [float(p[0]) for p in all_coords]
                ys_c = [float(p[1]) for p in all_coords]
                rx0, ry0 = int(min(xs_c)), int(min(ys_c))
                rx1, ry1 = int(max(xs_c)), int(max(ys_c))
                region_w, region_h = rx1 - rx0, ry1 - ry0
                if region_w <= 0 or region_h <= 0:
                    raise ValueError("Invalid ROI dimensions")

                scale        = min(target_size / region_w, target_size / region_h)
                downsample   = 1.0 / scale
                best_level   = self.slide.get_best_level_for_downsample(downsample)
                level_ds     = self.slide.level_downsamples[best_level]

                lw = max(1, round(region_w / level_ds))
                lh = max(1, round(region_h / level_ds))

                region = self.slide.read_region((rx0, ry0), best_level, (lw, lh))
                arr    = np.array(region)[:, :, :3]

                new_w = max(1, int(region_w * scale))
                new_h = max(1, int(region_h * scale))
                thumbnail = cv2.resize(arr, (new_w, new_h))
                return thumbnail, (rx0, ry0, rx1, ry1)
            else:
                thumb = self.slide.get_thumbnail((target_size, target_size))
                return np.array(thumb.convert('RGB')), None
        except Exception as e:
            print(f"썸네일 생성 실패: {e}")
            return None, None

    def _run_epithelial_classification(self, x, y, cls_arr):
        """
        Epithelial 세포 재분류 (WSI Segmentation 기반)
        cls_arr를 in-place로 수정한다 (반환값 없음).

        Args:
            x, y:     세포 좌표 numpy 배열 (float32)
            cls_arr:  세포 클래스 numpy 배열 (int32) — in-place 수정됨
            conf:     세포 confidence numpy 배열 (float32)
        """
        try:
            from ai.epithelial_classifier import WSISegmentationModel
            if self.tissue_type == "Other":
                self.status.emit("조직 타입이 'Other'로 설정되어 있어 재분류를 건너뜁니다.")
                return

            self.status.emit("Segmentation 모델 로딩 중...")
            self.progress.emit(52)

            from pathlib import Path
            project_root = Path(__file__).parent.parent
            if self.tissue_type == "Breast":
                model_path = project_root / "model" / "HnE_BR_segmentation.pt"
            elif self.tissue_type == "Stomach":
                model_path = project_root / "model" / "HnE_ST_segmentation.pt"
            else:
                return

            try:
                seg_model = WSISegmentationModel(
                    model_path=str(model_path),
                    model_mpp=1.0,
                    output_mpp=4.0,
                    device=self.device
                )
            except (FileNotFoundError, ImportError) as e:
                self.status.emit(f"Segmentation 모델 로드 실패, 재분류 건너뜀: {str(e)}")
                return

            # ROI bounds 계산 (ROI가 있으면)
            roi_bounds = None
            if self.roi_polygons:
                min_x = float('inf');  min_y = float('inf')
                max_x = float('-inf'); max_y = float('-inf')
                for polygon in self.roi_polygons:
                    coords = polygon.coordinates
                    xs_ = [p[0] for p in coords]
                    ys_ = [p[1] for p in coords]
                    min_x = min(min_x, min(xs_)); min_y = min(min_y, min(ys_))
                    max_x = max(max_x, max(xs_)); max_y = max(max_y, max(ys_))
                roi_bounds = (int(min_x), int(min_y), int(max_x), int(max_y))

            self.status.emit("WSI Segmentation 실행 중...")

            def progress_callback(progress_pct):
                self.progress.emit(55 + int(progress_pct * 0.35))

            def seg_status_callback(msg):
                self.status.emit(msg)

            prediction_mask, metadata = seg_model.predict_wsi(
                self.slide,
                patch_size=512,
                overlap_ratio=0.4,
                batch_size=8,
                progress_callback=progress_callback,
                status_callback=seg_status_callback,
                roi_bounds=roi_bounds
            )

            self.last_prediction_mask = prediction_mask
            self.last_seg_metadata = metadata
            self.last_seg_class_names = seg_model.class_names

            self.status.emit("Epithelial 세포 재분류 중...")
            self.progress.emit(92)

            wsi_mpp = self.origin_mpp
            output_mpp = seg_model.output_mpp
            scale_factor = wsi_mpp / output_mpp
            region_offset_x = metadata.get('region_offset', (0, 0))[0]
            region_offset_y = metadata.get('region_offset', (0, 0))[1]

            # 1단계: Epithelial 인덱스 및 mask 좌표 (numpy 벡터화)
            epi_indices = np.where(cls_arr == 1)[0]
            if len(epi_indices) == 0:
                return

            epi_xs = x[epi_indices]
            epi_ys = y[epi_indices]
            mxs = ((epi_xs - region_offset_x) * scale_factor).astype(np.int32)
            mys = ((epi_ys - region_offset_y) * scale_factor).astype(np.int32)
            h, w = prediction_mask.shape
            valid = (mxs >= 0) & (mxs < w) & (mys >= 0) & (mys < h)
            seg_vals = np.zeros(len(epi_indices), dtype=np.int32)
            seg_vals[valid] = prediction_mask[mys[valid], mxs[valid]]

            # 2단계: connected component 클러스터링
            from scipy import ndimage as ndi
            TUMOR_RATIO_THRESHOLD = 0.1
            epi_region = np.isin(prediction_mask, [2, 3]).astype(np.uint8)
            labeled_mask, num_components = ndi.label(epi_region, structure=np.ones((3, 3), dtype=np.int8))

            # 3단계: 컴포넌트별 Tumor 픽셀 비율 — bincount
            flat_label = labeled_mask.ravel()
            flat_mask  = prediction_mask.ravel().astype(np.int32)
            n_bins = num_components + 1
            tumor_counts = np.bincount(flat_label, weights=(flat_mask == 3), minlength=n_bins)
            total_counts = np.bincount(flat_label, weights=np.isin(flat_mask, [2, 3]).astype(float), minlength=n_bins)
            with np.errstate(invalid='ignore', divide='ignore'):
                tumor_ratio = np.where(total_counts > 0, tumor_counts / total_counts, 0.0)
            comp_class_arr = np.where(tumor_ratio >= TUMOR_RATIO_THRESHOLD, 3, 2).astype(np.int32)
            comp_class_arr[0] = 0  # background

            # 세포 좌표 → 컴포넌트 ID → 관 타입 (mxs/mys 재사용)
            lh, lw = labeled_mask.shape
            lvalid = (mxs >= 0) & (mxs < lw) & (mys >= 0) & (mys < lh)
            comp_ids = np.zeros(len(epi_indices), dtype=np.int32)
            comp_ids[lvalid] = labeled_mask[mys[lvalid], mxs[lvalid]]
            update_mask = comp_ids > 0
            seg_vals[update_mask] = comp_class_arr[comp_ids[update_mask]]

            # 4단계: cls_arr in-place 업데이트 (2=Benign→7, else Tumor→6)
            cls_arr[epi_indices] = np.where(seg_vals == 2, 7, 6).astype(np.int32)

            self.status.emit(f"Epithelial 재분류 완료 ({len(epi_indices)}개)")
            self.progress.emit(98)

            del seg_model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        except Exception as e:
            import traceback
            print(f"Epithelial 재분류 실패: {e}\n{traceback.format_exc()}")
            self.status.emit(f"재분류 실패, 원본 결과 사용: {str(e)}")

    def cancel(self):
        """작업 취소"""
        self.is_cancelled = True


class CellDetection(QObject):
    """
    세포 검출 클래스
    병리 이미지에서 세포를 검출하는 YOLOv11 기반 AI
    """
    
    detectionComplete = pyqtSignal(dict)
    detectionProgress = pyqtSignal(int)
    detectionStatus = pyqtSignal(str)
    detectionError = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.worker = None
        self.model = None
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        
        # 기본 모델 경로 설정 (프로젝트 루트/model/HnE_detection.pt)
        project_root = Path(__file__).parent.parent
        self.default_model_path = project_root / "model" / "HnE_detection.pt"
        
    
    def load_model(self, model_path=None):
        """
        AI 모델 로드
        
        Args:
            model_path: 모델 파일 경로 (None이면 기본 경로 사용)
        
        Returns:
            bool: 로드 성공 여부
        """
        try:
            # YOLO 모델은 원래 6개 클래스로 학습됨
            # 새로운 3개 클래스(Tumor/NT/Stroma-epithelial)는 재분류 단계에서 생성
            num_classes = 6  # 원본 YOLO 모델 클래스 수
            self.model = nn.yolo_v11_m(num_classes).to(self.device)
            
            # 경로가 지정되지 않으면 기본 경로 사용
            if model_path is None:
                model_path = str(self.default_model_path)
            
            if model_path:
                if not os.path.exists(model_path):
                    error_msg = f"모델 파일을 찾을 수 없습니다: {model_path}"
                    self.detectionError.emit(error_msg)
                    return False

                checkpoint = torch.load(model_path, map_location=self.device, weights_only=False)
                self.model.load_state_dict(checkpoint['model_state_dict'])
            
            self.model.eval()
            return True
            
        except Exception as e:
            self.detectionError.emit(f"모델 로드 실패: {str(e)}")
            return False
    
    def run_detection(self, slide, roi_polygons=None, auto_classify_epithelial=True, tissue_type="Stomach", image_path=None):
        """
        세포 검출 실행

        Args:
            slide: pyvips 또는 openslide 이미지 객체
            roi_polygons: ROI Annotation 리스트 (선택사항)
            auto_classify_epithelial: Epithelial 자동 재분류 여부 (기본값: True)
            tissue_type: 조직 타입 (Breast, Stomach, Other)
            image_path: WSI 파일 경로 (병렬 I/O 활성화, None이면 단일 슬라이드 사용)
        """
        if self.model is None:
            self.detectionError.emit("모델이 로드되지 않았습니다.")
            return

        if self.worker and self.worker.isRunning():
            return

        self.worker = DetectionWorker(slide, self.model, roi_polygons, self.device,
                                       auto_classify_epithelial=auto_classify_epithelial,
                                       tissue_type=tissue_type,
                                       image_path=image_path)
        self.worker.finished.connect(self._on_finished)
        self.worker.progress.connect(self._on_progress)
        self.worker.status.connect(self._on_status)
        self.worker.error.connect(self._on_error)
        self.worker.start()
    
    def _on_finished(self, result):
        """검출 완료 시 호출"""
        self.detectionComplete.emit(result)
    
    def _on_progress(self, progress):
        """진행률 업데이트 시 호출"""
        self.detectionProgress.emit(progress)
    
    def _on_status(self, status):
        """상태 메시지 업데이트 시 호출"""
        self.detectionStatus.emit(status)
    
    def _on_error(self, error_msg):
        """에러 발생 시 호출"""
        self.detectionError.emit(error_msg)
    
    def cancel(self):
        """실행 중인 작업 취소"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
    
    def unload_model(self):
        """모델 언로드 및 GPU 리소스 해제"""
        if self.model is not None:
            del self.model
            self.model = None
        
        # GPU 캐시 정리
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        
        import gc
        gc.collect()
    
    def is_model_loaded(self):
        """모델이 로드되어 있는지 확인"""
        return self.model is not None


def save_results_to_xml(cells, output_path):
    """
    검출 결과를 ASAP XML 형식으로 저장
    
    Args:
        cells: 검출된 세포 리스트
        output_path: 출력 XML 파일 경로
    """
    root = ET.Element("ASAP_Annotations")
    annotations = ET.SubElement(root, "Annotations")
    
    for i, cell in enumerate(cells):
        cls_id = cell.get('cls_id', 0)
        
        annotation = ET.SubElement(annotations, "Annotation")
        annotation.set("Name", f"Annotation {i}")
        annotation.set("Type", "Dot")
        annotation.set("PartOfGroup", CLASS_NAMES.get(cls_id, f"Class_{cls_id}"))
        annotation.set("Color", CLASS_COLORS.get(cls_id, "#FFFFFF"))
        
        coordinates = ET.SubElement(annotation, "Coordinates")
        coordinate = ET.SubElement(coordinates, "Coordinate")
        coordinate.set("Order", "0")
        coordinate.set("X", str(float(cell['x'])))
        coordinate.set("Y", str(float(cell['y'])))
    
    # AnnotationGroups 생성
    annotation_groups = ET.SubElement(root, "AnnotationGroups")
    for cls_id, class_name in CLASS_NAMES.items():
        group = ET.SubElement(annotation_groups, "Group")
        group.set("Name", class_name)
        group.set("PartOfGroup", "None")
        group.set("Color", CLASS_COLORS.get(cls_id, "#FFFFFF"))
        ET.SubElement(group, "Attributes")
    
    # XML 저장
    rough_string = ET.tostring(root, 'unicode')
    reparsed = minidom.parseString(rough_string)
    pretty_xml = reparsed.toprettyxml(indent="\t")
    
    lines = pretty_xml.split('\n')
    lines[0] = '<?xml version="1.0"?>'
    pretty_xml = '\n'.join(lines[1:])
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(pretty_xml)
    
    print(f"XML 저장 완료: {output_path}")


class DetectionOverlay:
    """
    검출 결과를 마스크 이미지로 생성하여 오버레이하는 클래스
    각 세포를 개별 포인트로 그리는 대신 마스크 이미지를 사용하여 리소스 절약
    """
    
    def __init__(self, image_width, image_height, downsample=64, color_map=None):
        """
        Args:
            image_width: 원본 이미지 너비 (레벨 0)
            image_height: 원본 이미지 높이 (레벨 0)
            downsample: 다운샘플 비율 (기본 64배 축소)
            color_map: 커스텀 색상맵 (None이면 CLASS_COLORS_RGB 사용)
        """
        self.image_width = image_width
        self.image_height = image_height
        self.downsample = downsample
        self.color_map = color_map

        # 마스크 크기 계산
        self.mask_width = image_width // downsample
        self.mask_height = image_height // downsample

        # RGBA 마스크 이미지 (투명 배경)
        self.mask = np.zeros((self.mask_height, self.mask_width, 4), dtype=np.uint8)

        # 클래스별 가시성
        self.class_visibility = {cls_id: True for cls_id in CLASS_NAMES.keys()}
        
        # 점 크기 (마스크 좌표 기준)
        self.point_radius = 10
    
    def clear(self):
        """마스크 초기화"""
        self.mask = np.zeros((self.mask_height, self.mask_width, 4), dtype=np.uint8)
    
    def add_cells(self, cells, alpha=180):
        """
        검출된 세포들을 마스크에 추가
        
        Args:
            cells: 세포 리스트 [{'x': x, 'y': y, 'cls_id': cls_id, 'confidence': conf}, ...]
            alpha: 투명도 (0-255, 기본 180)
        """
        for cell in cells:
            cls_id = cell.get('cls_id', 0)
            
            # 가시성 체크
            if not self.class_visibility.get(cls_id, True):
                continue
            
            # 마스크 좌표로 변환
            mask_x = int(cell['x'] / self.downsample)
            mask_y = int(cell['y'] / self.downsample)
            
            # 범위 체크
            if 0 <= mask_x < self.mask_width and 0 <= mask_y < self.mask_height:
                # 색상 가져오기
                active_colors = self.color_map if self.color_map else CLASS_COLORS_RGB
                color = active_colors.get(cls_id, (255, 255, 255))

                # 원 그리기 (RGBA) - 테두리만 (속이 빈 원)
                cv2.circle(self.mask, (mask_x, mask_y), self.point_radius,
                          (color[0], color[1], color[2], alpha), 3)  # 3 = 선 두께
    
    def set_class_visibility(self, cls_id, visible):
        """특정 클래스의 가시성 설정"""
        self.class_visibility[cls_id] = visible
    
    def set_all_visibility(self, visible):
        """모든 클래스의 가시성 설정"""
        for cls_id in self.class_visibility:
            self.class_visibility[cls_id] = visible
    
    def get_mask_image(self):
        """마스크 이미지 반환 (numpy RGBA)"""
        return self.mask
    
    def get_qpixmap(self):
        """QPixmap으로 변환하여 반환"""
        from PyQt5.QtGui import QImage, QPixmap
        
        # numpy RGBA -> QImage
        height, width, channels = self.mask.shape
        bytes_per_line = channels * width
        
        qimage = QImage(self.mask.data, width, height, bytes_per_line, QImage.Format_RGBA8888)
        return QPixmap.fromImage(qimage)
    
    def get_scaled_qpixmap(self, target_width, target_height):
        """지정된 크기로 스케일된 QPixmap 반환"""
        from PyQt5.QtCore import Qt
        
        pixmap = self.get_qpixmap()
        return pixmap.scaled(target_width, target_height,
                            Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    
    def rebuild_mask(self, cells, alpha=180):
        """마스크를 다시 빌드 (가시성 변경 후 사용)"""
        self.clear()
        self.add_cells(cells, alpha)


class SpatialGrid:
    """
    공간 격자 인덱스 — 셀 좌표를 격자(grid)에 미리 분류하여
    특정 영역의 셀을 O(1)에 조회 (전체 순회 O(N) 제거)
    """

    def __init__(self, grid_size=2048):
        self.grid_size = grid_size
        self.grid = {}  # (gx, gy) -> [cell, ...]

    def build(self, cells):
        """셀 리스트로 격자 인덱스 구축 (numpy argsort 가속)

        기존 Python dict 루프(O(N) 순차) 대신 numpy로 gx/gy를 일괄 계산 후
        argsort 기반 groupby를 수행 → 약 10배 속도 향상.
        """
        self.grid.clear()
        n = len(cells)
        if n == 0:
            return

        gs = self.grid_size

        # 모든 셀의 x, y 좌표를 numpy 배열로 추출
        xs = np.fromiter((c['x'] for c in cells), dtype=np.float64, count=n)
        ys = np.fromiter((c['y'] for c in cells), dtype=np.float64, count=n)

        gxs = xs.astype(np.int64) // gs
        gys = ys.astype(np.int64) // gs

        # (gx, gy) → 단일 int64 키로 인코딩 (WSI 좌표는 항상 양수)
        keys = gxs * 65536 + gys

        # 키 기준 정렬 (stable: 원래 순서 유지)
        order = np.argsort(keys, kind='stable')
        sorted_keys = keys[order]

        # 키가 바뀌는 지점이 그룹 경계
        boundaries = np.concatenate(([0], np.flatnonzero(np.diff(sorted_keys)) + 1, [n]))

        new_grid = {}
        for i in range(len(boundaries) - 1):
            start = int(boundaries[i])
            end   = int(boundaries[i + 1])
            kv    = int(sorted_keys[start])
            gx    = kv >> 16          # kv // 65536
            gy    = kv & 0xFFFF       # kv % 65536
            # order[start:end]의 원본 인덱스 → 셀 리스트 구성
            new_grid[(gx, gy)] = [cells[j] for j in order[start:end].tolist()]

        self.grid = new_grid

    def clear(self):
        self.grid.clear()

    def query(self, x_min, y_min, x_max, y_max):
        """영역 내 셀 리스트 반환 (격자 단위로 빠르게 필터링)"""
        gs = self.grid_size
        gx_min = int(x_min) // gs
        gy_min = int(y_min) // gs
        gx_max = int(x_max) // gs
        gy_max = int(y_max) // gs

        result = []
        for gx in range(gx_min, gx_max + 1):
            for gy in range(gy_min, gy_max + 1):
                bucket = self.grid.get((gx, gy))
                if bucket:
                    for cell in bucket:
                        cx, cy = cell['x'], cell['y']
                        if x_min <= cx < x_max and y_min <= cy < y_max:
                            result.append(cell)
        return result


class TiledDetectionOverlay:
    """
    타일 기반 검출 결과 오버레이
    대용량 이미지에서 현재 뷰에 해당하는 영역만 마스크 생성
    SpatialGrid를 이용한 공간 인덱싱으로 대량 셀에서도 빠른 렌더링
    """

    def __init__(self, tile_size=512, color_map=None):
        self.tile_size = tile_size
        self.cells = []
        self.spatial_grid = SpatialGrid(grid_size=2048)
        self.class_visibility = {cls_id: True for cls_id in CLASS_NAMES.keys()}
        self.color_map = color_map  # 커스텀 색상맵 (None이면 CLASS_COLORS_RGB 사용)
        self.point_radius = 16
        self.alpha = 180
        self._heatmap_cache = None  # 사전 계산된 density 그리드 캐시

    def set_cells(self, cells, color_map=None):
        """검출된 세포 리스트 설정 및 공간 인덱스 구축"""
        self.cells = cells
        self.spatial_grid.build(cells)
        if color_map is not None:
            self.color_map = color_map
            self.class_visibility = {cls_id: True for cls_id in color_map.keys()}
        self._build_heatmap_cache()

    def clear_cells(self):
        """세포 리스트 초기화"""
        self.cells = []
        self.spatial_grid.clear()
        self._heatmap_cache = None

    def set_class_visibility(self, cls_id, visible):
        """특정 클래스의 가시성 설정 (캐시 재계산 불필요 - create_heatmap_mask에서 합산)"""
        self.class_visibility[cls_id] = visible

    def _build_heatmap_cache(self, grid_size=2048):
        """클래스별 density 그리드를 미리 계산하여 캐시 (set_cells 시 1회만 실행)"""
        if not self.cells:
            self._heatmap_cache = None
            return

        xs_all = np.array([c['x'] for c in self.cells], dtype=np.float64)
        ys_all = np.array([c['y'] for c in self.cells], dtype=np.float64)

        x_min, x_max = float(xs_all.min()), float(xs_all.max())
        y_min, y_max = float(ys_all.min()), float(ys_all.max())
        span_w = max(x_max - x_min, 1.0)
        span_h = max(y_max - y_min, 1.0)

        # 종횡비 유지한 그리드 크기
        if span_w >= span_h:
            gw = grid_size
            gh = max(1, int(grid_size * span_h / span_w))
        else:
            gh = grid_size
            gw = max(1, int(grid_size * span_w / span_h))

        hist_range = [[y_min, y_max + 1e-6], [x_min, x_max + 1e-6]]

        # 클래스별 density 그리드 누적 (blur 없이 raw count 저장)
        cls_densities = {}
        for cls_id in set(c.get('cls_id', 0) for c in self.cells):
            cls_cells = [c for c in self.cells if c.get('cls_id', 0) == cls_id]
            xs = np.array([c['x'] for c in cls_cells], dtype=np.float64)
            ys = np.array([c['y'] for c in cls_cells], dtype=np.float64)
            density, _, _ = np.histogram2d(ys, xs, bins=[gh, gw], range=hist_range)
            cls_densities[cls_id] = density.astype(np.float32)

        self._heatmap_cache = {
            'cls_densities': cls_densities,
            'x_min': x_min, 'y_min': y_min,
            'x_max': x_max, 'y_max': y_max,
            'gw': gw, 'gh': gh,
            'sx': gw / span_w,
            'sy': gh / span_h,
        }

    def create_tile_mask(self, tile_x, tile_y, tile_width, tile_height, downsample=1):
        """
        특정 타일 영역의 마스크 생성 (numpy 벡터화로 cv2.circle 루프 제거)

        원형 오프셋 템플릿을 미리 계산한 뒤 모든 셀 좌표에 numpy 브로드캐스팅으로
        한 번에 붙여넣어 개당 Python→C++ 왕복 오버헤드를 없앤다.
        """
        mask_width  = tile_width  // downsample
        mask_height = tile_height // downsample

        tile_end_x = tile_x + tile_width
        tile_end_y = tile_y + tile_height

        visible_cells = self.spatial_grid.query(tile_x, tile_y, tile_end_x, tile_end_y)
        if not visible_cells:
            return None

        r             = max(2, int(self.point_radius / downsample))
        line_thickness = max(2, int(5 // downsample))
        inner_r       = max(0, r - line_thickness)

        # 원형 링 오프셋 템플릿 사전 계산 (hollow circle)
        oy, ox = np.mgrid[-r:r + 1, -r:r + 1]
        d_sq = oy ** 2 + ox ** 2
        ring  = (d_sq <= r * r) if inner_r == 0 else (d_sq <= r * r) & (d_sq > inner_r * inner_r)
        tdy   = oy[ring].ravel()   # shape: (K,)
        tdx   = ox[ring].ravel()   # shape: (K,)

        active_colors = self.color_map if self.color_map else CLASS_COLORS_RGB

        # 클래스별로 (mx, my) 목록을 모아 한 번에 처리
        cls_mxs = {}
        cls_mys = {}
        for cell in visible_cells:
            cls_id = cell.get('cls_id', 0)
            if not self.class_visibility.get(cls_id, True):
                continue
            mx = (cell['x'] - tile_x) / downsample
            my = (cell['y'] - tile_y) / downsample
            if cls_id not in cls_mxs:
                cls_mxs[cls_id] = []
                cls_mys[cls_id] = []
            cls_mxs[cls_id].append(mx)
            cls_mys[cls_id].append(my)

        if not cls_mxs:
            return None

        mask = np.zeros((mask_height, mask_width, 4), dtype=np.uint8)
        cell_count = 0

        for cls_id in cls_mxs:
            color = active_colors.get(cls_id, (255, 255, 255))
            rgba  = np.array([color[0], color[1], color[2], self.alpha], dtype=np.uint8)

            mxs = np.round(cls_mxs[cls_id]).astype(np.int32)  # (N,)
            mys = np.round(cls_mys[cls_id]).astype(np.int32)

            # 브로드캐스팅: (N, K) → 전체 픽셀 좌표
            all_px = (mxs[:, np.newaxis] + tdx[np.newaxis, :]).ravel()
            all_py = (mys[:, np.newaxis] + tdy[np.newaxis, :]).ravel()

            valid  = (all_px >= 0) & (all_px < mask_width) & \
                     (all_py >= 0) & (all_py < mask_height)
            all_px = all_px[valid]
            all_py = all_py[valid]

            if len(all_px):
                mask[all_py, all_px] = rgba
            cell_count += len(mxs)

        return mask if cell_count > 0 else None

    def create_view_mask(self, view_rect, downsample=1):
        """현재 뷰 영역의 마스크 생성"""
        from PyQt5.QtGui import QImage, QPixmap

        x = int(view_rect.x())
        y = int(view_rect.y())
        width = int(view_rect.width())
        height = int(view_rect.height())

        mask = self.create_tile_mask(x, y, width, height, downsample)

        if mask is None:
            return None, x, y

        h, w, c = mask.shape
        bytes_per_line = c * w
        qimage = QImage(mask.data, w, h, bytes_per_line, QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimage)

        return pixmap, x, y

    def create_heatmap_mask(self, view_rect, heatmap_size=512):
        """저배율 LOD용 히트맵 마스크 생성 (사전 계산된 캐시 사용)

        _build_heatmap_cache()에서 미리 계산된 전체 슬라이드 density 그리드를
        현재 뷰 영역으로 crop + resize하여 반환 → 세포 수에 관계없이 O(1) 속도.

        Returns:
            (QPixmap | None, x, y, scale)
            scale: scene units per heatmap pixel (setScale에 사용)
        """
        from PyQt5.QtGui import QImage, QPixmap

        x = int(view_rect.x())
        y = int(view_rect.y())
        width = int(view_rect.width())
        height = int(view_rect.height())

        if width <= 0 or height <= 0:
            return None, x, y, 1.0

        cache = self._heatmap_cache
        if cache is None:
            return None, x, y, 1.0

        cls_densities = cache['cls_densities']
        x_min, y_min = cache['x_min'], cache['y_min']
        gw, gh = cache['gw'], cache['gh']
        sx, sy = cache['sx'], cache['sy']

        # view_rect를 density 그리드 인덱스로 변환
        gx0c = max(0, int((x - x_min) * sx))
        gy0c = max(0, int((y - y_min) * sy))
        gx1c = min(gw, int((x + width - x_min) * sx) + 1)
        gy1c = min(gh, int((y + height - y_min) * sy) + 1)

        if gx1c <= gx0c or gy1c <= gy0c:
            return None, x, y, 1.0

        # 가시 클래스만 crop 후 합산 (작은 영역에서 연산 → 빠름)
        combined = None
        for cls_id, density in cls_densities.items():
            if not self.class_visibility.get(cls_id, True):
                continue
            crop = density[gy0c:gy1c, gx0c:gx1c]
            if combined is None:
                combined = crop.copy()
            else:
                combined += crop

        if combined is None or combined.max() == 0:
            return None, x, y, 1.0

        # heatmap_size 해상도로 리사이즈
        crop_h, crop_w = combined.shape
        target_w = heatmap_size
        target_h = max(1, int(heatmap_size * crop_h / crop_w))
        if crop_w != target_w or crop_h != target_h:
            combined = cv2.resize(combined, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

        # Gaussian blur (리사이즈 후 512 크기에서 → 빠름)
        sigma = max(3.0, target_w / 60.0)
        combined = cv2.GaussianBlur(combined, (0, 0), sigma)

        max_val = float(combined.max())
        if max_val == 0:
            return None, x, y, 1.0

        # 로컬 정규화 (뷰 내 상대 밀도)
        density_norm = (combined / max_val * 255).astype(np.uint8)

        # 컬러맵 적용 (COLORMAP_HOT: 검정→빨강→노랑→흰색)
        colored_bgr = cv2.applyColorMap(density_norm, cv2.COLORMAP_HOT)
        colored_rgb = cv2.cvtColor(colored_bgr, cv2.COLOR_BGR2RGB)

        # 알파: 밀도에 비례 (배경은 투명)
        alpha_mask = np.clip(
            density_norm.astype(np.float32) * (self.alpha / 255.0), 0, 255
        ).astype(np.uint8)

        hm_h, hm_w = density_norm.shape
        mask = np.zeros((hm_h, hm_w, 4), dtype=np.uint8)
        mask[:, :, 0] = colored_rgb[:, :, 0]
        mask[:, :, 1] = colored_rgb[:, :, 1]
        mask[:, :, 2] = colored_rgb[:, :, 2]
        mask[:, :, 3] = alpha_mask

        bytes_per_line = 4 * hm_w
        qimage = QImage(mask.data, hm_w, hm_h, bytes_per_line, QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimage.copy())

        # scale: crop이 커버하는 scene 너비 / 출력 픽셀 수
        scene_w_covered = (gx1c - gx0c) / sx
        scale = scene_w_covered / hm_w

        # 실제 crop 시작점의 scene 좌표 (클램핑으로 인해 x와 다를 수 있음)
        actual_x = x_min + gx0c / sx
        actual_y = y_min + gy0c / sy

        return pixmap, actual_x, actual_y, scale

    def get_cells_in_region(self, x, y, width, height):
        """특정 영역 내의 세포 리스트 반환"""
        return self.spatial_grid.query(x, y, x + width, y + height)


# 기존 호환성을 위한 별칭
LesionDetection = CellDetection
