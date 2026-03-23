# HnE Cell Detection API 명세서

> **버전**: v1.0 (Draft)  
> **작성일**: 2026-03-06  
> **프로젝트**: Comprehensive Pathology AI Solution  
> **Base URL**: `http://{host}:{port}/api/v1`

---

## 개요

H&E 염색 병리 이미지(WSI)에서 세포를 검출하고, Breast/Stomach 조직인 경우 Epithelial 세포를 Tumor/Benign으로 자동 재분류하는 REST API입니다.

### 처리 파이프라인

```
WSI 업로드 → 세포 검출 (YOLOv11, 6 class)
                ↓
         tissue_type == Breast 또는 Stomach?
           ├── Yes → Segmentation (DeepLabV3+) → Epithelial 재분류 (DBSCAN) → 8 class 결과
           └── No  → 6 class 결과 그대로 반환
```

### 검출 클래스 (8종)

| cls_id | 클래스명 | 색상 (HEX) | 비고 |
|--------|----------|-----------|------|
| 0 | Neutrophil | `#FF4500` | 기본 검출 |
| 1 | Epithelial | `#00FF00` | 기본 검출 (재분류 시 6/7로 변환) |
| 2 | Lymphocyte | `#0000FF` | 기본 검출 |
| 3 | Plasma | `#FFFF00` | 기본 검출 |
| 4 | Eosinophil | `#8A2BE2` | 기본 검출 |
| 5 | Connective tissue | `#808080` | 기본 검출 |
| 6 | Tumor Epithelial | `#FF0000` | Epithelial 재분류 결과 |
| 7 | Benign Epithelial | `#00FF00` | Epithelial 재분류 결과 |

### Segmentation 클래스 (4종, 재분류 시 내부 사용)

| seg_id | 클래스명 |
|--------|----------|
| 0 | Background |
| 1 | Stroma |
| 2 | Non_Tumor |
| 3 | Tumor |

---

## 인증

> 추후 결정 (API Key / JWT / OAuth2 등)

```
Authorization: Bearer {token}
```

---

## 엔드포인트 목록

| Method | Endpoint | 설명 |
|--------|----------|------|
| `POST` | `/detection/analyze` | WSI 파일 업로드 + 검출 (동기) |
| `POST` | `/detection/analyze/async` | WSI 파일 업로드 + 검출 (비동기) |
| `GET` | `/detection/tasks/{task_id}` | 비동기 작업 상태 조회 |
| `GET` | `/detection/tasks/{task_id}/result` | 비동기 작업 결과 조회 |
| `DELETE` | `/detection/tasks/{task_id}` | 작업 취소 / 결과 삭제 |
| `GET` | `/detection/models` | 사용 가능한 모델 목록 |
| `GET` | `/detection/health` | 서비스 상태 확인 |

---

## 1. 동기 검출 (소규모 슬라이드 / ROI 지정 시)

### `POST /detection/analyze`

ROI가 지정되었거나 소규모 이미지인 경우, 응답을 기다리며 한 번에 결과를 받습니다.

#### Request

**Content-Type**: `multipart/form-data`

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|----------|------|------|--------|------|
| `file` | `file` | ✅ | - | WSI 파일 (`.svs`, `.ndpi`, `.tiff`, `.tif`, `.mrxs`, `.scn`, `.png`, `.jpg`) |
| `tissue_type` | `string` | ✅ | - | 조직 타입: `Breast`, `Stomach`, `Other` |
| `roi` | `string (JSON)` | ❌ | `null` | ROI 영역 (폴리곤 좌표 배열) |
| `confidence_threshold` | `float` | ❌ | `0.01` | 전역 confidence 임계값 (0.0 ~ 1.0) |
| `class_thresholds` | `string (JSON)` | ❌ | `null` | 클래스별 confidence 임계값 |
| `iou_threshold` | `float` | ❌ | `0.35` | NMS IoU 임계값 |
| `auto_epithelial_classify` | `boolean` | ❌ | `true` | Epithelial 자동 재분류 여부 (Breast/Stomach만 적용) |
| `include_segmentation` | `boolean` | ❌ | `false` | Segmentation 마스크 포함 여부 |

#### ROI 형식

```json
{
  "roi": [
    {
      "type": "Polygon",
      "coordinates": [[100, 200], [500, 200], [500, 600], [100, 600]]
    },
    {
      "type": "Rectangle",
      "x": 1000,
      "y": 2000,
      "width": 5000,
      "height": 5000
    }
  ]
}
```

#### 클래스별 Confidence 임계값

```json
{
  "class_thresholds": {
    "0": 0.3,
    "1": 0.2,
    "2": 0.25,
    "3": 0.3,
    "4": 0.3,
    "5": 0.2
  }
}
```

#### Response (200 OK)

```json
{
  "status": "success",
  "task_id": "det_20260306_abc123",
  "processing_time_sec": 45.2,
  "metadata": {
    "image_name": "slide_001.svs",
    "image_dimensions": [100000, 80000],
    "mpp": 0.25,
    "tissue_type": "Breast",
    "model_name": "HnE_detection",
    "model_version": "YOLOv11m",
    "auto_epithelial_classify": true,
    "roi_applied": true
  },
  "summary": {
    "total_cells": 15432,
    "class_counts": {
      "Neutrophil": 234,
      "Epithelial": 0,
      "Lymphocyte": 5621,
      "Plasma": 1203,
      "Eosinophil": 89,
      "Connective tissue": 3412,
      "Tumor Epithelial": 3156,
      "Benign Epithelial": 1717
    },
    "epithelial_breakdown": {
      "total_original_epithelial": 4873,
      "reclassified_to_tumor": 3156,
      "reclassified_to_benign": 1717,
      "tumor_ratio": 0.648
    }
  },
  "cells": [
    {
      "x": 1024.5,
      "y": 2048.3,
      "cls_id": 6,
      "cls_name": "Tumor Epithelial",
      "confidence": 0.91
    },
    {
      "x": 1100.2,
      "y": 2100.7,
      "cls_id": 2,
      "cls_name": "Lymphocyte",
      "confidence": 0.87
    }
  ],
  "segmentation": null
}
```

#### Response (tissue_type = "Other", 재분류 없음)

```json
{
  "status": "success",
  "summary": {
    "total_cells": 8320,
    "class_counts": {
      "Neutrophil": 120,
      "Epithelial": 3500,
      "Lymphocyte": 2800,
      "Plasma": 600,
      "Eosinophil": 50,
      "Connective tissue": 1250,
      "Tumor Epithelial": 0,
      "Benign Epithelial": 0
    },
    "epithelial_breakdown": null
  },
  "cells": []
}
```

#### Segmentation 포함 응답 (`include_segmentation=true`)

```json
{
  "segmentation": {
    "mask_shape": [2000, 1600],
    "output_mpp": 4.0,
    "wsi_mpp": 0.25,
    "region_offset": [0, 0],
    "class_names": ["Background", "Stroma", "Non_Tumor", "Tumor"],
    "class_polygons": {
      "1": [[[x1, y1], [x2, y2], ...]],
      "2": [[[x1, y1], [x2, y2], ...]],
      "3": [[[x1, y1], [x2, y2], ...]]
    },
    "polygon_coordinate_system": "wsi_level0"
  }
}
```

---

## 2. 비동기 검출 (대용량 WSI)

### `POST /detection/analyze/async`

대용량 슬라이드의 경우, 작업을 큐에 등록하고 `task_id`를 즉시 반환합니다.

#### Request

동기 API와 동일한 파라미터.

추가 파라미터:

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|----------|------|------|--------|------|
| `callback_url` | `string` | ❌ | `null` | 완료 시 결과를 POST할 webhook URL |
| `priority` | `string` | ❌ | `normal` | 작업 우선순위: `low`, `normal`, `high` |

#### Response (202 Accepted)

```json
{
  "status": "accepted",
  "task_id": "det_20260306_abc123",
  "message": "작업이 큐에 등록되었습니다.",
  "estimated_time_sec": 120,
  "poll_url": "/api/v1/detection/tasks/det_20260306_abc123",
  "result_url": "/api/v1/detection/tasks/det_20260306_abc123/result"
}
```

---

### `GET /detection/tasks/{task_id}`

#### Response (200 OK)

```json
{
  "task_id": "det_20260306_abc123",
  "status": "processing",
  "progress": 65,
  "current_step": "Epithelial 세포 재분류 중...",
  "steps": [
    {"name": "슬라이드 로딩", "status": "completed"},
    {"name": "조직 영역 감지", "status": "completed"},
    {"name": "세포 검출", "status": "completed"},
    {"name": "Segmentation", "status": "processing", "progress": 80},
    {"name": "Epithelial 재분류", "status": "pending"},
    {"name": "결과 정리", "status": "pending"}
  ],
  "created_at": "2026-03-06T10:00:00Z",
  "started_at": "2026-03-06T10:00:02Z",
  "elapsed_sec": 45,
  "estimated_remaining_sec": 30
}
```

#### 작업 상태 값

| status | 설명 |
|--------|------|
| `queued` | 큐에서 대기 중 |
| `processing` | 처리 중 |
| `completed` | 완료 |
| `failed` | 실패 |
| `cancelled` | 취소됨 |

---

### `GET /detection/tasks/{task_id}/result`

#### Response (200 OK)

동기 API의 성공 응답과 동일한 형식.

#### Response (404 Not Found)

```json
{
  "status": "error",
  "error": {
    "code": "TASK_NOT_FOUND",
    "message": "작업을 찾을 수 없습니다."
  }
}
```

#### Response (202 Accepted, 아직 처리 중)

```json
{
  "status": "processing",
  "task_id": "det_20260306_abc123",
  "progress": 65,
  "message": "작업이 아직 처리 중입니다."
}
```

---

### `DELETE /detection/tasks/{task_id}`

진행 중인 작업을 취소하거나, 완료된 결과를 삭제합니다.

#### Response (200 OK)

```json
{
  "status": "cancelled",
  "task_id": "det_20260306_abc123",
  "message": "작업이 취소되었습니다."
}
```

---

## 3. 모델 정보

### `GET /detection/models`

#### Response (200 OK)

```json
{
  "models": [
    {
      "id": "hne_detection",
      "name": "HnE Cell Detection",
      "version": "YOLOv11m",
      "file": "HnE_detection.pt",
      "num_classes": 6,
      "classes": ["Neutrophil", "Epithelial", "Lymphocyte", "Plasma", "Eosinophil", "Connective tissue"],
      "input_size": 512,
      "patch_size_level0": 1024,
      "output_mpp": 0.5,
      "loaded": true,
      "device": "cuda:0"
    },
    {
      "id": "hne_br_segmentation",
      "name": "HnE Breast Segmentation",
      "version": "DeepLabV3Plus (EfficientNet-B5)",
      "file": "HnE_BR_segmentation.pt",
      "num_classes": 4,
      "classes": ["Background", "Stroma", "Non_Tumor", "Tumor"],
      "loaded": false,
      "device": null
    },
    {
      "id": "hne_st_segmentation",
      "name": "HnE Stomach Segmentation",
      "version": "DeepLabV3Plus (EfficientNet-B5)",
      "file": "HnE_ST_segmentation.pt",
      "num_classes": 4,
      "classes": ["Background", "Stroma", "Non_Tumor", "Tumor"],
      "loaded": false,
      "device": null
    }
  ]
}
```

---

## 4. 서비스 상태

### `GET /detection/health`

#### Response (200 OK)

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "gpu": {
    "available": true,
    "device": "NVIDIA GeForce RTX 4090",
    "memory_total_gb": 24.0,
    "memory_used_gb": 2.1,
    "cuda_version": "12.4"
  },
  "models": {
    "detection_loaded": true,
    "segmentation_breast_available": true,
    "segmentation_stomach_available": true
  },
  "uptime_sec": 3600,
  "active_tasks": 1,
  "queued_tasks": 0
}
```

---

## 에러 응답

모든 에러는 통일된 형식으로 반환됩니다.

### 형식

```json
{
  "status": "error",
  "error": {
    "code": "ERROR_CODE",
    "message": "사람이 읽을 수 있는 에러 메시지",
    "detail": "상세 정보 (선택)"
  }
}
```

### 에러 코드

| HTTP Status | Code | 설명 |
|-------------|------|------|
| 400 | `INVALID_FILE_FORMAT` | 지원하지 않는 파일 형식 |
| 400 | `INVALID_TISSUE_TYPE` | 잘못된 tissue_type 값 (Breast/Stomach/Other 아님) |
| 400 | `INVALID_ROI` | ROI 좌표 형식 오류 |
| 400 | `INVALID_THRESHOLD` | threshold 범위 오류 (0.0~1.0 밖) |
| 413 | `FILE_TOO_LARGE` | 업로드 파일 크기 초과 |
| 422 | `SLIDE_OPEN_FAILED` | WSI 파일 열기 실패 (손상된 파일 등) |
| 422 | `SEGMENTATION_NOT_AVAILABLE` | Breast/Stomach Segmentation 모델 파일 없음 |
| 500 | `MODEL_LOAD_FAILED` | 모델 로드 실패 |
| 500 | `DETECTION_FAILED` | 검출 중 내부 오류 |
| 500 | `SEGMENTATION_FAILED` | Segmentation 실행 중 내부 오류 |
| 500 | `RECLASSIFICATION_FAILED` | Epithelial 재분류 중 오류 |
| 503 | `GPU_OUT_OF_MEMORY` | GPU 메모리 부족 |
| 503 | `SERVICE_OVERLOADED` | 동시 작업 수 초과 |

---

## 데이터 흐름 상세

### Breast/Stomach 처리 (전체 파이프라인)

```
1. WSI 로드
   └─ OpenSlide.open(file)

2. 조직 마스크 생성
   └─ 썸네일 → Otsu 이진화 → 유효 패치 필터링

3. Cell Detection (YOLOv11m)
   ├─ 패치 크기: 1024×1024 (level 0) → 512×512 (resize)
   ├─ 출력 MPP: 0.5 μm/px
   ├─ NMS: IoU=0.35, conf=0.01 (클래스별 threshold)
   ├─ 병렬 I/O: 4 workers, prefetch 3 batches
   ├─ GPU batch: 8
   └─ 결과: 6 class (cls_id 0~5)

4. Segmentation (DeepLabV3+ / EfficientNet-B5)
   ├─ 모델 MPP: 1.0 μm/px
   ├─ 출력 MPP: 4.0 μm/px
   ├─ 패치: 512×512, overlap 40%
   ├─ Gaussian weighted blending
   ├─ 모델 선택: Breast → HnE_BR_segmentation.pt
   │              Stomach → HnE_ST_segmentation.pt
   └─ 결과: 4 class mask (Background/Stroma/Non_Tumor/Tumor)

5. Epithelial 재분류
   ├─ Epithelial 세포 좌표 → Segmentation 마스크 매핑
   ├─ Connected Component 분석 (Non_Tumor + Tumor 영역)
   ├─ 컴포넌트별 Tumor 비율 계산 (threshold: 10%)
   ├─ Tumor 비율 ≥ 10% → cls_id=6 (Tumor Epithelial)
   ├─ Tumor 비율 < 10% → cls_id=7 (Benign Epithelial)
   └─ cls_id=1 (Epithelial) 은 최종 결과에서 0개

6. 결과 반환
   └─ cells[], summary, segmentation(선택)
```

### Other 처리 (간단 파이프라인)

```
1. WSI 로드
2. 조직 마스크 생성
3. Cell Detection (Step 3과 동일)
4. (Segmentation/재분류 건너뜀)
5. 결과 반환 (6 class, cls_id=1 Epithelial 유지)
```

---

## 사용 예시

### cURL — 동기 검출 (Breast, ROI 지정)

```bash
curl -X POST http://localhost:8000/api/v1/detection/analyze \
  -F "file=@/path/to/slide.svs" \
  -F "tissue_type=Breast" \
  -F 'roi=[{"type":"Rectangle","x":10000,"y":20000,"width":30000,"height":30000}]' \
  -F "confidence_threshold=0.3" \
  -F "auto_epithelial_classify=true" \
  -F "include_segmentation=true"
```

### cURL — 비동기 검출 (Stomach, 전체 슬라이드)

```bash
# 1. 작업 제출
curl -X POST http://localhost:8000/api/v1/detection/analyze/async \
  -F "file=@/path/to/large_slide.svs" \
  -F "tissue_type=Stomach"

# 2. 상태 확인 (polling)
curl http://localhost:8000/api/v1/detection/tasks/det_20260306_abc123

# 3. 결과 조회
curl http://localhost:8000/api/v1/detection/tasks/det_20260306_abc123/result
```

### Python 클라이언트

```python
import requests

# 동기 검출
with open("slide.svs", "rb") as f:
    response = requests.post(
        "http://localhost:8000/api/v1/detection/analyze",
        files={"file": ("slide.svs", f)},
        data={
            "tissue_type": "Breast",
            "confidence_threshold": 0.3,
            "auto_epithelial_classify": True,
            "include_segmentation": True,
        },
    )

result = response.json()
print(f"총 {result['summary']['total_cells']}개 세포 검출")
print(f"Tumor Epithelial: {result['summary']['class_counts']['Tumor Epithelial']}")
print(f"Benign Epithelial: {result['summary']['class_counts']['Benign Epithelial']}")
```

---

## 성능 사양

| 항목 | 값 |
|------|------|
| **Detection 패치 크기** | 1024×1024 px (level 0) |
| **Detection 입력 크기** | 512×512 px (resize) |
| **Detection 출력 MPP** | 0.5 μm/px |
| **Segmentation 패치 크기** | 512×512 px |
| **Segmentation 출력 MPP** | 4.0 μm/px |
| **GPU 배치 크기** | 8 (Detection), 8 (Segmentation) |
| **I/O 워커** | 4 threads |
| **NMS IoU** | 0.35 |
| **NMS Confidence** | 0.01 (기본) |
| **Epithelial 재분류 Tumor 비율 임계값** | 10% |
| **예상 처리 시간 (40x, 50K×50K)** | 약 60~120초 (RTX 4090 기준) |
| **최대 동시 작업 수** | GPU 메모리에 따라 1~4 |

---

## Rate Limiting (추후 결정)

| 항목 | 기본값 |
|------|--------|
| 동기 요청 | 10 req/min |
| 비동기 요청 | 50 req/min |
| 최대 업로드 크기 | 10 GB |
| 결과 보관 기간 | 24시간 |

---

## Webhook (비동기 callback)

`callback_url` 지정 시, 작업 완료/실패 시 해당 URL로 POST 요청을 보냅니다.

### 완료 시

```json
{
  "event": "task.completed",
  "task_id": "det_20260306_abc123",
  "result_url": "http://host/api/v1/detection/tasks/det_20260306_abc123/result",
  "summary": {
    "total_cells": 15432,
    "processing_time_sec": 95.3
  }
}
```

### 실패 시

```json
{
  "event": "task.failed",
  "task_id": "det_20260306_abc123",
  "error": {
    "code": "DETECTION_FAILED",
    "message": "GPU 메모리 부족"
  }
}
```

---

## 향후 확장 계획

| 항목 | 설명 |
|------|------|
| PD-L1 Detection API | TPS 자동 계산 포함 |
| Batch 분석 | 여러 슬라이드 일괄 처리 |
| Streaming 결과 | SSE/WebSocket으로 실시간 진행 상황 전송 |
| 결과 캐싱 | 동일 파일 + 파라미터 조합 시 캐시 반환 |
| 모델 관리 API | 모델 업로드/교체/버전 관리 |
| 결과 내보내기 | PDF, ASAP XML, GeoJSON 형식 지원 |
