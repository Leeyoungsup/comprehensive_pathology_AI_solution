"""
AI 분석 API — Detection / Segmentation
기존 ai/ 모듈을 그대로 사용하여 서버에서 추론 실행
"""

import sys
import json
import uuid
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Form, Query
from fastapi.responses import JSONResponse

from app.config import settings
from app.slide_manager import slide_manager

# 기존 AI 코드 경로 추가
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

router = APIRouter()

# AI 작업 상태 추적
_tasks = {}  # {task_id: {"status": str, "progress": int, "result": dict|None, "error": str|None}}
_tasks_lock = threading.Lock()


def _run_detection(task_id: str, slide_id: str, roi_polygons: Optional[list], tissue_type: str):
    """백그라운드 검출 실행 (기존 detection.py 로직 활용)"""
    try:
        import torch
        import numpy as np

        info = slide_manager.get(slide_id)
        if not info:
            with _tasks_lock:
                _tasks[task_id]["status"] = "error"
                _tasks[task_id]["error"] = "슬라이드를 찾을 수 없습니다"
            return

        with _tasks_lock:
            _tasks[task_id]["status"] = "running"
            _tasks[task_id]["progress"] = 5

        # 기존 AI 모듈 임포트
        from ai.detection import non_max_suppression, CLASS_NAMES, CLASS_COLORS
        from ai.nets import nn as yolo_nn

        # 모델 로드
        model_path = Path(settings.MODEL_DIR) / "HnE_detection.pt"
        if not model_path.exists():
            with _tasks_lock:
                _tasks[task_id]["status"] = "error"
                _tasks[task_id]["error"] = f"모델 파일 없음: {model_path}"
            return

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = yolo_nn.YOLOv11(str(model_path), device)

        with _tasks_lock:
            _tasks[task_id]["progress"] = 10

        # 슬라이드에서 패치 단위 추론 (간소화 버전)
        slide = info.slide
        width, height = info.dimensions
        image_size = 1024
        output_mpp = 0.5
        origin_mpp = info.mpp
        original_size = int(image_size * output_mpp / origin_mpp)
        magnification = original_size / image_size

        all_cells = []
        total_patches = max(1, (width // image_size) * (height // image_size))
        processed = 0

        for px in range(0, width - image_size, image_size):
            for py in range(0, height - image_size, image_size):
                # ROI 체크
                if roi_polygons:
                    # 간단한 바운딩박스 체크
                    in_roi = False
                    center_x, center_y = px + image_size // 2, py + image_size // 2
                    for poly in roi_polygons:
                        xs = [p[0] for p in poly]
                        ys = [p[1] for p in poly]
                        if min(xs) <= center_x <= max(xs) and min(ys) <= center_y <= max(ys):
                            in_roi = True
                            break
                    if not in_roi:
                        processed += 1
                        continue

                try:
                    # 패치 읽기
                    tile = slide.read_region((px, py), 0, (original_size, original_size))
                    tile_rgb = tile.convert("RGB")
                    tile_resized = tile_rgb.resize((image_size, image_size))

                    # numpy → tensor
                    img_np = np.array(tile_resized).astype(np.float32) / 255.0
                    img_tensor = torch.from_numpy(img_np).permute(2, 0, 1).unsqueeze(0).to(device)

                    # 추론
                    with torch.no_grad():
                        outputs = model(img_tensor)

                    # NMS
                    results = non_max_suppression(outputs, confidence_threshold=0.01, iou_threshold=0.35)

                    for det in results:
                        if len(det) == 0:
                            continue
                        det_np = det.cpu().numpy()
                        for d in det_np:
                            cx = (d[0] + d[2]) / 2 * magnification + px
                            cy = (d[1] + d[3]) / 2 * magnification + py
                            conf = float(d[4])
                            cls_id = int(d[5])
                            all_cells.append({
                                "x": float(cx),
                                "y": float(cy),
                                "confidence": conf,
                                "class_id": cls_id,
                                "class_name": CLASS_NAMES.get(cls_id, "Unknown"),
                            })
                except Exception as e:
                    pass  # 개별 패치 실패는 무시

                processed += 1
                pct = int(10 + (processed / total_patches) * 85)
                with _tasks_lock:
                    _tasks[task_id]["progress"] = min(pct, 95)

        # 완료
        result = {
            "total_cells": len(all_cells),
            "cells": all_cells,
            "class_names": CLASS_NAMES,
            "class_colors": CLASS_COLORS,
        }

        with _tasks_lock:
            _tasks[task_id]["status"] = "completed"
            _tasks[task_id]["progress"] = 100
            _tasks[task_id]["result"] = result

    except Exception as e:
        with _tasks_lock:
            _tasks[task_id]["status"] = "error"
            _tasks[task_id]["error"] = str(e)


# ── API 엔드포인트 ──

@router.post("/detect")
async def start_detection(
    slide_id: str = Form(...),
    roi_polygons: Optional[str] = Form(None),  # JSON string
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
            "status": "queued",
            "progress": 0,
            "result": None,
            "error": None,
        }

    # 백그라운드 스레드에서 실행
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
        raise HTTPException(400, f"작업이 완료되지 않았습니다 (status: {task['status']})")

    return task["result"]
