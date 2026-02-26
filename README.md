# Comprehensive Pathology AI Solution

대용량 병리 이미지(WSI) 뷰어 및 다중 AI 모델 통합 분석 플랫폼

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| **WSI 뷰어** | 타일 기반 LOD 렌더링, 부드러운 줌/패닝 (0.01x ~ 40x) |
| **세포 검출** | H&E 병리 이미지에서 8종 세포 자동 검출 |
| **조직 분할** | 유방/위 조직 영역별 분할 (Stroma / Non-Tumor / Tumor) |
| **Epithelial 재분류** | 세그멘테이션 결과 기반 상피 세포 Tumor/Benign 자동 분류 |
| **PD-L1 검출** | PD-L1 양성/음성 종양 세포 검출 및 TPS 계산 |
| **ROI 어노테이션** | 폴리곤 · 사각형 · 포인트 도구로 분석 영역 지정 |
| **결과 시각화** | 클래스 분포, 공간 히트맵, Confidence 분포, 확률 맵 |
| **결과 관리** | JSON 저장/불러오기, 자동 저장, PDF 내보내기 |

---

## 빠른 시작

### Windows 독립 실행 버전 (사용자)

1. `PathologyAIViewer_Portable.zip` 다운로드
2. 압축 해제
3. `PathologyAIViewer.exe` 실행

> Python 설치 불필요 / 추가 패키지 설치 불필요

---

## 개발 환경 설정

### 요구사항

- **Python**: 3.12
- **CUDA**: 12.x (GPU 사용 시, CPU도 지원)
- **OS**: Windows 10/11 64-bit

### 설치

```cmd
conda create -n pathology python=3.12
conda activate pathology
pip install -r requirements.txt
python main.py
```

### OpenSlide (WSI 지원)

Windows는 `libs/openslide_lib/`에 내장되어 있어 별도 설치 불필요.

```bash
# Linux
sudo apt-get install openslide-tools python3-openslide

# macOS
brew install openslide
```

---

## AI 모델 파일

`model/` 디렉토리에 아래 파일이 있어야 합니다.

| 파일 | 크기 | 기능 |
|------|------|------|
| `HnE_detection.pt` | ~242 MB | 세포 검출 (8종) |
| `HnE_BR_segmentation.pt` | ~119 MB | 유방 조직 분할 |
| `HnE_ST_segmentation.pt` | ~119 MB | 위 조직 분할 |
| `PDL1_TPS_detection.pt` | ~241 MB | PD-L1 종양 검출 |

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

## 프로젝트 구조

```
comprehensive_pathology_AI_solution/
├── main.py                         # 진입점 (OpenSlide DLL 경로 자동 설정)
├── requirements.txt
│
├── ai/                             # AI 추론 모듈
│   ├── detection.py                # 세포 검출 (Worker + Overlay + SpatialGrid)
│   ├── epithelial_classifier.py    # 조직 분할 + Epithelial 재분류
│   ├── pdl1_detection.py           # PD-L1 검출 + TPS 계산
│   ├── classification.py           # 암 분류 (보조)
│   ├── segmentation.py             # 조직 분할 (보조)
│   └── nets/nn.py                  # 검출 네트워크 구조 정의
│
├── backend/services/               # 서비스 레이어 (비즈니스 로직)
│   ├── detection_service.py        # 세포 검출 서비스
│   ├── slide_service.py            # 슬라이드 관리
│   ├── annotation_service.py       # 어노테이션 저장/로드
│   └── epithelial_classification_service.py
│
├── core/                           # 핵심 엔진
│   ├── wsi_tile_manager.py         # 타일 렌더링 (LRU 캐시, LOD 레벨)
│   └── annotation.py              # 어노테이션 데이터 모델
│
├── ui/                             # 사용자 인터페이스
│   ├── viewer.py                   # 메인 윈도우 (버튼 연결, AI 오케스트레이션)
│   ├── wsi_view_widget.py          # WSI 렌더링 위젯
│   ├── minimap.py                  # 미니맵
│   ├── annotation_panel.py         # ROI 목록 패널
│   ├── annotation_items.py         # 그래픽 어노테이션 아이템
│   └── dialogs/
│       └── detection_visualization_dialog.py  # 결과 시각화 다이얼로그
│
├── utils/
│   └── coordinate_utils.py         # 좌표 변환, mask ↔ polygon
│
├── model/                          # AI 모델 파일 (별도 배치 필요)
├── libs/openslide_lib/             # OpenSlide DLL (Windows 내장)
└── assets/, icon/                  # 리소스
```

---

## 사용 방법

### 기본 조작

| 동작 | 방법 |
|------|------|
| 이미지 열기 | 툴바 "이미지 열기" 또는 `Ctrl+O` |
| 줌 인/아웃 | 마우스 휠 또는 버튼 |
| 화면 이동 | 마우스 왼쪽 버튼 드래그 |
| 화면 맞춤 | "화면 맞춤" 버튼 |
| 슬라이드 정보 | "슬라이드 정보" 버튼 (MPP, 레벨 수, 파일 크기 등) |

### ROI 어노테이션

| 도구 | 조작 |
|------|------|
| **폴리곤** | 좌클릭으로 점 추가 → 우클릭 완성 → ESC 취소 |
| **사각형** | 드래그로 그리기 |
| **포인트** | 좌클릭으로 추가 → 우클릭 종료 |
| 어노테이션 저장/로드 | Save ROI / Load ROI 버튼 (JSON) |
| 모두 삭제 | Clear ROI 버튼 |

### AI 분석

#### 1. 세포 검출

```
1. ROI 지정 (선택사항) — 미지정 시 전체 슬라이드 분석
2. 조직 타입 선택: Breast / Stomach / Other
3. "(통합)Cell Detection" 버튼 클릭
4. 완료 후 뷰어에 색상별 세포 오버레이 표시
5. 결과 패널에서 클래스별 세포 수 확인
```

**검출 세포 클래스 (8종)**

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

> 조직 타입이 Breast 또는 Stomach인 경우, 검출 완료 후 세그멘테이션 기반 Epithelial 자동 재분류가 실행됩니다.

#### 2. Tumor Segmentation

```
1. ROI 지정 (선택사항)
2. 조직 타입 선택: Breast / Stomach
3. "Tumor Segmentation" 버튼 클릭
4. 조직 분할 결과가 오버레이로 표시됨 (Stroma / Non-Tumor / Tumor)
```

#### 3. PD-L1 검출

```
1. ROI 지정 (선택사항)
2. "PD-L1 Detection" 버튼 클릭
3. TPS (Tumor Proportion Score) 자동 계산
4. 결과: PD-L1 양성/음성 세포 수 및 TPS% 표시
```

**TPS 해석 기준**

| TPS | 판정 |
|-----|------|
| < 1% | Negative |
| 1 ~ 49% | Low Positive |
| ≥ 50% | High Positive |

#### 4. 결과 시각화

```
"결과 시각화" 버튼 클릭 → 4개 탭 제공
  - 클래스 분포: 막대 그래프
  - Tumor 분석: Tumor/Benign 비율
  - 공간 히트맵: 세포 밀도 또는 조직 확률 맵
  - Confidence 분포: 클래스별 신뢰도 히스토그램
  - PDF 내보내기 지원
```

### 결과 저장/불러오기

| 기능 | 설명 |
|------|------|
| **Save** | JSON 파일로 저장 (메타데이터 + 세포 좌표 전체) |
| **Load** | 저장된 JSON 불러오기 → 오버레이 복원 |
| **Clear** | 현재 검출 결과 제거 |

---

## 결과 JSON 형식

```json
{
  "metadata": {
    "model_type": "detection",
    "model_name": "HnE Cell Detection",
    "timestamp": "2026-01-01T00:00:00",
    "image_path": "slide.svs"
  },
  "result": {
    "num_cells": 12345,
    "class_counts": { "Neutrophil": 100, "Epithelial": 200, ... },
    "cells": [
      { "x": 1024, "y": 2048, "cls_id": 0, "confidence": 0.91 },
      ...
    ]
  }
}
```

---

## 아키텍처

```
viewer.py (UI 이벤트)
    │
    ├── backend/services/     ← 비즈니스 로직 레이어
    │       │
    │       └── ai/           ← AI 추론 (QThread 기반 비동기)
    │
    └── wsi_view_widget.py    ← 렌더링 엔진
            │
            └── core/wsi_tile_manager.py   ← 타일 캐시 + LOD
```

**좌표계**
- WSI Level-0 기준 (픽셀 좌표)
- 세그멘테이션 마스크: `output_mpp = 4.0` 해상도로 저장
- 변환식: `wsi_x = mask_x × (output_mpp / wsi_mpp) + offset_x`

**Effective MPP 기반 LOD**
- `effective_mpp = wsi_mpp / zoom_level`
- 슬라이드 크기와 무관하게 물리적 해상도 기준으로 렌더링 레벨 결정

---

## 배포 빌드 (개발자)

| 스크립트 | 기능 | 출력 |
|----------|------|------|
| `build_portable.bat` | conda-pack 전체 환경 패키징 | `PathologyAIViewer_Portable/` (~5–10 GB) |
| `build_exe.bat` | 런처 실행 파일 생성 | `PathologyAIViewer.exe` |

### 배포 환경 요구사항

| 항목 | 개발(빌드) | 최종 사용자 |
|------|-----------|------------|
| OS | Windows 10/11 64-bit | Windows 10/11 64-bit |
| RAM | 16 GB 이상 권장 | 8 GB 이상 권장 |
| GPU | CUDA 12.x (선택) | — |
| Python | 3.12 | 불필요 |
| 디스크 | 5 GB+ (빌드 작업용) | 배포 패키지만 |

---

## 라이선스

MIT License
