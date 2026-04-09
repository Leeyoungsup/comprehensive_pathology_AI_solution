"""
AI 분석 API — Detection / Segmentation
기존 ai/ 모듈의 병렬 I/O + 배치 GPU 추론 파이프라인을 그대로 사용
"""

import os
import sys
import json
import uuid
import queue
import threading
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException, Form
from fastapi.responses import JSONResponse

from app.config import settings
from app.slide_manager import slide_manager

# 기존 AI 코드 경로 추가
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

router = APIRouter()

# AI 작업 상태 추적
_tasks = {}
_tasks_lock = threading.Lock()

# I/O 워커 스레드별 독립 OpenSlide 객체 (thread-safe)
_patch_thread_local = threading.local()


def _update_task(task_id, **kwargs):
    with _tasks_lock:
        _tasks[task_id].update(kwargs)


def _get_ai_cache_path(slide_path: str, tissue_type: str) -> Path:
    """
    AI 결과 캐시 파일 경로.
    settings.AI_RESULTS_DIR (uploads 와는 별개) 에 저장한다.
    파일명: {slide_stem}_HE-Fit_{tissue_type}.json
    """
    p = Path(slide_path)
    cache_dir = Path(settings.AI_RESULTS_DIR)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return cache_dir / f"{p.stem}_HE-Fit_{tissue_type}.json"


def _run_detection(task_id: str, slide_id: str, roi_polygons: Optional[list], tissue_type: str):
    """
    백그라운드 검출 — 기존 DetectionWorker.run()과 동일한 파이프라인:
    1. 조직 마스크 → 배경 패치 스킵
    2. 멀티스레드 I/O 프리페치 (ThreadPoolExecutor)
    3. 배치 GPU 추론 (8장씩)
    """
    try:
        import torch
        import numpy as np
        import cv2

        info = slide_manager.get(slide_id)
        if not info:
            _update_task(task_id, status="error", error="슬라이드를 찾을 수 없습니다")
            return

        # ── 캐시된 AI 결과 확인 (전체/ROI 무관 — 있으면 가져와서 표시) ──
        cache_path = _get_ai_cache_path(info.file_path, tissue_type)
        if cache_path.exists():
            try:
                _update_task(task_id, status="running", progress=10,
                             status_msg=f"Loading cached AI result: {cache_path.name}")
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                _update_task(task_id, status="completed", progress=100,
                             status_msg=f"Loaded cached result ({cached.get('total_cells', 0)} cells)",
                             result=cached)
                return
            except Exception as e:
                import traceback
                print(f"Cache load failed, running fresh inference: {e}\n{traceback.format_exc()}")

        _update_task(task_id, status="running", progress=1,
                     status_msg="Starting detection...")

        # ── 모델 로드 ──
        from ai.detection import non_max_suppression, CLASS_NAMES, CLASS_COLORS
        from ai.nets import nn as yolo_nn

        _update_task(task_id, progress=1, status_msg="Loading detection model...")

        model_path = Path(settings.MODEL_DIR) / "HnE_detection.pt"
        if not model_path.exists():
            _update_task(task_id, status="error", error=f"모델 파일 없음: {model_path}")
            return

        device = "cuda" if torch.cuda.is_available() else "cpu"
        num_classes = 6
        model = yolo_nn.yolo_v11_m(num_classes).to(device)
        checkpoint = torch.load(str(model_path), map_location=device, weights_only=False)
        model.load_state_dict(checkpoint['model_state_dict'])
        model.eval()

        _update_task(task_id, progress=3, status_msg="Detection model loaded")

        # ── 설정 (기존 DetectionWorker와 동일) ──
        slide = info.slide
        slide_path = info.file_path
        width, height = info.dimensions
        image_size = 1024
        output_mpp = 0.5
        origin_mpp = info.mpp
        original_size = int(image_size * output_mpp / origin_mpp)

        BATCH_SIZE = 8
        IO_WORKERS = min(max(2, os.cpu_count() or 4), 8)
        PREFETCH_BATCHES = 3

        class_thresholds = {
            0: 0.01, 1: 0.01, 2: 0.01,
            3: 0.01, 4: 0.01, 5: 0.01,
        }

        # ── 조직 마스크 (배경 스킵) ──
        _update_task(task_id, progress=4, status_msg="조직 마스크 생성 중...")
        thumb_mask = _create_tissue_mask(slide)
        _update_task(task_id, progress=5)

        # ── Pre-scan: 유효 패치 수집 ──
        valid_patch_list = []
        for pr in range(width // image_size - 1):
            for pc in range(height // image_size - 1):
                mx = (pr * image_size) // 64
                my = (pc * image_size) // 64
                if np.sum(thumb_mask[my:my + image_size // 64,
                                     mx:mx + image_size // 64]) == 0:
                    continue
                px, py = pr * image_size, pc * image_size
                # ROI 체크 (간단 바운딩박스)
                if roi_polygons:
                    cx, cy = px + image_size // 2, py + image_size // 2
                    in_roi = any(
                        min(p[0] for p in poly) <= cx <= max(p[0] for p in poly) and
                        min(p[1] for p in poly) <= cy <= max(p[1] for p in poly)
                        for poly in roi_polygons
                    )
                    if not in_roi:
                        continue
                valid_patch_list.append((px, py))

        n_valid = len(valid_patch_list)
        _update_task(task_id, progress=6, status_msg=f"유효 패치 {n_valid}개 발견")

        if n_valid == 0:
            _update_task(task_id, status="completed", progress=100, result={
                "total_cells": 0, "cells": [],
                "class_names": {str(k): v for k, v in CLASS_NAMES.items()},
                "class_colors": {str(k): v for k, v in CLASS_COLORS.items()},
            })
            return

        # ── numpy 청크 누적 (기존 방식: list-of-dicts 대신 numpy 배열) ──
        chunks_x, chunks_y, chunks_cls, chunks_conf = [], [], [], []
        detected_count = 0
        processed_valid = 0

        # ── I/O → 텐서 변환 함수 (스레드별 독립 OpenSlide) ──
        def _read_patch_tensor(patch_x, patch_y):
            try:
                if (not hasattr(_patch_thread_local, 'slide') or
                        _patch_thread_local.slide_path != slide_path):
                    import openslide
                    _patch_thread_local.slide = openslide.OpenSlide(slide_path)
                    _patch_thread_local.slide_path = slide_path
                local_slide = _patch_thread_local.slide

                patch = local_slide.read_region((patch_x, patch_y), 0, (image_size, image_size))
                patch_rgb = patch.convert('RGB')
                patch_np = np.asarray(patch_rgb)
                patch_resized = cv2.resize(patch_np, (512, 512))
                return torch.from_numpy(patch_resized.copy()).permute(2, 0, 1).float() / 255.0
            except Exception as e:
                return None

        # ── 배치 GPU 추론 함수 (기존 _infer_batch와 동일) ──
        def _infer_batch(batch_coords, batch_tensors):
            bx, by, bcls, bconf = [], [], [], []
            try:
                batch = torch.stack(batch_tensors).to(device)
                with torch.no_grad():
                    if device == "cuda":
                        with torch.amp.autocast('cuda'):
                            preds = model(batch)
                    else:
                        preds = model(batch)

                results = non_max_suppression(
                    preds, confidence_threshold=0.01,
                    iou_threshold=0.3, class_thresholds=class_thresholds,
                )

                coord_scale = image_size / 512  # = 2.0
                for i, (sx, sy) in enumerate(batch_coords):
                    if i >= len(results) or len(results[i]) == 0:
                        continue
                    det = results[i]
                    xyxy = det[:, :4]
                    cx_np = ((xyxy[:, 0] + xyxy[:, 2]) / 2 * coord_scale + sx).cpu().numpy().astype(np.float32)
                    cy_np = ((xyxy[:, 1] + xyxy[:, 3]) / 2 * coord_scale + sy).cpu().numpy().astype(np.float32)
                    cls_np = det[:, 5].cpu().numpy().astype(np.int32)
                    conf_np = det[:, 4].cpu().numpy().astype(np.float32)
                    if len(cx_np) > 0:
                        bx.append(cx_np)
                        by.append(cy_np)
                        bcls.append(cls_np)
                        bconf.append(conf_np)
            except Exception as e:
                import traceback
                print(f"Batch inference error: {e}\n{traceback.format_exc()}")

            if not bx:
                ef = np.empty(0, dtype=np.float32)
                ei = np.empty(0, dtype=np.int32)
                return ef, ef.copy(), ei, ef.copy()
            return np.concatenate(bx), np.concatenate(by), np.concatenate(bcls), np.concatenate(bconf)

        # ══════════════════════════════════════
        # 파이프라인: I/O 프리페치 → 배치 GPU 추론
        # (기존 DetectionWorker._io_producer 로직 그대로)
        # ══════════════════════════════════════
        prefetch_q = queue.Queue(maxsize=PREFETCH_BATCHES)
        producer_done = threading.Event()

        def _io_producer():
            try:
                with ThreadPoolExecutor(max_workers=IO_WORKERS) as pool:
                    pending = []
                    for px, py in valid_patch_list:
                        future = pool.submit(_read_patch_tensor, px, py)
                        pending.append((px, py, future))

                        if len(pending) >= BATCH_SIZE:
                            coords, tensors = [], []
                            for bpx, bpy, f in pending:
                                t = f.result(timeout=60)
                                if t is not None:
                                    coords.append((bpx, bpy))
                                    tensors.append(t)
                            if coords:
                                prefetch_q.put((coords, tensors, len(pending)), timeout=30)
                            pending.clear()

                    # 남은 패치
                    if pending:
                        coords, tensors = [], []
                        for bpx, bpy, f in pending:
                            t = f.result(timeout=60)
                            if t is not None:
                                coords.append((bpx, bpy))
                                tensors.append(t)
                        if coords:
                            prefetch_q.put((coords, tensors, len(pending)), timeout=30)
            except Exception as e:
                print(f"I/O producer error: {e}")
            finally:
                producer_done.set()
                prefetch_q.put(None)  # sentinel

        producer_thread = threading.Thread(target=_io_producer, daemon=True)
        producer_thread.start()

        # ── GPU 추론 루프 ──
        while True:
            try:
                item = prefetch_q.get(timeout=120)
            except queue.Empty:
                if producer_done.is_set():
                    break
                continue

            if item is None:
                break

            batch_coords, batch_tensors, patch_count = item
            bx, by, bcls, bconf = _infer_batch(batch_coords, batch_tensors)
            k = len(bx)
            if k > 0:
                chunks_x.append(bx)
                chunks_y.append(by)
                chunks_cls.append(bcls)
                chunks_conf.append(bconf)
                detected_count += k

            processed_valid += patch_count
            pct = int(5 + (processed_valid / n_valid) * 45)  # 5~50%
            _update_task(task_id, progress=min(pct, 50),
                         status_msg=f"Detection: Patch {processed_valid}/{n_valid} | Cells: {detected_count}")

        producer_thread.join(timeout=10)

        # ── 결과 병합 ──
        if chunks_x:
            all_x = np.concatenate(chunks_x)
            all_y = np.concatenate(chunks_y)
            all_cls = np.concatenate(chunks_cls)
            all_conf = np.concatenate(chunks_conf)
        else:
            all_x = all_y = all_conf = np.empty(0, dtype=np.float32)
            all_cls = np.empty(0, dtype=np.int32)

        _update_task(task_id, progress=50,
                     status_msg=f"Detection complete: {detected_count} cells")

        # ── Epithelial 재분류 (Breast/Stomach만) ──
        seg_data = None
        auto_classify = tissue_type in ("Breast", "Stomach")
        if auto_classify and len(all_cls) > 0:
            epithelial_count = int(np.sum(all_cls == 1))
            if epithelial_count > 0:
                _update_task(task_id, progress=52,
                             status_msg=f"Epithelial reclassification starting... ({epithelial_count} cells)")
                seg_data = _run_epithelial_classification(
                    task_id, slide, slide_path, info, all_x, all_y, all_cls,
                    tissue_type, roi_polygons, device,
                )
            else:
                _update_task(task_id, progress=98,
                             status_msg="No Epithelial cells found, skipping reclassification")
        elif not auto_classify:
            _update_task(task_id, progress=98,
                         status_msg="Tissue type 'Other' — skipping reclassification")

        n_cells = len(all_x)
        all_cells = [
            {
                "x": float(all_x[i]),
                "y": float(all_y[i]),
                "confidence": float(all_conf[i]),
                "class_id": int(all_cls[i]),
                "class_name": CLASS_NAMES.get(int(all_cls[i]), "Unknown"),
            }
            for i in range(n_cells)
        ]

        result = {
            "total_cells": n_cells,
            "cells": all_cells,
            "class_names": {str(k): v for k, v in CLASS_NAMES.items()},
            "class_colors": {str(k): v for k, v in CLASS_COLORS.items()},
            "seg_data": seg_data,
        }

        # ── 전체 추론(폴리곤 없음)인 경우만 캐시 저장 ──
        if roi_polygons is None:
            try:
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(result, f)
                print(f"AI result cached: {cache_path}")
            except Exception as e:
                import traceback
                print(f"Cache save failed: {e}\n{traceback.format_exc()}")

        _update_task(task_id, status="completed", progress=100, result=result)

    except Exception as e:
        import traceback
        _update_task(task_id, status="error", error=f"{e}\n{traceback.format_exc()}")


def _create_tissue_mask(slide):
    """조직 마스크 생성 (기존 DetectionWorker._create_tissue_mask와 동일)"""
    import numpy as np
    import cv2

    try:
        downsample = 128
        thumbnail = slide.get_thumbnail((
            slide.dimensions[0] // downsample,
            slide.dimensions[1] // downsample,
        ))
        thumbnail = np.array(thumbnail)

        if len(thumbnail.shape) == 3:
            gray = cv2.cvtColor(thumbnail[:, :, :3], cv2.COLOR_RGB2GRAY)
        else:
            gray = thumbnail

        mask = cv2.threshold(255 - gray, 30, 255, cv2.THRESH_BINARY)[1]
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

        target_w = slide.dimensions[0] // 64
        target_h = slide.dimensions[1] // 64
        mask = cv2.resize(mask, (target_w, target_h), interpolation=cv2.INTER_NEAREST)
        return mask
    except Exception:
        w, h = slide.dimensions
        return np.ones((h // 64, w // 64), dtype=np.uint8) * 255


def _run_epithelial_classification(task_id, slide, slide_path, info, all_x, all_y, all_cls,
                                    tissue_type, roi_polygons, device):
    """
    Epithelial 재분류: WSI Segmentation → Epithelial(1) → Tumor(6) / Benign(7)
    데스크톱 DetectionWorker._run_epithelial_classification과 동일 로직
    all_cls를 in-place로 수정한다.
    Returns: seg_data dict (seg_class_names, overlays as base64, thumbnail) or None
    """
    import numpy as np
    import torch

    try:
        from ai.epithelial_classifier import WSISegmentationModel

        # Segmentation 모델 경로
        if tissue_type == "Breast":
            seg_model_path = Path(settings.MODEL_DIR) / "HnE_BR_segmentation.pt"
        elif tissue_type == "Stomach":
            seg_model_path = Path(settings.MODEL_DIR) / "HnE_ST_segmentation.pt"
        else:
            return

        if not seg_model_path.exists():
            _update_task(task_id, status_msg=f"Segmentation model not found: {seg_model_path}")
            return

        _update_task(task_id, progress=52,
                     status_msg="Loading segmentation model...")

        seg_model = WSISegmentationModel(
            model_path=str(seg_model_path),
            model_mpp=1.0,
            output_mpp=4.0,
            device=device,
        )

        # ROI bounds 계산
        roi_bounds = None
        if roi_polygons:
            min_x = min(p[0] for poly in roi_polygons for p in poly)
            min_y = min(p[1] for poly in roi_polygons for p in poly)
            max_x = max(p[0] for poly in roi_polygons for p in poly)
            max_y = max(p[1] for poly in roi_polygons for p in poly)
            roi_bounds = (int(min_x), int(min_y), int(max_x), int(max_y))

        _update_task(task_id, progress=55,
                     status_msg="Running WSI Segmentation...")

        def progress_cb(pct):
            # 55~90% 구간
            _update_task(task_id, progress=55 + int(pct * 0.35),
                         status_msg=f"WSI Segmentation... {int(pct)}%")

        prediction_mask, metadata = seg_model.predict_wsi(
            slide,
            patch_size=512,
            overlap_ratio=0.4,
            batch_size=8,
            progress_callback=progress_cb,
            roi_bounds=roi_bounds,
            image_path=slide_path,
        )

        _update_task(task_id, progress=92,
                     status_msg="Reclassifying Epithelial cells...")

        # ── Epithelial 인덱스 및 mask 좌표 변환 ──
        wsi_mpp = info.mpp
        output_mpp = seg_model.output_mpp
        scale_factor = wsi_mpp / output_mpp
        region_offset_x = metadata.get('region_offset', (0, 0))[0]
        region_offset_y = metadata.get('region_offset', (0, 0))[1]

        epi_indices = np.where(all_cls == 1)[0]
        if len(epi_indices) == 0:
            return

        epi_xs = all_x[epi_indices]
        epi_ys = all_y[epi_indices]
        mxs = ((epi_xs - region_offset_x) * scale_factor).astype(np.int32)
        mys = ((epi_ys - region_offset_y) * scale_factor).astype(np.int32)
        h, w = prediction_mask.shape
        valid = (mxs >= 0) & (mxs < w) & (mys >= 0) & (mys < h)
        seg_vals = np.zeros(len(epi_indices), dtype=np.int32)
        seg_vals[valid] = prediction_mask[mys[valid], mxs[valid]]

        # ── Connected component 클러스터링 ──
        from scipy import ndimage as ndi
        TUMOR_RATIO_THRESHOLD = 0.1
        epi_region = np.isin(prediction_mask, [2, 3]).astype(np.uint8)
        labeled_mask, num_components = ndi.label(epi_region, structure=np.ones((3, 3), dtype=np.int8))

        flat_label = labeled_mask.ravel()
        flat_mask = prediction_mask.ravel().astype(np.int32)
        n_bins = num_components + 1
        tumor_counts = np.bincount(flat_label, weights=(flat_mask == 3), minlength=n_bins)
        total_counts = np.bincount(flat_label, weights=np.isin(flat_mask, [2, 3]).astype(float), minlength=n_bins)
        with np.errstate(invalid='ignore', divide='ignore'):
            tumor_ratio = np.where(total_counts > 0, tumor_counts / total_counts, 0.0)
        comp_class_arr = np.where(tumor_ratio >= TUMOR_RATIO_THRESHOLD, 3, 2).astype(np.int32)
        comp_class_arr[0] = 0  # background

        lh, lw = labeled_mask.shape
        lvalid = (mxs >= 0) & (mxs < lw) & (mys >= 0) & (mys < lh)
        comp_ids = np.zeros(len(epi_indices), dtype=np.int32)
        comp_ids[lvalid] = labeled_mask[mys[lvalid], mxs[lvalid]]
        update_mask = comp_ids > 0
        seg_vals[update_mask] = comp_class_arr[comp_ids[update_mask]]

        # cls_arr in-place 업데이트: Benign(2)→7, Tumor(3)→6
        all_cls[epi_indices] = np.where(seg_vals == 2, 7, 6).astype(np.int32)

        _update_task(task_id, progress=98,
                     status_msg=f"Epithelial reclassification complete ({len(epi_indices)} cells)")

        # ── 썸네일 + 세그멘테이션 오버레이 생성 (프론트엔드 시각화용) ──
        seg_data = _build_seg_overlays(slide, prediction_mask, metadata,
                                       seg_model.class_names, roi_bounds)

        del seg_model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        return seg_data

    except Exception as e:
        import traceback
        print(f"Epithelial reclassification failed: {e}\n{traceback.format_exc()}")
        _update_task(task_id, progress=98,
                     status_msg=f"Reclassification failed, using original results: {e}")
        return None


def _build_seg_overlays(slide, prediction_mask, metadata, class_names, roi_bounds):
    """
    세그멘테이션 확률맵(prob_map)을 썸네일 크기로 리사이즈하여 클래스별 오버레이 base64 생성.
    데스크톱의 _create_spatial_heatmap_tab과 동일: jet colormap + alpha=0.75 on probability maps.
    """
    import numpy as np
    import cv2
    import base64
    import io
    from PIL import Image

    try:
        # 썸네일 생성 (ROI 영역이면 해당 영역만)
        THUMB_SIZE = 800
        sw, sh = slide.dimensions
        if roi_bounds:
            x0, y0, x1, y1 = roi_bounds
        else:
            x0, y0, x1, y1 = 0, 0, sw, sh
        rw, rh = x1 - x0, y1 - y0

        # 썸네일 비율 유지
        if rw >= rh:
            tw = THUMB_SIZE
            th = max(1, int(THUMB_SIZE * rh / rw))
        else:
            th = THUMB_SIZE
            tw = max(1, int(THUMB_SIZE * rw / rh))

        # 썸네일 생성
        if roi_bounds:
            # ROI: 적절한 레벨에서 직접 read_region → 정확한 영역
            best_level = slide.get_best_level_for_downsample(max(rw, rh) / THUMB_SIZE)
            ds = slide.level_downsamples[best_level]
            read_w = int(rw / ds)
            read_h = int(rh / ds)
            region = slide.read_region((x0, y0), best_level, (read_w, read_h))
            thumb_np = np.array(region.convert('RGB'))
        else:
            thumb = slide.get_thumbnail((THUMB_SIZE, THUMB_SIZE))
            thumb_np = np.array(thumb.convert('RGB'))
        thumb_resized = cv2.resize(thumb_np, (tw, th))

        # 썸네일 → base64 JPEG
        _, thumb_buf = cv2.imencode('.jpeg', cv2.cvtColor(thumb_resized, cv2.COLOR_RGB2BGR),
                                     [cv2.IMWRITE_JPEG_QUALITY, 85])
        thumb_b64 = base64.b64encode(thumb_buf.tobytes()).decode('ascii')

        # ── 확률맵 기반 오버레이 (데스크톱과 동일) ──
        # metadata['prob_map'] = (num_classes, H, W) softmax probabilities
        # predict_wsi는 roi_bounds에 10% 버퍼를 추가하므로 mask/prob_map 영역 ≠ roi_bounds
        # → roi_bounds에 해당하는 부분만 crop 필요
        prob_map = metadata.get('prob_map')
        region_offset = metadata.get('region_offset', (0, 0))
        wsi_mpp = metadata.get('wsi_mpp', 0.25)
        output_mpp = metadata.get('output_mpp', 8.0)
        mpp_ratio = output_mpp / wsi_mpp  # mask 1px = WSI mpp_ratio px

        # mask/prob_map에서 roi_bounds에 해당하는 crop 인덱스 계산
        mask_h, mask_w = prediction_mask.shape
        if roi_bounds:
            # roi_bounds(WSI 좌표) → mask 좌표
            crop_mx0 = max(0, int((x0 - region_offset[0]) / mpp_ratio))
            crop_my0 = max(0, int((y0 - region_offset[1]) / mpp_ratio))
            crop_mx1 = min(mask_w, int((x1 - region_offset[0]) / mpp_ratio))
            crop_my1 = min(mask_h, int((y1 - region_offset[1]) / mpp_ratio))
        else:
            crop_mx0, crop_my0 = 0, 0
            crop_mx1, crop_my1 = mask_w, mask_h

        overlays = {}
        num_classes = len(class_names) if class_names else int(prediction_mask.max()) + 1

        for cls_id in range(1, num_classes):  # 0=Background 제외
            cls_name = class_names[cls_id] if class_names and cls_id < len(class_names) else f'Class_{cls_id}'

            if prob_map is not None and cls_id < prob_map.shape[0]:
                # roi 영역만 crop 후 썸네일 크기로 bilinear 리사이즈
                cropped = prob_map[cls_id][crop_my0:crop_my1, crop_mx0:crop_mx1].astype(np.float32)
                prob_resized = cv2.resize(cropped, (tw, th),
                                          interpolation=cv2.INTER_LINEAR)
            else:
                # fallback: argmax 마스크에서 crop → 이진 + blur
                cropped = prediction_mask[crop_my0:crop_my1, crop_mx0:crop_mx1].astype(np.uint8)
                mask_resized = cv2.resize(cropped, (tw, th),
                                           interpolation=cv2.INTER_NEAREST)
                prob_resized = cv2.GaussianBlur(
                    (mask_resized == cls_id).astype(np.float32), (7, 7), 2.0)

            # jet colormap 적용 (데스크톱: cmap='jet', alpha=0.75, vmin=0, vmax=1)
            cls_norm = (np.clip(prob_resized, 0, 1) * 255).astype(np.uint8)
            cls_jet = cv2.applyColorMap(cls_norm, cv2.COLORMAP_JET)
            # alpha: 확률값에 비례 (0.75 최대)
            alpha = (np.clip(prob_resized, 0, 1) * 0.75 * 255).astype(np.uint8)
            cls_rgba = np.dstack([cv2.cvtColor(cls_jet, cv2.COLOR_BGR2RGB), alpha])

            img = Image.fromarray(cls_rgba, 'RGBA')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            overlays[cls_name] = base64.b64encode(buf.getvalue()).decode('ascii')

        return {
            'thumbnail': thumb_b64,
            'overlays': overlays,
            'class_names': class_names[1:] if class_names else [],  # Background 제외
            'width': tw,
            'height': th,
        }
    except Exception as e:
        import traceback
        print(f"Seg overlay generation failed: {e}\n{traceback.format_exc()}")
        return None


# ═══ API 엔드포인트 ═══

@router.post("/detect")
async def start_detection(
    slide_id: str = Form(...),
    roi_polygons: Optional[str] = Form(None),
    tissue_type: str = Form("Stomach"),
):
    """검출 작업 시작 (비동기)"""
    info = slide_manager.get(slide_id)
    if not info:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")

    task_id = uuid.uuid4().hex[:12]
    polygons = json.loads(roi_polygons) if roi_polygons else None

    with _tasks_lock:
        _tasks[task_id] = {
            "status": "queued", "progress": 0,
            "result": None, "error": None, "status_msg": "",
        }

    t = threading.Thread(
        target=_run_detection,
        args=(task_id, slide_id, polygons, tissue_type),
        daemon=True,
    )
    t.start()

    return {"task_id": task_id, "status": "queued"}


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """AI 작업 상태 조회"""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        raise HTTPException(404, "작업을 찾을 수 없습니다")

    response = {
        "task_id": task_id,
        "status": task["status"],
        "progress": task["progress"],
        "status_msg": task.get("status_msg", ""),
    }
    if task["status"] == "completed":
        response["result"] = task["result"]
    elif task["status"] == "error":
        response["error"] = task["error"]
    return response


@router.get("/task/{task_id}/result")
async def get_task_result(task_id: str):
    """AI 작업 결과 조회"""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        raise HTTPException(404, "작업을 찾을 수 없습니다")
    if task["status"] != "completed":
        raise HTTPException(400, f"작업 미완료 (status: {task['status']})")
    return task["result"]


@router.post("/save-result")
async def save_detection_result(
    slide_id: str = Form(...),
    tissue_type: str = Form("Stomach"),
    result: str = Form(...),
):
    """
    검출 결과를 서버 내부 AI 결과 폴더에 저장 (다운로드 X).
    파일: AI_RESULTS_DIR/{slide_stem}_HE-Fit_{tissue_type}.json
    """
    info = slide_manager.get(slide_id)
    if not info:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")

    try:
        result_obj = json.loads(result)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid JSON: {e}")

    cache_path = _get_ai_cache_path(info.file_path, tissue_type)
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(result_obj, f)
    except Exception as e:
        raise HTTPException(500, f"Save failed: {e}")

    return {
        "saved": True,
        "path": str(cache_path),
        "filename": cache_path.name,
        "total_cells": result_obj.get("total_cells", 0),
    }
