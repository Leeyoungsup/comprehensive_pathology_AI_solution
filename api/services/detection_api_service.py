"""
Detection API 서비스

PyQt5 의존 없이 AI 모듈(detection, segmentation, epithelial_classifier)을
직접 호출하여 검출·재분류를 수행하는 서비스 레이어.

- 모델 로드/언로드
- 동기/비동기 검출 파이프라인
- 진행률 콜백 → TaskState 업데이트
"""

from __future__ import annotations

import gc
import os
import queue
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
import torch
import torchvision

# openslide는 지연 import (DLL 경로 설정 후 사용)
openslide = None

def _ensure_openslide():
    """OpenSlide 모듈 지연 로드 (main.py에서 DLL 경로 설정 후 호출)"""
    global openslide
    if openslide is None:
        import openslide as _openslide
        openslide = _openslide
    return openslide

# 프로젝트 루트(ai/, model/ 가 있는 곳)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# I/O 워커용 스레드-로컬 OpenSlide 객체
_patch_thread_local = threading.local()


# ============================================================================
# Helper: 프로젝트의 ai 모듈 재사용
# ============================================================================

def _import_nn():
    """ai.nets.nn 모듈 import (모델 아키텍처)"""
    from ai.nets import nn
    return nn


def _import_nms():
    """ai.detection 의 NMS 함수 import"""
    from ai.detection import non_max_suppression, wh2xy, CLASS_NAMES, CLASS_COLORS
    return non_max_suppression, wh2xy, CLASS_NAMES, CLASS_COLORS


def _import_seg_model():
    """ai.epithelial_classifier 의 WSISegmentationModel import"""
    from ai.epithelial_classifier import WSISegmentationModel
    return WSISegmentationModel


# ============================================================================
# ROI Polygon helper (QPointF 없이)
# ============================================================================

class SimplePolygon:
    """ROI polygon — contains_point 만 제공 (ray-casting)"""

    def __init__(self, coordinates: List[List[float]]):
        self.coordinates = [(float(c[0]), float(c[1])) for c in coordinates]

    def contains_point(self, px: float, py: float) -> bool:
        n = len(self.coordinates)
        if n < 3:
            return False
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = self.coordinates[i]
            xj, yj = self.coordinates[j]
            if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi):
                inside = not inside
            j = i
        return inside


def build_roi_polygons(roi_list: List[dict]) -> List[SimplePolygon]:
    """ROI JSON 배열 → SimplePolygon 리스트로 변환"""
    polygons = []
    for item in roi_list:
        roi_type = item.get("type", "Polygon")
        if roi_type == "Rectangle":
            x = float(item["x"])
            y = float(item["y"])
            w = float(item["width"])
            h = float(item["height"])
            coords = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
            polygons.append(SimplePolygon(coords))
        else:
            coords = item.get("coordinates", [])
            if coords:
                polygons.append(SimplePolygon(coords))
    return polygons


# ============================================================================
# Detection API Service
# ============================================================================

class DetectionAPIService:
    """
    Detection + Segmentation + Epithelial 재분류 파이프라인 (비-Qt)

    모델 인스턴스를 싱글턴으로 유지하며,
    여러 요청이 순차적/병렬로 detect() 호출 가능.
    """

    def __init__(self):
        self._device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        self._model = None            # YOLOv11m detection model
        self._model_lock = threading.Lock()  # 모델 로드/사용 동기화

        # 기본 경로
        self._detection_model_path = PROJECT_ROOT / "model" / "HnE_detection.pt"
        self._seg_breast_path = PROJECT_ROOT / "model" / "HnE_BR_segmentation.pt"
        self._seg_stomach_path = PROJECT_ROOT / "model" / "HnE_ST_segmentation.pt"

        # Detection 설정
        self.image_size = 1024
        self.output_mpp = 0.5
        self.batch_size = 8
        self.io_workers = 4

    # ------------------------------------------------------------------
    # Model Management
    # ------------------------------------------------------------------

    def load_detection_model(self, model_path: Optional[str] = None) -> bool:
        """Detection 모델 로드"""
        with self._model_lock:
            try:
                nn = _import_nn()
                self._model = nn.yolo_v11_m(6).to(self._device)

                path = Path(model_path) if model_path else self._detection_model_path
                if not path.exists():
                    raise FileNotFoundError(f"모델 파일 없음: {path}")

                ckpt = torch.load(str(path), map_location=self._device, weights_only=False)
                self._model.load_state_dict(ckpt["model_state_dict"])
                self._model.eval()
                return True
            except Exception as e:
                print(f"Detection 모델 로드 실패: {e}")
                self._model = None
                return False

    def unload_detection_model(self):
        """Detection 모델 언로드"""
        with self._model_lock:
            if self._model is not None:
                del self._model
                self._model = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
            gc.collect()

    @property
    def is_detection_model_loaded(self) -> bool:
        return self._model is not None

    def get_device_str(self) -> str:
        return str(self._device)

    # ------------------------------------------------------------------
    # Model Info
    # ------------------------------------------------------------------

    def get_model_info(self) -> List[Dict[str, Any]]:
        """사용 가능한 모델 목록"""
        _, _, CLASS_NAMES, _ = _import_nms()
        device_str = str(self._device) if self._model else None
        models = [
            {
                "id": "hne_detection",
                "name": "HnE Cell Detection",
                "version": "YOLOv11m",
                "file": "HnE_detection.pt",
                "num_classes": 6,
                "classes": [CLASS_NAMES[i] for i in range(6)],
                "input_size": 512,
                "patch_size_level0": 1024,
                "output_mpp": self.output_mpp,
                "loaded": self.is_detection_model_loaded,
                "device": device_str,
            },
            {
                "id": "hne_br_segmentation",
                "name": "HnE Breast Segmentation",
                "version": "DeepLabV3Plus (EfficientNet-B5)",
                "file": "HnE_BR_segmentation.pt",
                "num_classes": 4,
                "classes": ["Background", "Stroma", "Non_Tumor", "Tumor"],
                "loaded": False,
                "device": None,
            },
            {
                "id": "hne_st_segmentation",
                "name": "HnE Stomach Segmentation",
                "version": "DeepLabV3Plus (EfficientNet-B5)",
                "file": "HnE_ST_segmentation.pt",
                "num_classes": 4,
                "classes": ["Background", "Stroma", "Non_Tumor", "Tumor"],
                "loaded": False,
                "device": None,
            },
        ]
        return models

    # ------------------------------------------------------------------
    # Full Detection Pipeline
    # ------------------------------------------------------------------

    def run_detection(
        self,
        slide_path: str,
        tissue_type: str = "Other",
        roi_list: Optional[List[dict]] = None,
        confidence_threshold: float = 0.01,
        class_thresholds: Optional[Dict[int, float]] = None,
        iou_threshold: float = 0.35,
        auto_epithelial_classify: bool = True,
        include_segmentation: bool = False,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        동기 검출 파이프라인 (호출 스레드에서 실행)

        Args:
            slide_path: WSI 파일 경로
            tissue_type: Breast / Stomach / Other
            roi_list: ROI JSON 배열 (None → 전체)
            confidence_threshold: 전역 confidence 임계값
            class_thresholds: 클래스별 confidence 임계값
            iou_threshold: NMS IoU 임계값
            auto_epithelial_classify: Epithelial 재분류 여부
            include_segmentation: Segmentation 결과 포함 여부
            progress_callback: (progress%, message) 콜백
            cancel_check: 취소 여부 확인 함수

        Returns:
            검출 결과 dict
        """
        non_max_suppression, wh2xy, CLASS_NAMES, CLASS_COLORS = _import_nms()

        def _progress(pct: int, msg: str):
            if progress_callback:
                progress_callback(pct, msg)

        def _cancelled() -> bool:
            return cancel_check() if cancel_check else False

        # 0. 모델 확인
        if self._model is None:
            if not self.load_detection_model():
                raise RuntimeError("Detection 모델을 로드할 수 없습니다.")

        start_time = time.time()

        # 1. 슬라이드 열기
        _progress(1, "슬라이드 로딩 중...")
        _openslide = _ensure_openslide()
        slide = _openslide.OpenSlide(slide_path)
        width, height = slide.dimensions

        # MPP
        mpp_x = slide.properties.get("openslide.mpp-x")
        mpp_y = slide.properties.get("openslide.mpp-y")
        if mpp_x and mpp_y:
            origin_mpp = (float(mpp_x) + float(mpp_y)) / 2
        else:
            origin_mpp = 0.25

        original_size = int(self.image_size * self.output_mpp / origin_mpp)

        # ROI
        roi_polygons = build_roi_polygons(roi_list) if roi_list else None

        # 클래스별 threshold
        ct = class_thresholds or {i: confidence_threshold for i in range(6)}

        # 2. 조직 마스크
        _progress(3, "조직 영역 감지 중...")
        if _cancelled():
            raise InterruptedError("작업이 취소되었습니다.")
        thumb_mask = self._create_tissue_mask(slide)
        _progress(5, "조직 마스크 생성 완료")

        # 3. 유효 패치 목록
        valid_patches = self._collect_valid_patches(
            width, height, self.image_size, thumb_mask, roi_polygons
        )
        n_valid = len(valid_patches)
        _progress(6, f"유효 패치 {n_valid}개 확인 완료")

        if _cancelled():
            raise InterruptedError("작업이 취소되었습니다.")

        # 4. 배치 추론
        chunks_x, chunks_y, chunks_cls, chunks_conf = [], [], [], []
        detected_count = 0
        processed = 0

        BATCH_SIZE = self.batch_size
        IO_WORKERS = self.io_workers
        PREFETCH_BATCHES = 3

        prefetch_queue: queue.Queue = queue.Queue(maxsize=PREFETCH_BATCHES)
        producer_done = threading.Event()

        def _io_producer():
            from concurrent.futures import ThreadPoolExecutor
            try:
                with ThreadPoolExecutor(max_workers=IO_WORKERS) as pool:
                    pending = []
                    for px, py in valid_patches:
                        if _cancelled():
                            break
                        fut = pool.submit(self._read_patch_tensor, slide_path, px, py,
                                          self.image_size, origin_mpp, self.output_mpp)
                        pending.append((px, py, fut))

                        if len(pending) >= BATCH_SIZE:
                            coords, tensors = [], []
                            for bx, by, f in pending:
                                t = f.result(timeout=120)
                                if t is not None:
                                    coords.append((bx, by))
                                    tensors.append(t)
                            if coords:
                                while not _cancelled():
                                    try:
                                        prefetch_queue.put((coords, tensors, len(pending)), timeout=0.5)
                                        break
                                    except queue.Full:
                                        continue
                            pending.clear()

                    # 잔여 패치
                    if pending and not _cancelled():
                        coords, tensors = [], []
                        for bx, by, f in pending:
                            t = f.result(timeout=120)
                            if t is not None:
                                coords.append((bx, by))
                                tensors.append(t)
                        if coords:
                            while not _cancelled():
                                try:
                                    prefetch_queue.put((coords, tensors, len(pending)), timeout=0.5)
                                    break
                                except queue.Full:
                                    continue
            except Exception as e:
                print(f"I/O 프로듀서 오류: {e}")
            finally:
                producer_done.set()
                prefetch_queue.put(None)

        prod = threading.Thread(target=_io_producer, daemon=True)
        prod.start()

        last_update = time.time()
        infer_start = time.time()

        while True:
            try:
                item = prefetch_queue.get(timeout=180)
            except queue.Empty:
                if producer_done.is_set():
                    break
                continue

            if item is None:
                break
            if _cancelled():
                break

            batch_coords, batch_tensors, patch_count = item
            bx, by, bcls, bconf = self._infer_batch(
                batch_coords, batch_tensors, non_max_suppression,
                confidence_threshold, iou_threshold, ct, roi_polygons
            )
            k = len(bx)
            if k > 0:
                chunks_x.append(bx)
                chunks_y.append(by)
                chunks_cls.append(bcls)
                chunks_conf.append(bconf)
                detected_count += k

            processed += patch_count
            pct = int(6 + (processed / max(n_valid, 1)) * 44)  # 6~50%
            now = time.time()
            if now - last_update >= 1.0:
                elapsed = now - infer_start
                speed = processed / elapsed if elapsed > 0 else 0
                eta = (n_valid - processed) / speed if speed > 0 else 0
                _progress(pct, f"패치 {processed}/{n_valid} | 세포 {detected_count}개 | {speed:.1f}it/s | ~{int(eta)}초")
                last_update = now

        prod.join(timeout=15)

        if _cancelled():
            slide.close()
            raise InterruptedError("작업이 취소되었습니다.")

        _progress(50, f"결과 정리 중... ({detected_count}개 검출)")

        # 청크 병합
        if chunks_x:
            all_x = np.concatenate(chunks_x)
            all_y = np.concatenate(chunks_y)
            all_cls = np.concatenate(chunks_cls)
            all_conf = np.concatenate(chunks_conf)
        else:
            all_x = all_y = all_conf = np.empty(0, dtype=np.float32)
            all_cls = np.empty(0, dtype=np.int32)
        del chunks_x, chunks_y, chunks_cls, chunks_conf
        gc.collect()

        # 5. Epithelial 재분류
        seg_result = None
        if auto_epithelial_classify and tissue_type in ("Breast", "Stomach"):
            epi_count = int(np.sum(all_cls == 1))
            if epi_count > 0:
                _progress(52, f"Epithelial 재분류 시작 ({epi_count}개)...")
                seg_data = self._run_epithelial_reclassification(
                    slide, slide_path, all_x, all_y, all_cls, origin_mpp,
                    tissue_type, roi_polygons, _progress, _cancelled,
                    include_segmentation,
                )
                if include_segmentation and seg_data:
                    seg_result = seg_data
            else:
                _progress(52, "Epithelial 세포 없음, 재분류 건너뜀")

        # 6. 결과 구성
        _progress(95, "결과 구성 중...")

        class_counts = {name: 0 for name in CLASS_NAMES.values()}
        if len(all_cls) > 0:
            bc = np.bincount(all_cls, minlength=max(CLASS_NAMES.keys()) + 1)
            for cid, cname in CLASS_NAMES.items():
                if cid < len(bc):
                    class_counts[cname] = int(bc[cid])

        # Epithelial breakdown
        epi_breakdown = None
        if auto_epithelial_classify and tissue_type in ("Breast", "Stomach"):
            tumor_epi = class_counts.get("Tumor Epithelial", 0)
            benign_epi = class_counts.get("Benign Epithelial", 0)
            total_epi = tumor_epi + benign_epi
            epi_breakdown = {
                "total_original_epithelial": total_epi,
                "reclassified_to_tumor": tumor_epi,
                "reclassified_to_benign": benign_epi,
                "tumor_ratio": tumor_epi / total_epi if total_epi > 0 else 0.0,
            }

        # cells list
        n_cells = len(all_x)
        cells = [
            {
                "x": float(all_x[i]),
                "y": float(all_y[i]),
                "cls_id": int(all_cls[i]),
                "cls_name": CLASS_NAMES.get(int(all_cls[i]), "Unknown"),
                "confidence": float(all_conf[i]),
            }
            for i in range(n_cells)
        ]

        processing_time = time.time() - start_time

        slide.close()
        _progress(100, "검출 완료")

        return {
            "status": "success",
            "processing_time_sec": round(processing_time, 2),
            "metadata": {
                "image_name": Path(slide_path).name,
                "image_dimensions": [width, height],
                "mpp": origin_mpp,
                "tissue_type": tissue_type,
                "model_name": "HnE_detection",
                "model_version": "YOLOv11m",
                "auto_epithelial_classify": auto_epithelial_classify,
                "roi_applied": roi_polygons is not None,
            },
            "summary": {
                "total_cells": n_cells,
                "class_counts": class_counts,
                "epithelial_breakdown": epi_breakdown,
            },
            "cells": cells,
            "segmentation": seg_result,
        }

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_tissue_mask(slide) -> np.ndarray:
        """조직 영역 마스크 생성"""
        try:
            downsample = 128
            w, h = slide.dimensions
            thumbnail = slide.get_thumbnail((w // downsample, h // downsample))
            thumbnail = np.array(thumbnail)
            if len(thumbnail.shape) == 3:
                gray = cv2.cvtColor(thumbnail[:, :, :3], cv2.COLOR_RGB2GRAY)
            else:
                gray = thumbnail

            mask = cv2.threshold(255 - gray, 30, 255, cv2.THRESH_BINARY)[1]
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

            target_w = w // 64
            target_h = h // 64
            mask = cv2.resize(mask, (target_w, target_h), interpolation=cv2.INTER_NEAREST)
            return mask
        except Exception:
            w, h = slide.dimensions
            return np.ones((h // 64, w // 64), dtype=np.uint8) * 255

    @staticmethod
    def _collect_valid_patches(
        width: int, height: int, image_size: int,
        thumb_mask: np.ndarray, roi_polygons: Optional[List[SimplePolygon]],
    ) -> List[Tuple[int, int]]:
        """유효 패치 좌표 수집"""
        valid = []
        for pr in range(width // image_size - 1):
            for pc in range(height // image_size - 1):
                mx = (pr * image_size) // 64
                my = (pc * image_size) // 64
                if np.sum(thumb_mask[my:my + image_size // 64, mx:mx + image_size // 64]) == 0:
                    continue
                px, py = pr * image_size, pc * image_size
                if roi_polygons:
                    center_x = px + image_size // 2
                    center_y = py + image_size // 2
                    in_roi = any(p.contains_point(center_x, center_y) for p in roi_polygons)
                    if not in_roi:
                        # 코너 체크
                        corners = [(px, py), (px + image_size, py),
                                   (px + image_size, py + image_size), (px, py + image_size)]
                        in_roi = any(
                            p.contains_point(cx, cy)
                            for cx, cy in corners
                            for p in roi_polygons
                        )
                    if not in_roi:
                        continue
                valid.append((px, py))
        return valid

    @staticmethod
    def _read_patch_tensor(
        slide_path: str, patch_x: int, patch_y: int,
        image_size: int, origin_mpp: float, output_mpp: float,
    ) -> Optional[torch.Tensor]:
        """패치 읽기 → CPU 텐서 (스레드 안전)"""
        try:
            if (not hasattr(_patch_thread_local, "slide") or
                    _patch_thread_local.image_path != slide_path):
                _openslide = _ensure_openslide()
                _patch_thread_local.slide = _openslide.OpenSlide(slide_path)
                _patch_thread_local.image_path = slide_path
            sl = _patch_thread_local.slide

            patch = sl.read_region((patch_x, patch_y), 0, (image_size, image_size))
            patch = np.array(patch)[:, :, :3]
            patch = cv2.resize(patch, (512, 512))
            return torch.from_numpy(patch.copy()).permute(2, 0, 1).float() / 255.0
        except Exception as e:
            print(f"패치 읽기 오류 ({patch_x}, {patch_y}): {e}")
            return None

    def _infer_batch(
        self,
        batch_coords: List[Tuple[int, int]],
        batch_tensors: List[torch.Tensor],
        nms_fn,
        conf_thresh: float,
        iou_thresh: float,
        class_thresholds: Dict[int, float],
        roi_polygons: Optional[List[SimplePolygon]],
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """배치 GPU 추론"""
        _ef = np.empty(0, dtype=np.float32)
        _ei = np.empty(0, dtype=np.int32)

        xs, ys, clss, confs = [], [], [], []
        coord_scale = self.image_size / 512

        try:
            batch = torch.stack(batch_tensors).to(self._device)
            with torch.no_grad():
                with torch.amp.autocast("cuda", enabled=torch.cuda.is_available()):
                    preds = self._model(batch)

            results = nms_fn(preds, confidence_threshold=conf_thresh,
                             iou_threshold=iou_thresh, class_thresholds=class_thresholds)

            for i, (start_x, start_y) in enumerate(batch_coords):
                if i >= len(results) or len(results[i]) == 0:
                    continue
                det = results[i]
                xyxy, confs_t, cls_ids = det[:, :4], det[:, 4], det[:, 5]

                cx = ((xyxy[:, 0] + xyxy[:, 2]) / 2 * coord_scale + start_x).cpu().numpy().astype(np.float32)
                cy = ((xyxy[:, 1] + xyxy[:, 3]) / 2 * coord_scale + start_y).cpu().numpy().astype(np.float32)
                cl = cls_ids.cpu().numpy().astype(np.int32)
                co = confs_t.cpu().numpy().astype(np.float32)

                if roi_polygons:
                    keep = np.array([
                        any(p.contains_point(float(cx[j]), float(cy[j])) for p in roi_polygons)
                        for j in range(len(cx))
                    ], dtype=bool)
                    cx, cy, cl, co = cx[keep], cy[keep], cl[keep], co[keep]

                if len(cx) > 0:
                    xs.append(cx)
                    ys.append(cy)
                    clss.append(cl)
                    confs.append(co)

        except Exception as e:
            print(f"배치 추론 오류: {e}\n{traceback.format_exc()}")

        if not xs:
            return _ef, _ef.copy(), _ei, _ef.copy()

        return np.concatenate(xs), np.concatenate(ys), np.concatenate(clss), np.concatenate(confs)

    def _run_epithelial_reclassification(
        self,
        slide: openslide.OpenSlide,
        slide_path: str,
        all_x: np.ndarray,
        all_y: np.ndarray,
        all_cls: np.ndarray,
        origin_mpp: float,
        tissue_type: str,
        roi_polygons: Optional[List[SimplePolygon]],
        _progress: Callable,
        _cancelled: Callable,
        include_segmentation: bool,
    ) -> Optional[Dict[str, Any]]:
        """Epithelial 재분류 수행 (cls_arr in-place 수정)"""
        try:
            WSISegmentationModel = _import_seg_model()

            if tissue_type == "Breast":
                seg_path = self._seg_breast_path
            elif tissue_type == "Stomach":
                seg_path = self._seg_stomach_path
            else:
                return None

            if not seg_path.exists():
                _progress(90, f"Segmentation 모델 파일 없음: {seg_path.name}")
                return None

            _progress(55, "Segmentation 모델 로딩 중...")
            seg_model = WSISegmentationModel(
                model_path=str(seg_path),
                model_mpp=1.0,
                output_mpp=4.0,
                device=self._device,
            )

            # ROI bounds
            roi_bounds = None
            if roi_polygons:
                min_x = min(c[0] for p in roi_polygons for c in p.coordinates)
                min_y = min(c[1] for p in roi_polygons for c in p.coordinates)
                max_x = max(c[0] for p in roi_polygons for c in p.coordinates)
                max_y = max(c[1] for p in roi_polygons for c in p.coordinates)
                roi_bounds = (int(min_x), int(min_y), int(max_x), int(max_y))

            def seg_progress(pct):
                _progress(55 + int(pct * 0.3), f"Segmentation {pct}%")

            def seg_status(msg):
                _progress(-1, msg)  # -1 → 진행률 변경 없이 메시지만

            _progress(58, "WSI Segmentation 실행 중...")
            prediction_mask, metadata = seg_model.predict_wsi(
                slide,
                patch_size=512,
                overlap_ratio=0.4,
                batch_size=8,
                progress_callback=seg_progress,
                status_callback=seg_status,
                roi_bounds=roi_bounds,
                image_path=slide_path,
            )

            if _cancelled():
                del seg_model
                return None

            # Epithelial 재분류 (Connected Component + Tumor ratio)
            _progress(90, "Epithelial 세포 재분류 중...")

            scale_factor = origin_mpp / seg_model.output_mpp
            region_offset_x = metadata.get("region_offset", (0, 0))[0]
            region_offset_y = metadata.get("region_offset", (0, 0))[1]

            epi_indices = np.where(all_cls == 1)[0]
            if len(epi_indices) == 0:
                del seg_model
                return None

            epi_xs = all_x[epi_indices]
            epi_ys = all_y[epi_indices]
            mxs = ((epi_xs - region_offset_x) * scale_factor).astype(np.int32)
            mys = ((epi_ys - region_offset_y) * scale_factor).astype(np.int32)
            h, w = prediction_mask.shape
            valid = (mxs >= 0) & (mxs < w) & (mys >= 0) & (mys < h)
            seg_vals = np.zeros(len(epi_indices), dtype=np.int32)
            seg_vals[valid] = prediction_mask[mys[valid], mxs[valid]]

            from scipy import ndimage as ndi
            TUMOR_RATIO_THRESHOLD = 0.1
            epi_region = np.isin(prediction_mask, [2, 3]).astype(np.uint8)
            labeled_mask, num_components = ndi.label(epi_region, structure=np.ones((3, 3), dtype=np.int8))

            flat_label = labeled_mask.ravel()
            flat_mask = prediction_mask.ravel().astype(np.int32)
            n_bins = num_components + 1
            tumor_counts = np.bincount(flat_label, weights=(flat_mask == 3), minlength=n_bins)
            total_counts = np.bincount(flat_label, weights=np.isin(flat_mask, [2, 3]).astype(float), minlength=n_bins)
            with np.errstate(invalid="ignore", divide="ignore"):
                tumor_ratio = np.where(total_counts > 0, tumor_counts / total_counts, 0.0)
            comp_class_arr = np.where(tumor_ratio >= TUMOR_RATIO_THRESHOLD, 3, 2).astype(np.int32)
            comp_class_arr[0] = 0

            lh, lw = labeled_mask.shape
            lvalid = (mxs >= 0) & (mxs < lw) & (mys >= 0) & (mys < lh)
            comp_ids = np.zeros(len(epi_indices), dtype=np.int32)
            comp_ids[lvalid] = labeled_mask[mys[lvalid], mxs[lvalid]]
            update_mask = comp_ids > 0
            seg_vals[update_mask] = comp_class_arr[comp_ids[update_mask]]

            # cls_arr in-place 수정: 2 = Non_Tumor → Benign(7), else → Tumor(6)
            all_cls[epi_indices] = np.where(seg_vals == 2, 7, 6).astype(np.int32)

            _progress(95, f"Epithelial 재분류 완료 ({len(epi_indices)}개)")

            # Segmentation 결과 구성
            seg_result = None
            if include_segmentation:
                seg_result = {
                    "mask_shape": list(prediction_mask.shape),
                    "output_mpp": seg_model.output_mpp,
                    "wsi_mpp": origin_mpp,
                    "region_offset": list(metadata.get("region_offset", (0, 0))),
                    "class_names": seg_model.class_names,
                    "polygon_coordinate_system": "wsi_level0",
                }

            del seg_model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            return seg_result

        except Exception as e:
            print(f"Epithelial 재분류 실패: {e}\n{traceback.format_exc()}")
            _progress(95, f"재분류 실패 (원본 결과 사용): {e}")
            return None


# ============================================================================
# Singleton 인스턴스
# ============================================================================

_service_instance: Optional[DetectionAPIService] = None
_instance_lock = threading.Lock()


def get_detection_service() -> DetectionAPIService:
    """싱글턴 DetectionAPIService 반환"""
    global _service_instance
    if _service_instance is None:
        with _instance_lock:
            if _service_instance is None:
                _service_instance = DetectionAPIService()
    return _service_instance
