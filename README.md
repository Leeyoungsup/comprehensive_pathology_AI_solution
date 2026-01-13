# Comprehensive Pathology AI Solution

대용량 병리 이미지(WSI) 뷰어 및 YOLOv11 기반 세포 검출 AI 통합 프로그램

## 프로젝트 구조

```
comprehensive_pathology_AI_solution/
├── main.py                      # 메인 실행 파일
├── requirements.txt             # Python 패키지 의존성
├── README.md                    # 프로젝트 문서
│
├── core/                        # 핵심 로직
│   ├── __init__.py
│   ├── wsi_tile_manager.py      # WSI 타일 매니저 (ASAP 기반)
│   └── annotation.py            # 어노테이션 데이터 모델
│
├── backend/                     # 서비스 레이어 (비즈니스 로직)
│   └── services/
│       ├── __init__.py
│       ├── detection_service.py  # 검출 서비스
│       ├── slide_service.py      # 슬라이드 관리 서비스
│       └── annotation_service.py # 어노테이션 저장/로드 서비스
│
├── ai/                          # AI 모듈
│   ├── __init__.py
│   ├── detection.py             # YOLOv11 세포 검출 (Worker + Overlay)
│   ├── segmentation.py          # 조직 분할 (예정)
│   └── classification.py        # 암 분류 (예정)
│
├── ui/                          # UI 컴포넌트
│   ├── __init__.py
│   ├── viewer.py                # 메인 뷰어 윈도우 (이벤트 처리만)
│   ├── wsi_view_widget.py       # WSI 뷰어 위젯 (렌더링 엔진)
│   ├── minimap.py               # 미니맵 위젯
│   ├── annotation_panel.py      # 어노테이션 목록 패널
│   ├── annotation_items.py      # 어노테이션 그래픽 아이템
│   ├── dialogs.py               # 다이얼로그 컴포넌트
│   └── viewer.ui                # Qt Designer UI 파일
│
├── libs/                        # 외부 라이브러리
│   └── openslide_lib/           # OpenSlide 라이브러리
│
├── assets/                      # 리소스 파일
└── icon/                        # 아이콘 파일
```

## 주요 기능

### 1. WSI 타일 기반 렌더링
- **ASAP 구조 기반**: TileManager, TileCache, LOD 시스템
- **멀티 스레드 타일 로딩**: 4개 워커 스레드로 비동기 로딩
- **레벨별 캐시 관리**: 
  - 레벨 0 (고해상도): 500 타일 (~500MB)
  - 레벨 1: 800 타일
  - 레벨 2: 1200 타일
  - 레벨 3+: 2000 타일
- **LRU Eviction**: 메모리 효율적 관리

### 2. 뷰어 기능
- **부드러운 줌/패닝**: QGraphicsView 기반
- **4단계 레벨 시스템**: 자동 해상도 전환
- **줌 제한**: 최소 0.01x ~ 최대 40x
- **프리로딩**: 보이는 영역 ±4 타일 미리 로드
- **성능 최적화**: 
  - 줌 시 100ms 디바운싱으로 렉 방지
  - 저배율(<0.05x) 시 16배 다운샘플링으로 부드러운 렌더링

### 3. 미니맵
- **왼쪽 하단 오버레이**: 반투명 배경
- **현재 FOV 표시**: 빨간 사각형으로 현재 뷰 영역 표시
- **클릭/드래그 이동**: 미니맵에서 클릭하거나 드래그하여 뷰 이동

### 4. ROI 어노테이션 (ASAP 스타일)
- **폴리곤 그리기**: 
  - 좌클릭: 점 추가
  - 우클릭: 폴리곤 완성
  - ESC: 그리기 취소
  - Ctrl+드래그: 그리기 모드에서 패닝
- **어노테이션 선택**: 클릭하여 어노테이션 선택 (하이라이트 표시)
- **어노테이션 삭제**: 
  - Delete 키: 선택된 어노테이션 삭제
  - Delete 버튼: 패널에서 선택 후 삭제
  - Clear ROI 버튼: 모든 어노테이션 삭제
- **어노테이션 저장/불러오기**: JSON 형식으로 저장 및 불러오기
- **Scale-independent 렌더링**: Cosmetic Pen으로 줌에 관계없이 일정한 선 두께

### 5. AI 세포 검출 (YOLOv11n)
- **YOLOv11 기반 6종 세포 검출**:
  - Neutrophil (호중구) - 빨강
  - Epithelial (상피세포) - 주황
  - Lymphocyte (림프구) - 노랑
  - Plasma (형질세포) - 초록
  - Eosinophil (호산구) - 청록
  - Connective tissue (결합조직) - 파랑
  
- **ROI 기반 검출**: 
  - ROI 폴리곤 내부의 세포만 검출
  - ROI 없으면 전체 슬라이드 분석
  
- **실시간 진행 상황 표시**:
  - Progress Bar: 0~100% 진행률
  - Progress Label: 현재 작업 상태 메시지
  - 상태바: 세부 정보 표시
  
- **Interactive 결과 표시**:
  - 클래스별 세포 개수 표시 (색상 구분)
  - 클릭으로 클래스별 표시/숨김 토글 (✓/✗)
  - "전체" 클릭으로 모든 클래스 일괄 토글
  
- **타일 기반 병렬 처리**:
  - 512x512 패치 단위 처리
  - ROI 경계 필터링으로 정확한 영역 검출
  - GPU 메모리 효율적 관리

### 6. 검출 결과 관리
- **Clear**: 현재 검출 결과 삭제
- **Save**: JSON 형식으로 저장
  - 메타데이터 포함 (모델명, 버전, 시간, 원본 이미지 정보)
  - 자동 파일명 제안 (WSI파일명_detection_result.json)
- **Load**: 저장된 결과 불러오기
  - 메타데이터 기반 모델 타입 자동 인식
  - 레거시 형식 호환
  - 세포 오버레이 자동 복원

**JSON 저장 형식**:
```json
{
  "metadata": {
    "model_type": "detection",
    "model_name": "YOLOv11n",
    "version": "1.0",
    "timestamp": "2026-01-12T14:30:45.123456",
    "image_path": "C:/path/to/slide.svs",
    "image_name": "slide.svs"
  },
  "result": {
    "num_cells": 1234,
    "class_counts": {
      "Neutrophil": 100,
      "Lymphocyte": 200,
      ...
    },
    "cells": [
      {
        "x": 1000,
        "y": 2000,
        "cls_id": 0,
        "conf": 0.95
      },
      ...
    ]
  }
}
```

### 7. 아키텍처
- **Clean Architecture**: UI - Service - AI 3계층 분리
  - **UI Layer** (viewer.py): 사용자 입력 및 이벤트 처리만
  - **Service Layer** (backend/services): 비즈니스 로직 및 데이터 관리
  - **AI Layer** (ai/): 알고리즘 및 모델 추론
- **Qt Designer 기반 UI**: .ui 파일로 UI 정의, 코드와 분리
- **비동기 워커**: QThread 기반 AI 작업, UI 블로킹 없음

## 설치 방법

### 1. 필수 패키지 설치

```bash
pip install -r requirements.txt
```

**주요 패키지:**
- PyQt5: GUI 프레임워크
- openslide-python: WSI 파일 처리
- numpy: 이미지 데이터 처리
- torch: PyTorch (AI 모델 추론)
- ultralytics: YOLOv11 모델

### 2. OpenSlide 설치 (WSI 파일 지원용)

**Windows:**
- 프로젝트의 `libs/openslide_lib/` 폴더에 이미 포함되어 있음

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get install openslide-tools python3-openslide
```

**macOS:**
```bash
brew install openslide
```

### 3. YOLOv11 모델 준비
- 모델 파일 경로: `ai/best.pt`
- 6종 세포 검출 학습 완료 모델
- 자동 로딩 (첫 실행 시 초기화)

## 실행 방법

```bash
python main.py
```

## 기술 스택

- **Python 3.8+**
- **PyQt5**: GUI 프레임워크
- **OpenSlide**: WSI 파일 처리
- **NumPy**: 이미지 데이터 처리
- **PyTorch**: AI 모델 추론
- **Ultralytics YOLOv11**: 세포 검출 모델

## 지원 파일 형식

- **OpenSlide 지원 형식**: .svs, .ndpi, .vms, .vmu, .scn, .mrxs, .tiff, .svslide, .bif

## 사용 방법

### 기본 조작
1. **이미지 열기**: 툴바의 "이미지 열기" 버튼 또는 `Ctrl+O`
2. **줌 조작**:
   - 마우스 휠로 줌 인/아웃
   - 줌 인/아웃 버튼 사용
   - 줌 제한: 0.01x ~ 40x
3. **화면 이동**: 마우스 왼쪽 버튼으로 드래그
4. **화면 맞춤**: "화면 맞춤" 버튼

### ROI 그리기
1. **Polygon 버튼 클릭**: 그리기 모드 활성화
2. **좌클릭**: 폴리곤 점 추가
3. **우클릭**: 폴리곤 완성
4. **ESC**: 그리기 취소
5. **Ctrl+드래그**: 그리기 모드에서 화면 이동

### 어노테이션 관리
1. **선택**: 뷰어에서 어노테이션 클릭 또는 패널 리스트에서 선택
2. **삭제**: Delete 키 또는 Delete 버튼
3. **모두 삭제**: Clear ROI 버튼
4. **저장**: Save ROI 버튼 (JSON 형식)
5. **불러오기**: Load ROI 버튼

### 세포 검출 (Cell Detection)
1. **ROI 그리기** (선택사항): 분석할 영역 지정
2. **(통합)Cell Detection 버튼 클릭**: AI 검출 시작
3. **진행 상황 확인**: Progress Bar와 Label에서 실시간 확인
4. **결과 확인**: 
   - 검출 결과 패널에 클래스별 세포 수 표시
   - 뷰어에 색상별 세포 오버레이 표시
5. **클래스 토글**: 
   - 개별 클래스 클릭: 해당 클래스만 표시/숨김
   - "전체" 클릭: 모든 클래스 일괄 표시/숨김

### 결과 관리
- **Clear**: 현재 검출 결과 삭제
- **Save**: 결과를 JSON 파일로 저장 (메타데이터 포함)
- **Load**: 저장된 결과 불러오기 (세포 오버레이 복원)

### 미니맵 사용
- **클릭**: 해당 위치로 즉시 이동
- **드래그**: 실시간으로 뷰 이동

## 향후 개발 계획

1. **추가 AI 모델 통합**
   - Segmentation (조직 분할)
   - Classification (암 분류)
   - 범용 JSON 포맷으로 모든 AI 결과 통합 관리

2. **성능 최적화**
   - GPU 가속 최적화
   - 타일 캐싱 개선
   - 대용량 슬라이드 처리 속도 향상

3. **추가 어노테이션 도구**
   - Rectangle (사각형)
   - Ellipse (타원)
   - Freehand (자유곡선)
   - Point (점)

4. **분석 결과 고도화**
   - 통계 대시보드
   - 히트맵 시각화
   - CSV/Excel 내보내기
   - 보고서 자동 생성

5. **배치 처리**
   - 다중 슬라이드 일괄 분석
   - 작업 큐 관리
   - 백그라운드 처리

## 주요 특징

- ✅ **Clean Architecture**: UI-Service-AI 3계층 분리로 유지보수성 향상
- ✅ **성능 최적화**: 디바운싱과 다운샘플링으로 부드러운 줌 경험
- ✅ **ROI 기반 분석**: 관심 영역만 선택적으로 분석하여 시간 절약
- ✅ **Interactive 결과**: 클릭으로 클래스별 표시 제어
- ✅ **범용 저장 형식**: 메타데이터 포함 JSON으로 모든 AI 결과 관리
- ✅ **실시간 피드백**: Progress Bar와 상태 메시지로 작업 진행 상황 확인

## 🚀 EXE 파일 빌드 및 배포

이 프로젝트는 PyInstaller를 사용하여 독립 실행형 Windows 실행 파일로 빌드할 수 있습니다.

### 빠른 빌드 (3단계)

1. **환경 확인**
   ```bash
   python check_environment.py
   ```

2. **빌드 실행**
   ```powershell
   # PowerShell
   .\build.ps1
   
   # 또는 CMD
   build.bat
   ```

3. **결과 확인**
   - `dist/PathologyAIViewer/PathologyAIViewer.exe` 실행
   - 폴더 전체를 압축하여 배포

### 📚 상세 문서

- **[빠른 시작 가이드](QUICK_START.md)**: 3단계로 빌드하기
- **[배포 가이드](DEPLOYMENT_GUIDE.md)**: 상세한 빌드 및 배포 설명서

### 배포 요구사항

**개발 환경** (빌드 시):
- Python 3.8+
- 모든 requirements.txt 패키지
- 디스크 여유 공간 5GB+

**최종 사용자** (실행 시):
- Windows 10/11 (64-bit)
- 8GB RAM 이상 권장
- Visual C++ Redistributable (자동 확인)

### 주요 특징
- ✅ PyTorch 포함 (GPU/CPU 자동 감지)
- ✅ OpenSlide 라이브러리 내장
- ✅ AI 모델 자동 패키징
- ✅ 독립 실행 (Python 설치 불필요)
- ✅ 2-4GB 단일 배포 패키지

---

## 라이선스

MIT License

## 기여

이슈나 풀 리퀘스트는 언제든지 환영합니다! 
