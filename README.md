# Comprehensive Pathology AI Solution

대용량 병리 이미지(WSI) 뷰어 및 AI 분석 통합 프로그램

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
├── ui/                          # UI 컴포넌트
│   ├── __init__.py
│   ├── viewer.py                # 메인 뷰어 윈도우
│   ├── wsi_view_widget.py       # WSI 뷰어 위젯 (렌더링 엔진)
│   ├── minimap.py               # 미니맵 위젯
│   ├── annotation_panel.py      # 어노테이션 목록 패널
│   ├── annotation_items.py      # 어노테이션 그래픽 아이템
│   ├── viewer.ui                # Qt Designer UI 파일
│   └── viewer_ui.py             # UI 파일에서 생성된 Python 코드
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

### 3. 미니맵
- **왼쪽 하단 오버레이**: 반투명 배경
- **현재 FOV 표시**: 빨간 사각형으로 현재 뷰 영역 표시
- **클릭/드래그 이동**: 미니맵에서 클릭하거나 드래그하여 뷰 이동

### 4. ROI 어노테이션 (ASAP 스타일)
- **폴리곤 그리기**: 드래그하여 ROI 영역 설정
  - 마우스 드래그: 점 자동 추가 (뷰 좌표 기준 10px 간격)
  - 시작점 근처 드래그: 자동 완성 (20px 이내)
  - Enter: 폴리곤 완성
  - ESC: 그리기 취소
  - Ctrl+드래그: 그리기 모드에서 패닝
- **어노테이션 선택**: 클릭하여 어노테이션 선택 (하이라이트 표시)
- **어노테이션 삭제**: 
  - Delete 키: 선택된 어노테이션 삭제
  - Delete 버튼: 패널에서 선택 후 삭제
  - Clear 버튼: 모든 어노테이션 삭제
- **어노테이션 저장/불러오기**: JSON 형식으로 저장 및 불러오기
- **Scale-independent 렌더링**: Cosmetic Pen으로 줌에 관계없이 일정한 선 두께

### 5. AI 분석 패널
- **H&E AI**:
  - 조직 분할 (Segmentation)
  - 암 분류 (Classification)
  - 병변 검출 (Detection)
- **IHC AI**: (추후 구현 예정)
- **ROI 기반 분석**: 그려진 폴리곤 영역 내에서만 AI 분석 수행

## 설치 방법

### 1. 필수 패키지 설치

```bash
pip install -r requirements.txt
```

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

## 실행 방법

```bash
python main.py
```

## 사용 방법

### 기본 조작
1. **이미지 열기**: 툴바의 "이미지 열기" 버튼 또는 `Ctrl+O`
2. **줌 조작**:
   - 마우스 휠로 줌 인/아웃
   - 줌 인/아웃 버튼 사용
   - 줌 제한: 0.01x ~ 40x
3. **화면 이동**: 마우스 왼쪽 버튼으로 드래그
4. **화면 맞춤**: "화면 맞춤" 버튼

### ROI 그리기 (ASAP 스타일)
1. **Polygon 버튼 클릭**: 그리기 모드 활성화
2. **드래그**: 마우스를 드래그하여 폴리곤 점 추가
3. **완성**: 
   - 시작점 근처로 드래그하면 자동 완성
   - Enter 키로 완성
4. **취소**: ESC 키
5. **패닝**: Ctrl+드래그로 그리기 모드에서 화면 이동

### 어노테이션 관리
1. **선택**: 뷰어에서 어노테이션 클릭 또는 패널 리스트에서 선택
2. **삭제**: Delete 키 또는 Delete 버튼
3. **모두 삭제**: Clear 버튼
4. **저장**: Save 버튼 (JSON 형식)
5. **불러오기**: Load 버튼

### 미니맵 사용
- **클릭**: 해당 위치로 즉시 이동
- **드래그**: 실시간으로 뷰 이동

## 기술 스택

- **Python 3.8+**
- **PyQt5**: GUI 프레임워크
- **OpenSlide**: WSI 파일 처리
- **NumPy**: 이미지 데이터 처리

## 지원 파일 형식

- **OpenSlide 지원 형식**: .svs, .ndpi, .vms, .vmu, .scn, .mrxs, .tiff, .svslide, .bif

## 향후 개발 계획

1. **AI 모델 통합**
   - PyTorch 모델 로딩
   - 비동기 추론 처리
   - 결과 시각화 오버레이

2. **ROI 기반 AI 분석**
   - 선택된 ROI 영역만 분석
   - 패치 추출 및 배치 처리

3. **추가 어노테이션 도구**
   - Rectangle (사각형)
   - Ellipse (타원)
   - Freehand (자유곡선)
   - Point (점)

4. **성능 최적화**
   - GPU 가속 활용
   - 타일 캐싱 개선

## 라이선스

MIT License

## 기여

이슈나 풀 리퀘스트는 언제든지 환영합니다! 
