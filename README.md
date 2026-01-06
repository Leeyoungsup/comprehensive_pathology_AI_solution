# Comprehensive Pathology AI Solution

병리 이미지 뷰어와 AI 분석을 통합한 PyQt6 기반 프로그램

## 기능

### 현재 구현된 기능
- ✅ 병리 이미지 로드 및 표시
- ✅ 마우스 휠을 이용한 줌 인/아웃
- ✅ 마우스 드래그를 이용한 패닝
- ✅ 줌 슬라이더 컨트롤
- ✅ 화면 맞춤 기능
- ✅ AI 분석 패널 UI (템플릿)
- ✅ 이미지 정보 표시

### 예정된 기능
- 🔲 조직 분할 (Tissue Segmentation) AI 모델 통합
- 🔲 암 분류 (Cancer Classification) AI 모델 통합
- 🔲 병변 검출 (Lesion Detection) AI 모델 통합
- 🔲 AI 분석 결과 오버레이 표시
- 🔲 WSI(Whole Slide Image) 파일 지원 (OpenSlide 활용)
- 🔲 분석 결과 저장 및 내보내기

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
