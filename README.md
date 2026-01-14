# Comprehensive Pathology AI Solution

대용량 병리 이미지(WSI) 뷰어 및 YOLOv11 기반 세포 검출 AI 통합 프로그램

## 🚀 빠른 시작 (사용자용)

### Windows 독립 실행 버전

1. **PathologyAIViewer_Portable.zip** 다운로드
2. 압축 해제
3. **PathologyAIViewer.exe** 더블클릭으로 실행

> ✅ Python 설치 불필요  
> ✅ 추가 패키지 설치 불필요  
> ✅ 콘솔 창 없이 깔끔하게 실행

### 대체 실행 방법

- **run.bat**: 콘솔 창과 함께 실행 (디버깅용)
- **run_nogui.vbs**: 콘솔 없이 실행 (VBScript)

---

## 📦 배포 패키지 생성 (개발자용)

### 1. 전체 환경 패키징 (conda-pack)

```cmd
build_portable.bat
```

**생성 결과:**
- `PathologyAIViewer_Portable/` 폴더 (완전 독립 실행)
- 약 10-15분 소요
- Python 환경 전체 포함 (5-10GB)

### 2. 실행 파일 생성 (exe)

```cmd
build_exe.bat
```

**생성 결과:**
- `PathologyAIViewer.exe` (콘솔 없는 런처)
- 자동으로 Portable 폴더에 복사
- 아이콘 적용

---

## 🛠️ 개발 환경 설정

### 필수 요구사항

- **Python**: 3.12 이상
- **CUDA**: 12.8 (GPU 사용 시)
- **OS**: Windows 10/11

### 설치 방법

1. **Conda 환경 생성**
   ```cmd
   conda create -n pathology python=3.12
   conda activate pathology
   ```

2. **의존성 설치**
   ```cmd
   pip install -r requirements.txt
   ```

3. **실행**
   ```cmd
   python main.py
   ```

---

## 📋 프로젝트 구조

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

---

## 🎯 주요 기능

### 1. WSI 타일 기반 렌더링
- **ASAP 구조 기반**: TileManager, TileCache, LOD 시스템
- **멀티 스레드 타일 로딩**: 4개 워커 스레드로 비동기 로딩
- **레벨별 캐시 관리**: LRU 방식으로 메모리 효율적 관리
- **부드러운 줌/패닝**: 0.01x ~ 40x 줌 범위

### 2. ROI 어노테이션
- **폴리곤 그리기**: 좌클릭(점 추가), 우클릭(완성), ESC(취소)
- **어노테이션 관리**: 선택, 삭제, 저장/불러오기 (JSON)
- **Scale-independent 렌더링**: 줌에 관계없이 일정한 선 두께

### 3. AI 세포 검출 (YOLOv11n)
- **6종 세포 검출**: Neutrophil, Epithelial, Lymphocyte, Plasma, Eosinophil, Connective tissue
- **ROI 기반 검출**: 선택한 영역 내 세포만 분석
- **Interactive 결과**: 클래스별 표시/숨김 토글
- **GPU 가속**: CUDA 지원으로 빠른 처리

### 4. 검출 결과 관리
- **저장/불러오기**: JSON 형식으로 메타데이터 포함
- **실시간 진행 상황**: Progress Bar 및 상태 메시지
- **클래스별 통계**: 세포 개수 및 분포 시각화

---

## 📂 주요 파일
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
---

## 🔧 배포 스크립트

| 스크립트 | 설명 | 출력 |
|---------|------|------|
| `build_portable.bat` | conda-pack으로 전체 환경 패키징 | `PathologyAIViewer_Portable/` 폴더 |
| `build_exe.bat` | 실행 파일 생성 및 자동 복사 | `PathologyAIViewer.exe` |
| `run.bat` | 콘솔 창과 함께 실행 | 디버깅용 |
| `run_nogui.vbs` | 콘솔 없이 VBScript로 실행 | 사용자용 |

---

## 🛣️ 향후 계획

1. **조직 분할 (Segmentation)**
   - U-Net 기반 조직 영역 분할
   - 종양/정상 조직 구분

2. **암 분류 (Classification)**
   - ResNet 기반 암 등급 분류
   - 다중 클래스 분류

3. **추가 어노테이션 도구**
   - Rectangle, Ellipse, Freehand
   - Point 어노테이션

4. **분석 결과 고도화**
   - 통계 대시보드
   - 히트맵 시각화
   - CSV/Excel 내보내기

---

## 📄 라이선스

MIT License

---

## 👥 기여

버그 리포트, 기능 제안, Pull Request를 환영합니다!

---

## 📞 문의

프로젝트 관련 문의사항이 있으시면 GitHub Issues를 통해 연락 주세요.

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
