# Comprehensive Pathology AI Solution

대용량 병리 이미지(WSI) 뷰어 및 AI 분석 통합 프로그램

## 프로젝트 구조

```
comprehensive_pathology_AI_solution/
├── main.py                 # 메인 실행 파일
├── requirements.txt        # Python 패키지 의존성
├── README.md              # 프로젝트 문서
│
├── core/                  # 핵심 로직
│   ├── __init__.py
│   └── wsi_tile_manager.py    # WSI 타일 매니저 (ASAP 기반)
│
├── ui/                    # UI 컴포넌트
│   ├── __init__.py
│   ├── viewer.py          # 메인 뷰어 윈도우
│   ├── viewer.ui          # Qt Designer UI 파일
│   ├── viewer_ui.py       # UI 파일에서 생성된 Python 코드
│   └── minimap.py         # 미니맵 위젯
│
├── libs/                  # 외부 라이브러리
│   ├── openslide_lib/     # OpenSlide 라이브러리
│   └── libopenslide-1.dll # OpenSlide DLL
│
└── assets/                # 리소스 파일
    └── (이미지, 아이콘 등)
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
- **프리로딩**: 보이는 영역 ±4 타일 미리 로드

### 3. 미니맵
- **왼쪽 하단 오버레이**: 반투명 배경
- **캐시 상태 시각화**:
  - 레벨 0: 파란색 (고해상도)
  - 레벨 1: 주황색
  - 레벨 2: 초록색
  - 레벨 3+: 노란색
- **현재 FOV 표시**: 빨간 사각형

### 4. AI 분석 패널 (예정)
- 조직 분할 (Segmentation)
- 암 분류 (Classification)
- 병변 검출 (Detection)

## 설치 방법

### 1. 필수 패키지 설치

```bash
pip install -r requirements.txt
```

### 2. OpenSlide 설치 (WSI 파일 지원용)

**Windows:**
1. [OpenSlide Windows binaries](https://openslide.org/download/) 다운로드
2. 다운로드한 파일을 적절한 위치에 압축 해제
3. 시스템 환경 변수 PATH에 OpenSlide bin 폴더 경로 추가

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get install openslide-tools python3-openslide
```

**macOS:**
```bash
brew install openslide
```

## 실행 방법

```bash
python main.py
```

## 프로젝트 구조

```
comprehensive_pathology_AI_solution/
├── main.py              # 메인 진입점
├── viewer.py            # 병리 뷰어 UI 및 로직
├── requirements.txt     # 필요한 패키지 목록
└── README.md           # 프로젝트 문서
```

## 사용 방법

1. **이미지 열기**: 툴바의 "이미지 열기" 버튼 또는 `Ctrl+O`
2. **줌 조작**:
   - 마우스 휠로 줌 인/아웃
   - `Ctrl++` / `Ctrl+-` 단축키
   - 하단 줌 슬라이더 사용
3. **화면 이동**: 마우스 왼쪽 버튼으로 드래그
4. **화면 맞춤**: `Ctrl+0` 또는 툴바의 "화면 맞춤" 버튼
5. **AI 분석**: 오른쪽 패널의 분석 버튼 클릭 (추후 구현 예정)

## 주요 컴포넌트

### ImageViewer 클래스
- 이미지 표시 및 인터랙션 처리
- 줌, 패닝 기능 제공
- OpenCV 기반 이미지 처리

### PathologyViewer 클래스
- 메인 윈도우 UI
- 툴바, 상태바, 패널 관리
- AI 분석 인터페이스

## 향후 개발 계획

1. **AI 모델 통합**
   - PyTorch/TensorFlow 모델 로딩
   - 비동기 추론 처리
   - 결과 시각화 오버레이

2. **WSI 지원**
   - OpenSlide를 통한 대용량 슬라이드 이미지 처리
   - 타일 기반 렌더링
   - 멀티레벨 이미지 지원

3. **성능 최적화**
   - GPU 가속 활용
   - 이미지 캐싱
   - 멀티스레딩 처리

4. **추가 기능**
   - 주석 및 마커 추가
   - 측정 도구
   - 배치 처리 모드

## 라이선스

MIT License

## 기여

이슈나 풀 리퀘스트는 언제든지 환영합니다!
"# comprehensive_pathology_AI_solution" 
