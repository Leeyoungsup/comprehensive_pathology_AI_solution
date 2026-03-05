# Comprehensive Pathology AI Solution

대용량 병리 이미지(WSI) 뷰어 + AI 분석(검출/분할/분류) 결과를 통합 시각화·검증하는 Windows 데스크톱 애플리케이션입니다.

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| **WSI 뷰어** | 타일 기반 LOD 렌더링, 줌/패닝, 미니맵 내비게이션 (0.01x ~ 40x) |
| **H&E Cell Detection** | H&E 병리 이미지에서 8종 세포 검출 + 오버레이 표시 |
| **Tumor Segmentation** | Breast/Stomach 조직 분할(Stroma / Non-Tumor / Tumor) + 마스크 오버레이 표시 |
| **Epithelial 재분류** | Segmentation 기반 상피 세포 Tumor/Benign 자동 재분류(조직 타입에 따라) |
| **PD-L1 Detection** | PD-L1 양성/음성 종양 세포 검출 및 TPS 계산 |
| **ROI 어노테이션** | 폴리곤/사각형/포인트로 분석 영역 지정(저장/불러오기 지원) |
| **결과 시각화** | 클래스 분포, 공간 히트맵, confidence 분포, 확률 맵 + **PDF 내보내기** |
| **결과 관리** | JSON 저장/불러오기, 자동 저장(옵션) |

---

## 빠른 시작 (사용자)

### Windows 독립 실행(포터블)

1. `PathologyAIViewer_Portable.zip` 다운로드
2. 압축 해제
3. `PathologyAIViewer.exe` 실행

> Python 설치 불필요 / 추가 패키지 설치 불필요

---

## 개발 환경 설정 (개발자)

### 요구사항

- **OS**: Windows 10/11 64-bit
- **Python**: 3.12
- **CUDA**: 12.x (GPU 사용 시, CPU도 지원)

### 설치/실행

```cmd
conda create -n pathology python=3.12
conda activate pathology
pip install -r requirements.txt
python main.py
```

### OpenSlide (WSI 지원)

Windows는 `libs/openslide_lib/`에 OpenSlide DLL이 포함되어 있어 별도 설치가 필요하지 않습니다.

---

## AI 모델 파일

`model/` 폴더에 아래 파일이 필요합니다.

| 파일 | 기능 |
|------|------|
| `HnE_detection.pt` | H&E 세포 검출(8종) |
| `HnE_BR_segmentation.pt` | Breast 분할 |
| `HnE_ST_segmentation.pt` | Stomach 분할 |
| `PDL1_TPS_detection.pt` | PD-L1 종양 세포 검출 + TPS |

---

## 지원 파일 형식

| 형식 | 확장자 |
|------|--------|
| Leica Aperio | `.svs` |
| Hamamatsu | `.ndpi` |
| OLYMPUS | `.vms`, `.vmu` |
| Leica SCN | `.scn` |
| 3DHISTECH MIRAX | `.mrxs` |
| BigTIFF | `.tiff`, `.tif` |
| 일반 이미지 | `.png`, `.jpg`, `.jpeg` |

---

## 사용 방법

### 기본 조작

| 동작 | 방법 |
|------|------|
| 확대/축소 | 마우스 휠(마우스 포인터 기준) |
| 화면 이동(패닝) | 좌클릭 드래그(그리기 모드가 아닐 때) / **Ctrl+좌클릭 드래그(모든 모드 공통)** |
| 미니맵 이동 | 미니맵 좌클릭(즉시 이동) / 미니맵 좌클릭 드래그(연속 이동) |
| 좌표 확인 | 마우스 이동 시 상태바에 이미지 좌표(x, y) 표시 |

### ROI 어노테이션

| 기능 | 설명 |
|------|------|
| 폴리곤 생성 | 좌클릭으로 점 추가 후 완성(아래 단축 조작 참고) |
| 폴리곤 완성 | 우클릭 / 더블클릭 / Enter |
| 자동 완성 | 시작점 근처(약 20px) 클릭 시 자동 완성 |
| 취소 | ESC(그리기 취소) |
| 선택/삭제 | 어노테이션 클릭으로 선택 → Delete로 삭제 |
| 저장/불러오기 | Annotation 패널의 Save/Load 버튼(JSON) |

---

## AI 분석 (주요 흐름)

### 1) H&E Cell Detection

1. (선택) ROI 지정 — 미지정 시 전체 슬라이드 분석
2. 조직 타입 선택: Breast / Stomach / Other
3. `(통합) Cell Detection` 실행(진행 중 재클릭 시 중단)
4. 완료 후 뷰어에 검출 결과 오버레이 표시
5. 결과 리스트에서 클래스별 표시/숨김, confidence 임계값(슬라이더)로 필터링

**검출 세포 클래스(8종)**

| 클래스 | 색상 |
|--------|------|
| Neutrophil | 주황 |
| Epithelial | 초록 |
| Lymphocyte | 파랑 |
| Plasma | 노랑 |
| Eosinophil | 보라 |
| Connective tissue | 회색 |
| Tumor Epithelial | 빨강 |
| Benign Epithelial | 하늘 |

> 조직 타입이 Breast 또는 Stomach인 경우, 검출 완료 후 세그멘테이션 기반 Epithelial 재분류가 적용될 수 있습니다.

### 2) Tumor Segmentation

1. (선택) ROI 지정
2. 조직 타입 선택: Breast / Stomach (Other는 실행 불가)
3. `Tumor Segmentation` 실행(진행 중 재클릭 시 중단)
4. 분할 결과가 마스크 오버레이로 표시되고, 결과 리스트에서 클래스별 표시/숨김 가능

### 3) 결과 시각화 + PDF

`결과 시각화` 버튼에서 다음을 확인할 수 있습니다.

- 클래스 분포(막대 그래프)
- Tumor 분석(Tumor/Benign 비율)
- 공간 히트맵(세포 밀도/확률 맵)
- confidence 분포(클래스별 히스토그램)
- **PDF 내보내기**(다이얼로그 내 버튼)

---

## 결과 저장/불러오기

| 기능 | 설명 |
|------|------|
| Save | 현재 결과를 JSON으로 저장(Detection/Segmentation 자동 분기) |
| Load | 저장된 JSON을 불러와 오버레이/리스트 복원(Detection 또는 Segmentation) |
| Clear | 현재 결과 제거 |

---

## JSON 형식

### Detection 결과(JSON)

```json
{
  "metadata": {
    "model_type": "detection",
    "model_name": "HnE Cell Detection",
    "version": "1.0",
    "timestamp": "2026-01-01T00:00:00",
    "image_path": "slide.svs",
    "image_name": "slide.svs"
  },
  "result": {
    "num_cells": 12345,
    "class_counts": {"Neutrophil": 100, "Epithelial": 200},
    "cells": [
      {"x": 1024, "y": 2048, "cls_id": 0, "confidence": 0.91}
    ]
  }
}
```

### Segmentation 결과(JSON, polygon 기반)

Segmentation은 저장 시 mask를 polygon으로 변환하여 저장하고, 로드 시 polygon을 mask로 복원하여 오버레이를 표시합니다.

```json
{
  "metadata": {
    "model_type": "segmentation",
    "model_name": "HnE_Segmentation",
    "version": "1.0",
    "timestamp": "2026-01-01T00:00:00",
    "image_path": "slide.svs",
    "image_name": "slide.svs",
    "tissue_type": "Breast"
  },
  "result": {
    "segmentation_metadata": {
      "wsi_dimensions": [100000, 80000],
      "wsi_mpp": 0.25,
      "output_mpp": 4.0,
      "mask_shape": [2000, 1600],
      "class_names": ["Background", "Stroma", "Non_Tumor", "Tumor"],
      "region_offset": [0, 0]
    },
    "roi_bounds": [0, 0, 1000, 1000],
    "roi_polygons": [],
    "class_polygons": {"1": [[[0, 0], [10, 0], [10, 10]]]},
    "polygon_coordinate_system": "wsi_level0",
    "simplification_epsilon": 2.0
  }
}
```

### ROI 어노테이션(JSON)

```json
{
  "annotations": [
    {
      "id": "...",
      "name": "ROI_1",
      "type": "Polygon",
      "coordinates": [[100.0, 200.0], [150.0, 220.0], [130.0, 260.0]],
      "color": [0, 255, 0],
      "group": "default",
      "visible": true,
      "properties": {}
    }
  ]
}
```

---

## 성능/에러 가이드

### 대용량 슬라이드 성능 팁

- 네트워크 드라이브보다 로컬 SSD 경로를 권장합니다(I/O 병목 완화).
- ROI를 지정하면 분석 범위를 줄여 실행 시간/메모리 부담을 낮출 수 있습니다.
- 오버레이 표시량이 많아 느릴 때는 결과 리스트에서 클래스 숨김 또는 confidence 임계값을 높여 표시량을 줄이세요.

### 로그/오류 확인

- 상태바/Progress: 모델 로딩, 실행, 중단, 완료, 실패 메시지 확인
- 팝업 메시지: 파일 로드/JSON 파싱/모델 로드 실패 등 즉시 안내
- 콘솔 출력: 예외 발생 시 스택트레이스가 출력될 수 있으므로(터미널/디버그 콘솔) 함께 수집하면 원인 파악이 빨라집니다.

---

## 배포 빌드 (개발자)

| 스크립트 | 기능 | 출력 |
|----------|------|------|
| `build_portable.bat` | conda-pack 기반 포터블 패키징 | `PathologyAIViewer_Portable/` |
| `build_exe.bat` | 런처 실행 파일 생성 | `PathologyAIViewer.exe` |
| `build_nuitka.bat` | Nuitka 기반 빌드(옵션) | `dist_nuitka/` |

---

## 라이선스

MIT License
