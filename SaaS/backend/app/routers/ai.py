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

from fastapi import APIRouter, HTTPException, Form, Query
from fastapi.responses import JSONResponse, FileResponse

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
    HE-Fit 결과 캐시: ai_results/HE-Fit/{slide_stem}_HE-Fit_{tissue_type}.json
    레거시 경로 (ai_results/{slide_stem}_HE-Fit_{tissue_type}.json) 가 있으면
    새 위치로 자동 이동한다.
    """
    p = Path(slide_path)
    cache_dir = Path(settings.AI_RESULTS_DIR) / "HE-Fit"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    new_path = cache_dir / f"{p.stem}_HE-Fit_{tissue_type}.json"
    legacy_path = Path(settings.AI_RESULTS_DIR) / f"{p.stem}_HE-Fit_{tissue_type}.json"
    if not new_path.exists() and legacy_path.exists():
        try:
            legacy_path.replace(new_path)
        except Exception as e:
            print(f"[ai] HE-Fit legacy migration failed: {e}")
    return new_path


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


# ═══════════════════════════════════════════════════════════════════
# Virtual Stain (VS-IHC) — IHC → H&E
# ═══════════════════════════════════════════════════════════════════

VS_MODEL_FILES = {
    "ihc_membrane": "IHC_HnE_virtual_stain_membrane.pth",
    # nucleus 모델은 아직 학습 안 됨 — 추가 시 여기에 등록
}


def _get_vs_cache_paths(slide_path: str, stain_type: str, target_mpp: float = 2.0):
    """
    Virtual stain 결과 캐시: ai_results/VS-IHC/{slide_stem}_VS-IHC_{stain}_mpp{p}.{png|json}
    타일 피라미드는 sibling 폴더: ..._tile/{level}/{tx}_{ty}.jpeg
    레거시 (ai_results 루트) 경로가 있으면 새 위치로 자동 이동.
    """
    p = Path(slide_path)
    cache_dir = Path(settings.AI_RESULTS_DIR) / "VS-IHC"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    mpp_str = f"{target_mpp:g}".replace(".", "p")
    base_name = f"{p.stem}_VS-IHC_{stain_type}_mpp{mpp_str}"
    new_png = (cache_dir / base_name).with_suffix(".png")
    new_meta = (cache_dir / base_name).with_suffix(".json")

    legacy_dir = Path(settings.AI_RESULTS_DIR)
    legacy_png = (legacy_dir / base_name).with_suffix(".png")
    legacy_meta = (legacy_dir / base_name).with_suffix(".json")
    legacy_tile = legacy_dir / f"{base_name}_tile"

    for src, dst in ((legacy_png, new_png), (legacy_meta, new_meta)):
        if src.exists() and not dst.exists():
            try:
                src.replace(dst)
            except Exception as e:
                print(f"[ai] VS legacy migration failed ({src.name}): {e}")
    if legacy_tile.exists() and not (cache_dir / f"{base_name}_tile").exists():
        try:
            legacy_tile.replace(cache_dir / f"{base_name}_tile")
        except Exception as e:
            print(f"[ai] VS legacy tile dir migration failed: {e}")
    return new_png, new_meta


def _get_vs_tile_dir(slide_path: str, stain_type: str, target_mpp: float = 2.0) -> Path:
    """VS 타일 피라미드 폴더: {png_parent}/{png_stem}_tile/"""
    png_path, _ = _get_vs_cache_paths(slide_path, stain_type, target_mpp)
    return png_path.parent / f"{png_path.stem}_tile"


def _generate_vs_tiles(output_canvas, tile_dir: Path,
                       tile_size: int = 512, n_levels: int = 4,
                       quality: int = 88) -> list[dict]:
    """
    output_canvas (uint8 H×W×3 또는 H×W×4) → 4단계 피라미드 JPEG 타일 생성.
    레벨 0 = 원본 해상도, 각 레벨은 /2 다운샘플.
    완전히 흰 타일은 스킵 (서빙 시 404 → 프론트에서 무시).
    반환: [{"level":0,"width":W,"height":H,"nx":..,"ny":..,"tile_count":..}, ...]
    """
    import numpy as np
    from PIL import Image

    if tile_dir.exists():
        # 기존 타일 제거 (재생성 시 stale 제거)
        try:
            import shutil
            shutil.rmtree(tile_dir)
        except Exception:
            pass
    tile_dir.mkdir(parents=True, exist_ok=True)

    # RGBA → RGB (alpha=0 영역은 흰색 배경으로 합성해 JPEG 저장)
    if output_canvas.ndim == 3 and output_canvas.shape[2] == 4:
        rgb = output_canvas[:, :, :3].copy()
        a = output_canvas[:, :, 3]
        mask = a < 255
        if mask.any():
            rgb[mask] = 255
        pil = Image.fromarray(rgb, 'RGB')
    else:
        pil = Image.fromarray(output_canvas, 'RGB')

    levels_meta: list[dict] = []
    current = pil
    for lv in range(n_levels):
        w, h = current.size
        nx = (w + tile_size - 1) // tile_size
        ny = (h + tile_size - 1) // tile_size
        level_dir = tile_dir / str(lv)
        level_dir.mkdir(parents=True, exist_ok=True)

        arr = np.asarray(current)
        count = 0
        for ty in range(ny):
            for tx in range(nx):
                left = tx * tile_size
                upper = ty * tile_size
                right = min(left + tile_size, w)
                lower = min(upper + tile_size, h)
                patch = arr[upper:lower, left:right]
                # 거의 전부 흰색이면 스킵 (디스크 절약)
                if patch.size == 0:
                    continue
                if patch.min() >= 248:
                    continue
                tile_img = Image.fromarray(patch, 'RGB')
                tile_img.save(level_dir / f"{tx}_{ty}.jpeg", "JPEG",
                              quality=quality, optimize=False)
                count += 1

        levels_meta.append({
            "level": lv, "width": int(w), "height": int(h),
            "nx": int(nx), "ny": int(ny), "tile_count": int(count),
        })

        if lv < n_levels - 1:
            new_w = max(1, w // 2)
            new_h = max(1, h // 2)
            current = current.resize((new_w, new_h), Image.BILINEAR)

    return levels_meta


def _run_virtual_stain(task_id: str, slide_id: str,
                       roi_polygons, stain_type: str,
                       target_mpp: float = 2.0):
    """
    Virtual staining 백그라운드 작업.
    desktop ai/virtual_stain.py 의 VirtualStainWorker.run() 로직을 그대로 옮김.
    Qt 시그널 대신 _update_task() 사용.
    """
    try:
        import torch
        import numpy as np
        from PIL import Image
        import openslide

        from ai.virtual_stain import (
            Generator, _make_blend_weight, _read_patch, VirtualStainWorker
        )

        # Pillow의 decompression-bomb 가드 해제 (VS composite 가 수억 px 일 수 있음)
        Image.MAX_IMAGE_PIXELS = None

        info = slide_manager.get(slide_id)
        if not info:
            _update_task(task_id, status="error", error="슬라이드를 찾을 수 없습니다")
            return

        # ── ROI 폴리곤 보관 (표시 클립용; 추론은 항상 전체로 수행) ──
        # 추론/저장은 ROI 무시하고 전체로 진행해 캐시를 만든다.
        # 단, 사용자가 ROI를 지정한 경우 그 폴리곤은 결과에 그대로 담아 프론트에서
        # 오버레이를 ROI 영역으로만 클립해 보여주도록 한다.
        display_roi_polygons = roi_polygons
        roi_polygons = None  # 전체 추론 강제

        # ── 캐시 확인 ──
        png_path, meta_path = _get_vs_cache_paths(info.file_path, stain_type, target_mpp)
        if png_path.exists() and meta_path.exists():
            try:
                _update_task(task_id, status="running", progress=10,
                             status_msg=f"Loading cached virtual stain: {png_path.name}")
                with open(meta_path, 'r', encoding='utf-8') as f:
                    cached_meta = json.load(f)

                # 레거시 캐시: 타일 피라미드가 없으면 PNG에서 1회 업그레이드 생성
                tile_dir = _get_vs_tile_dir(info.file_path, stain_type, target_mpp)
                if (not cached_meta.get("levels")) or (not tile_dir.exists()):
                    try:
                        _update_task(task_id, progress=30,
                                     status_msg="Upgrading legacy cache → tile pyramid...")
                        legacy_png = Image.open(str(png_path))
                        if legacy_png.mode == 'RGBA':
                            bg = Image.new('RGB', legacy_png.size, (255, 255, 255))
                            bg.paste(legacy_png, mask=legacy_png.split()[3])
                            legacy_arr = np.asarray(bg)
                        else:
                            legacy_arr = np.asarray(legacy_png.convert('RGB'))
                        tile_size_px = int(cached_meta.get("tile_size", 512))
                        levels_meta = _generate_vs_tiles(
                            legacy_arr, tile_dir,
                            tile_size=tile_size_px, n_levels=4,
                        )
                        cached_meta['tile_size'] = tile_size_px
                        cached_meta['levels'] = levels_meta
                        with open(meta_path, 'w', encoding='utf-8') as f:
                            json.dump(cached_meta, f)
                    except Exception as e:
                        import traceback
                        print(f"VS legacy tile upgrade failed: {e}\n{traceback.format_exc()}")

                cached_meta['image_filename'] = png_path.name
                cached_meta['cached'] = True
                if display_roi_polygons is not None:
                    cached_meta['roi_polygons'] = display_roi_polygons
                _update_task(task_id, status="completed", progress=100,
                             status_msg="Loaded cached virtual stain",
                             result=cached_meta)
                return
            except Exception as e:
                print(f"VS cache load failed, running fresh: {e}")

        # ── 모델 경로 확인 ──
        model_filename = VS_MODEL_FILES.get(stain_type)
        if not model_filename:
            _update_task(task_id, status="error",
                         error=f"Unknown stain type: {stain_type}")
            return
        model_path = Path(settings.MODEL_DIR) / model_filename
        if not model_path.exists():
            _update_task(task_id, status="error",
                         error=f"Virtual stain model not found: {model_path}")
            return

        _update_task(task_id, status="running", progress=1,
                     status_msg="Loading virtual stain model...")

        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        use_fp16 = (device.type == 'cuda')

        generator = Generator(3, 3).to(device)
        generator.load_state_dict(torch.load(str(model_path), map_location=device))
        generator.eval()
        if use_fp16:
            generator = generator.half()

        _update_task(task_id, progress=3, status_msg="Opening slide...")

        slide_path = info.file_path
        slide = openslide.OpenSlide(slide_path)

        # target_mpp is provided as parameter
        patch_size = 512
        batch_size = 4

        native_mpp = float(slide.properties.get('openslide.mpp-x', 0.25))
        downsample_factor = target_mpp / native_mpp
        ps = patch_size
        overlap = ps // 4
        stride = ps - overlap
        read_size = int(ps * downsample_factor)
        read_stride = int(stride * downsample_factor)

        best_level = slide.get_best_level_for_downsample(downsample_factor)
        level_ds = slide.level_downsamples[best_level]
        level_read = int(read_size / level_ds)

        W, H = slide.dimensions

        # ROI bounds 계산 (폴리곤 → bounding box)
        roi_bounds = None
        if roi_polygons:
            xs = [p[0] for poly in roi_polygons for p in poly]
            ys = [p[1] for poly in roi_polygons for p in poly]
            roi_bounds = (
                max(0, int(min(xs))), max(0, int(min(ys))),
                min(W, int(max(xs))), min(H, int(max(ys))),
            )

        if roi_bounds:
            x_min, y_min, x_max, y_max = roi_bounds
        else:
            x_min, y_min, x_max, y_max = 0, 0, W, H

        # ROI가 한 패치보다 작으면 read_size로 확장 (슬라이드 경계 안에서 클램프)
        if x_max - x_min < read_size:
            cx = (x_min + x_max) // 2
            x_min = max(0, cx - read_size // 2)
            x_max = min(W, x_min + read_size)
            x_min = max(0, x_max - read_size)
        if y_max - y_min < read_size:
            cy = (y_min + y_max) // 2
            y_min = max(0, cy - read_size // 2)
            y_max = min(H, y_min + read_size)
            y_min = max(0, y_max - read_size)

        if W < read_size or H < read_size:
            _update_task(task_id, status="error",
                         error=f"Slide too small for target_mpp={target_mpp} "
                               f"(needs >= {read_size}px at level-0, slide is {W}x{H}).")
            slide.close()
            return

        pos_x = list(range(x_min, x_max - read_size + 1, read_stride))
        pos_y = list(range(y_min, y_max - read_size + 1, read_stride))
        if not pos_x:
            pos_x = [x_min]
        if not pos_y:
            pos_y = [y_min]
        if pos_x[-1] + read_size < x_max:
            pos_x.append(max(pos_x[-1] + read_stride, x_max - read_size))
        if pos_y[-1] + read_size < y_max:
            pos_y.append(max(pos_y[-1] + read_stride, y_max - read_size))

        n_px, n_py = len(pos_x), len(pos_y)
        out_w = (n_px - 1) * stride + ps
        out_h = (n_py - 1) * stride + ps
        canvas_l0_w = pos_x[-1] + read_size - x_min
        canvas_l0_h = pos_y[-1] + read_size - y_min

        _update_task(task_id, progress=5, status_msg="Creating tissue mask...")

        # tissue grid 빌드는 worker의 메서드를 직접 호출 (인스턴스 불필요한 staticmethod 형태가 아니라
        # 인스턴스 메서드여서 래핑 필요) — 가장 단순한 방법: dummy worker 인스턴스 생성
        dummy_worker = VirtualStainWorker(
            image_path=slide_path,
            model_path=str(model_path),
            stain_type=stain_type,
            target_mpp=target_mpp,
            patch_size=patch_size,
            batch_size=batch_size,
            roi_bounds=roi_bounds,
            roi_polygons=roi_polygons,
        )
        tissue_grid, tissue_pixel_mask = dummy_worker._build_tissue_grid(
            slide, x_min, y_min, canvas_l0_w, canvas_l0_h,
            n_px, n_py, stride, ps, out_w, out_h,
        )
        tissue_total = int(tissue_grid.sum())
        _update_task(task_id, progress=8,
                     status_msg=f"Grid {n_px}x{n_py}: {tissue_total} tissue patches")

        # ── 패치 리스트 ──
        all_patches = []
        for yi in range(n_py):
            for xi in range(n_px):
                x0 = pos_x[xi]
                y0 = pos_y[yi]
                out_of_bounds = (x0 + read_size > W) or (y0 + read_size > H)
                is_tissue = bool(tissue_grid[yi, xi]) and not out_of_bounds
                all_patches.append((xi, yi, x0, y0,
                                    xi * stride, yi * stride, is_tissue))

        # ── 누적 캔버스 ──
        blend_weight = _make_blend_weight(ps, overlap)
        blend_3ch = blend_weight[:, :, None]
        output_acc = np.zeros((out_h, out_w, 3), dtype=np.float32)
        input_acc = np.zeros((out_h, out_w, 3), dtype=np.float32)
        weight_acc = np.zeros((out_h, out_w), dtype=np.float32)

        tissue_count = 0
        bs = batch_size
        io_workers = min(max(2, os.cpu_count() or 4), 8)
        tissue_batch = []

        with torch.inference_mode(), ThreadPoolExecutor(max_workers=io_workers) as pool:
            futures = []
            for (xi, yi, x0, y0, px, py_c, is_tissue) in all_patches:
                f = pool.submit(_read_patch, slide_path, x0, y0,
                                best_level, level_read, ps, None, None)
                futures.append(f)

            for patch_idx, (xi, yi, x0, y0, px, py_c, is_tissue) in enumerate(all_patches):
                region_np = futures[patch_idx].result()
                input_acc[py_c:py_c + ps, px:px + ps] += region_np * blend_3ch

                if not is_tissue:
                    output_acc[py_c:py_c + ps, px:px + ps] += region_np * blend_3ch
                    weight_acc[py_c:py_c + ps, px:px + ps] += blend_weight
                else:
                    t = torch.from_numpy(region_np).permute(2, 0, 1)
                    t = t / 255.0 * 2.0 - 1.0
                    tissue_batch.append((px, py_c, t))

                is_end_of_row = (xi == n_px - 1)
                batch_full = len(tissue_batch) >= bs
                if tissue_batch and (batch_full or is_end_of_row):
                    VirtualStainWorker._run_batch(
                        generator, device, use_fp16, tissue_batch,
                        output_acc, weight_acc, blend_3ch, blend_weight, ps,
                    )
                    tissue_count += len(tissue_batch)
                    tissue_batch.clear()

                if is_end_of_row:
                    pct = 8 + int(87 * (yi + 1) / n_py)
                    _update_task(task_id, progress=pct,
                                 status_msg=f"Virtual staining... row {yi + 1}/{n_py} "
                                            f"({tissue_count} tissue patches)")

        if tissue_batch:
            VirtualStainWorker._run_batch(
                generator, device, use_fp16, tissue_batch,
                output_acc, weight_acc, blend_3ch, blend_weight, ps,
            )
            tissue_count += len(tissue_batch)
            tissue_batch.clear()

        _update_task(task_id, progress=96, status_msg="Composing final image...")

        # ── Compose ──
        uncovered = weight_acc < 0.01
        weight_acc = np.maximum(weight_acc, 1e-10)
        output_canvas = (output_acc / weight_acc[:, :, None]).clip(0, 255).astype(np.uint8)
        input_canvas = (input_acc / weight_acc[:, :, None]).clip(0, 255).astype(np.uint8)
        output_canvas[uncovered] = 255
        input_canvas[uncovered] = 255
        output_canvas[~tissue_pixel_mask] = input_canvas[~tissue_pixel_mask]

        # ── Polygon ROI 마스킹 → RGBA ──
        import cv2
        alpha = np.full((out_h, out_w), 255, dtype=np.uint8)
        if roi_polygons:
            scale_x = out_w / canvas_l0_w
            scale_y = out_h / canvas_l0_h
            poly_mask = np.zeros((out_h, out_w), dtype=np.uint8)
            for poly_coords in roi_polygons:
                pts = np.array([
                    [round((x - x_min) * scale_x), round((y - y_min) * scale_y)]
                    for x, y in poly_coords
                ], dtype=np.int32)
                cv2.fillPoly(poly_mask, [pts], 255)
            alpha = poly_mask

        rgba = np.dstack([output_canvas, alpha])

        # ── 캐시 저장 (전체 추론만 도달; ROI는 위에서 캐시 hit 또는 폴리곤 무시) ──
        levels_meta = []
        tile_size_px = 512
        try:
            _update_task(task_id, progress=97, status_msg="Saving composite PNG...")
            Image.fromarray(rgba, 'RGBA').save(str(png_path), format='PNG', optimize=False)

            _update_task(task_id, progress=98, status_msg="Generating tile pyramid...")
            tile_dir = _get_vs_tile_dir(info.file_path, stain_type, target_mpp)
            levels_meta = _generate_vs_tiles(
                output_canvas, tile_dir,
                tile_size=tile_size_px, n_levels=4,
            )

            meta = {
                "stain_type": stain_type,
                "roi_origin": [int(x_min), int(y_min)],
                "canvas_l0_w": int(canvas_l0_w),
                "canvas_l0_h": int(canvas_l0_h),
                "target_mpp": target_mpp,
                "tissue_count": int(tissue_count),
                "total_patches": int(n_px * n_py),
                "image_filename": png_path.name,
                "tile_size": tile_size_px,
                "levels": levels_meta,
            }
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f)
            print(f"VS result cached: {png_path} + {len(levels_meta)} pyramid levels")
        except Exception as e:
            import traceback
            print(f"VS cache save failed: {e}\n{traceback.format_exc()}")

        result_payload = {
            "stain_type": stain_type,
            "image_filename": png_path.name,
            "roi_origin": [int(x_min), int(y_min)],
            "canvas_l0_w": int(canvas_l0_w),
            "canvas_l0_h": int(canvas_l0_h),
            "target_mpp": target_mpp,
            "tissue_count": int(tissue_count),
            "total_patches": int(n_px * n_py),
            "tile_size": tile_size_px,
            "levels": levels_meta,
            "cached": False,
        }
        if display_roi_polygons is not None:
            result_payload["roi_polygons"] = display_roi_polygons
        _update_task(task_id, status="completed", progress=100,
                     status_msg=f"Virtual staining complete — {tissue_count}/{n_px * n_py} patches",
                     result=result_payload)

        del generator
        slide.close()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    except Exception as e:
        import traceback
        _update_task(task_id, status="error",
                     error=f"Virtual staining failed: {e}\n{traceback.format_exc()}")


@router.post("/virtual-stain")
async def start_virtual_stain(
    slide_id: str = Form(...),
    stain_type: str = Form("ihc_membrane"),
    target_mpp: float = Form(2.0),
    roi_polygons: Optional[str] = Form(None),
):
    """Virtual stain (VS-IHC) 작업 시작 (비동기)"""
    info = slide_manager.get(slide_id)
    if not info:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")
    if stain_type not in VS_MODEL_FILES:
        raise HTTPException(400, f"Unknown stain type: {stain_type}")

    polygons = json.loads(roi_polygons) if roi_polygons else None
    task_id = uuid.uuid4().hex[:12]

    with _tasks_lock:
        _tasks[task_id] = {
            "status": "queued", "progress": 0,
            "result": None, "error": None, "status_msg": "",
        }

    t = threading.Thread(
        target=_run_virtual_stain,
        args=(task_id, slide_id, polygons, stain_type, target_mpp),
        daemon=True,
    )
    t.start()
    return {"task_id": task_id, "status": "queued"}


@router.get("/virtual-stain/{slide_id}/{stain_type}.png")
async def get_virtual_stain_image(slide_id: str, stain_type: str,
                                  target_mpp: float = Query(2.0)):
    """Virtual stain 캐시 PNG 서빙 (전체 추론 결과, PDF/리포트용)"""
    info = slide_manager.get(slide_id)
    if not info:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")
    png_path, _ = _get_vs_cache_paths(info.file_path, stain_type, target_mpp)
    if not png_path.exists():
        raise HTTPException(404, "Virtual stain image not found")
    return FileResponse(str(png_path), media_type="image/png")


@router.get("/virtual-stain/{slide_id}/{stain_type}/tile/{level}/{tx}_{ty}.jpeg")
async def get_virtual_stain_tile(
    slide_id: str,
    stain_type: str,
    level: int,
    tx: int,
    ty: int,
    target_mpp: float = Query(2.0),
):
    """
    Virtual stain 피라미드 타일 서빙.
    디스크에 있으면 정적 서빙, 없으면 404 (빈/흰 타일은 생성 안 함).
    """
    info = slide_manager.get(slide_id)
    if not info:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")
    tile_dir = _get_vs_tile_dir(info.file_path, stain_type, target_mpp)
    tile_path = tile_dir / str(level) / f"{tx}_{ty}.jpeg"
    if not tile_path.exists():
        raise HTTPException(404, "tile not found")
    return FileResponse(
        str(tile_path),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=604800"},
    )
