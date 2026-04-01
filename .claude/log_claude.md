# Git Commit Log - Comprehensive Pathology AI Solution

> **저장소**: Leeyoungsup/comprehensive_pathology_AI_solution  
> **브랜치**: main  
> **총 커밋 수**: 239개  
> **기간**: 2026-01-06 ~ 2026-03-05  
> **기여자**: Leeyoungsup (261 commits, all branches)

---

## 2026-03-05 (최신)

| Hash | 메시지 |
|------|--------|
| `e4136e2` | fix: ROI 저장 및 로드 기능 개선 및 예외 처리 추가 |
| `bd2ecce` | docs: README.md 내용 업데이트 및 문구 개선 |
| `98bb1e4` | Implement feature X to enhance user experience and fix bug Y in module Z |
| `685a51f` | Remove obsolete AI report PDF file due to irrelevance and outdated content |
| `e99a326` | Implement feature X to enhance user experience and fix bug Y in module Z |

## 2026-03-03 (스플래시 스크린 & 로고 & PyInstaller 개선)

| Hash | 메시지 |
|------|--------|
| `a6a81e7` | fix: 로고 이미지 파일 업데이트 |
| `c26933e` | fix: 로고 이미지 파일 업데이트 |
| `56c9e06` | fix: 애플리케이션 아이콘 설정 로직 개선 및 불필요한 임포트 제거 |
| `f49849c` | feat: 로고 디렉토리 포함 추가 |
| `965686e` | fix: 로고 폴더 복사 로직 추가 |
| `6607d93` | feat: 스플래시 스크린 추가 및 로고 경로 설정 개선 |
| `76a58fc` | Implement feature X to enhance user experience and optimize performance |
| `4ca02d9` | fix: __pycache__ 디렉토리의 detection 및 viewer 파일 업데이트 |
| `972d790` | fix: 전체 카운트 및 TPS 업데이트 로직 개선 및 불필요한 visibility 상태 보존 제거 |
| `c13c5f0` | fix: TiledDetectionOverlay에서 클래스 가시성 유지 로직 개선 |
| `c21eea9` | fix: __pycache__ 디렉토리의 viewer 및 wsi_view_widget 파일 업데이트 |
| `78d910b` | fix: LOD 기준을 3 μm/px로 변경하여 히트맵 사용 조건 수정 |
| `4484bc4` | feat: confidence 슬라이더에 debounce 타이머 추가 및 필터링 최적화 |
| `b596323` | fix: ai/__pycache__/detection.pyc 파일 업데이트 |
| `73fd7e0` | feat: 시각화 패널 레이아웃 조정 및 PDF 생성 로직 개선 |
| `577f4f4` | feat: PyInstaller 실행 옵션을 onedir로 변경 및 Portable 폴더 복사 로직 개선 |
| `dc12e53` | feat: PyInstaller 실행 옵션을 onedir에서 onefile로 변경 |

## 2026-02-27 (Nuitka 빌드 & 병렬 I/O 최적화)

| Hash | 메시지 |
|------|--------|
| `eac5c7b` | fix: AI 폴더를 sys.path에 추가하는 코드 제거 및 상대 경로로 수정 |
| `4cb281a` | feat: Nuitka 크래시 리포트 XML 파일 추가 |
| `2966490` | feat: Nuitka 빌드 감지 추가 및 PyInstaller 실행 파일 구분 로직 개선 |
| `c96fb8d` | feat: Nuitka 빌드 스크립트에서 단계 수 조정 및 conda 환경 확인 추가 |
| `8d393d2` | feat: PyInstaller 실행 옵션을 onefile에서 onedir로 변경 |
| `63803f3` | feat: 빌드 후 의존성 복사 스크립트 추가 |
| `e34aa17` | feat: Nuitka 빌드 스크립트 추가 및 패키지 복사 기능 구현 |
| `e1dc274` | chore: .gitignore 파일에서 __pycache__ 디렉토리 정리 |
| `cc5b1ad` | chore: .gitignore 파일 수정으로 불필요한 캐시 및 디렉토리 추가 |
| `235ab62` | chore: 업데이트된 바이너리 파일로 캐시 정리 |
| `27f3783` | feat: WSITileManager 초기화 시 타일 크기 자동 설정으로 코드 간소화 |
| `de8ddbe` | feat: 병렬 I/O 및 GPU 추론 최적화로 메모리 사용량 감소 |
| `fc59550` | feat: TiledDetectionOverlay에 density 그리드 캐시 추가 및 성능 최적화 |

## 2026-02-26 (성능 최적화 & 메모리 관리)

| Hash | 메시지 |
|------|--------|
| `9461ffd` | Refactor code structure for improved readability and maintainability |
| `03f6711` | feat: seg_prob_map을 인스턴스에 저장하지 않고 메모리 사용 최적화 |
| `d9674fe` | feat: 대형 배열 즉시 해제 추가로 메모리 사용 최적화 |
| `23c1639` | feat: non_max_suppression 및 DetectionWorker 최적화, Epithelial 재분류 로직 개선 |
| `6bf7c22` | feat: __pycache__ 파일 업데이트 |
| `415fc8c` | feat: DBSCAN 클러스터링 최적화 및 Tumor 비율 판정 로직 개선 |
| `680d66f` | feat: 디버그 출력 제거 및 Epithelial 재분류 로직 최적화 |
| `2af2b59` | feat: __pycache__ 파일 업데이트 |
| `300ff43` | feat: 캐시 관리 로그 제거 및 워커 수 조정 |
| `186aa3b` | feat: conda-unpack 경로 재설정 및 환경 변수 설정 개선 |
| `8e331b7` | feat: OpenSlide 경로 설정 시 디버그 출력 제거 |
| `8a2f963` | feat: Python 파일 사전 컴파일 추가 및 실행 배치 파일 생성 개선 |
| `e8419c0` | feat: README.md 업데이트 - 주요 기능 및 빠른 시작 섹션 개선 |
| `6c3c16c` | feat: .gitignore에 HnE_detection_backup.pt 추가 및 __pycache__ 파일 변경 |
| `d8085d3` | feat: effective MPP 계산 추가 및 다운샘플링 로직 개선 |
| `9bf1bca` | feat: 자동저장/자동시각화 체크박스 임시 숨김 및 모델 이름 변경 |
| `3445565` | feat: WSI 로딩 시 MPP 정보 추가 및 타일 레벨 선택 로직 개선 |
| `b42ed31` | feat: 디버그 출력 추가 및 WSI 처리 과정에서의 정보 로그 개선 |
| `439e878` | feat: 디버그 출력 추가 및 MPP 정보 처리 개선 |
| `556f047` | feat: 불필요한 디버그 출력 제거 및 경고 메시지 정리 |
| `3e89fe4` | feat: MPP 및 confidence threshold 로직 개선, 불필요한 디버그 출력 제거 |
| `ba1a669` | feat: DetectionVisualizationDialog에 plot_arrays 매개변수 추가 및 초기화 로직 개선 |
| `a2a7b9c` | feat: 썸네일 재사용 및 시각화 다이얼로그용 사전 계산 배열 저장 로직 개선 |
| `07a97a3` | feat: 시각화 다이얼로그용 plot 배열 사전 계산 및 썸네일 생성 로직 추가 |

## 2026-02-25 (시각화 다이얼로그 & PDF 내보내기)

| Hash | 메시지 |
|------|--------|
| `9ef9f5e` | feat: viewer.pyc 파일 업데이트 |
| `7f1ae50` | feat: 컴파일된 Python 파일 업데이트 |
| `e0194c9` | feat: LOD에 따른 히트맵 마스크 생성 로직 개선 |
| `23d2bb8` | feat: 중복 시그널 연결 방지를 위한 검출 모듈 시그널 연결 로직 개선 |
| `8309e07` | feat: SpatialGrid 및 TiledDetectionOverlay 클래스의 성능 개선을 위한 numpy 최적화 |
| `60a3771` | feat: 저배율 LOD용 히트맵 마스크 생성 기능 추가 |
| `3b7b8fe` | feat: Update compiled Python files in various modules |
| `8e8db3e` | feat: Enhance detection visualization dialog with PDF export functionality and UI improvements |
| `833bff7` | feat: WSIViewWidget의 뷰포트 업데이트 모드를 최소화로 변경 |
| `cc46191` | feat: 결과 시각화 버튼을 UI에 추가 및 위치 변경 |
| `066ee37` | feat: TumorSegmentationWorker 추가 및 UI에서 자동저장 및 자동시각화 체크박스 구현 |
| `a4883ef` | feat: HnE 탭에서 자동 시각화 체크박스 제거 |
| `11271fe` | feat: TileLoader 및 WSITileManager 개선 - 스레드 전용 OpenSlide 오픈 및 태스크 플러시 기능 추가 |
| `8f61b6c` | feat: start_detection 메서드에 image_path 인자 추가 및 문서화 |
| `b3641ca` | feat: WSISegmentationModel.predict_wsi에 상태 콜백 추가 및 유효 패치 사전 필터링 기능 구현 |
| `c087f1e` | feat: 병렬 I/O 및 배치 GPU 추론을 위한 DetectionWorker 개선 |
| `aebe979` | Implement feature X to enhance user experience and fix bug Y in module Z |
| `6427942` | feat: 새로운 AI 보고서 PDF 파일 추가 |

## 2026-02-24 (결과 시각화 기능)

| Hash | 메시지 |
|------|--------|
| `5295b49` | feat: 메인 함수에서 불필요한 로그 출력 코드 주석 처리 |
| `661d8de` | feat: 슬라이드 정보 및 검출 결과 시각화 창을 싱글턴으로 변경하고 썸네일 추가 |
| `baa6b18` | feat: 자동 시각화 체크박스 추가 및 결과 시각화 버튼 텍스트 수정 |
| `1206a8b` | feat: __pycache__ 파일 업데이트 |
| `b093fc1` | feat: 슬라이드 정보 다이얼로그 비모달로 설정 및 표시 방식 변경 |
| `f9a9b38` | feat: DetectionVisualizationDialog 클래스 및 시각화 기능 추가 |
| `9ca5fc3` | feat: DetectionVisualizationDialog 및 관련 함수 추가 |
| `1347a9e` | feat: 결과 시각화 버튼 추가 |
| `e7f5062` | feat: 시각화 버튼 추가 및 HnE 검출 결과 시각화 기능 구현 |
| `6f8a436` | feat: 결과 시각화 버튼 추가 및 텍스트 설정 |
| `3a4782a` | fix: Non-Tumor 세포에 대한 클러스터 판정 조건 추가 |

## 2026-02-19 (confidence threshold 조정)

| Hash | 메시지 |
|------|--------|
| `79e8da9` | chore: __pycache__ 파일 업데이트 |
| `de0b3f8` | fix: 클래스별 confidence threshold 값을 1로 수정하여 슬라이더 범위 조정 |
| `a50aef4` | fix: 클래스 이름 및 색상 수정, confidence threshold 값 조정 |
| `7d082e7` | Implement feature X to enhance user experience and optimize performance |

## 2026-02-12 (클래스별 confidence 슬라이더 & PD-L1 준비)

| Hash | 메시지 |
|------|--------|
| `d1e9823` | chore: __pycache__ 파일 업데이트 및 새로운 경로 파일 추가 |
| `8eba982` | feat: 클래스별 confidence 슬라이더 추가 및 결과 리스트 업데이트 기능 개선 |
| `c256b6d` | fix: 클래스 이름을 Epithelial과 Stromal로 수정하고 Neutrophil과 Eosinophil의 순서를 변경 |
| `3bacbfb` | refactor: 클래스 이름 및 색상 정리, confidence threshold 값 조정 |
| `62a2dba` | fix: non_max_suppression의 confidence_threshold 값을 0.3에서 0.35로 수정 |
| `13579a3` | feat: ER/PR 탭 제목 수정 및 PR 버튼 추가, 불필요한 PR 탭 제거 |

## 2026-02-10 (PD-L1 검출 모듈 & 자동저장 & Epithelial DBSCAN)

| Hash | 메시지 |
|------|--------|
| `c65e80a` | fix: __pycache__ 디렉토리의 바이너리 파일 업데이트 |
| `eeee69c` | feat: set_detection_results에 커스텀 색상맵 인자 추가 |
| `c5e1923` | feat: PD-L1 탭에 조직 타입 선택 그룹 및 라디오 버튼 추가 |
| `80053e2` | feat: PD-L1 검출 모듈 추가 및 UI에 버튼 연결 |
| `1900ee1` | fix: non_max_suppression의 confidence_threshold 및 iou_threshold 값을 수정하고, 원본 크기 기반으로 패치 처리 로직 수정 |
| `145c4e1` | fix: non_max_suppression의 confidence_threshold 값을 0.005에서 0.3으로 수정 |
| `4294305` | feat: PD-L1 탭에 조직 타입 선택 그룹 추가 및 라디오 버튼 설정 |
| `3932cd3` | feat: PD-L1 검출 모듈 추가 및 YOLOv11m 기반 기능 구현 |
| `d29f06a` | feat: PDL1_TPS_detection.pt 모델 파일을 .gitignore에 추가 |
| `226147b` | feat: 커스텀 색상맵 지원 추가 및 관련 클래스 수정 |
| `9924545` | fix: __pycache__ 파일 업데이트 |
| `cec90d3` | feat: 자동저장 기능 추가 및 UI 요소 개선 |
| `1569f8a` | fix: Epithelial 세포 재분류 로직에 DBSCAN 클러스터링 추가 |
| `3ed9d73` | fix: Epithelial 세포 재분류 로직 개선 및 DBSCAN 클러스터링 추가 |

## 2026-02-06 (그리기 모드 안정화 & 메모리 관리)

| Hash | 메시지 |
|------|--------|
| `d0d6020` | fix: __pycache__ 파일 업데이트 |
| `699ebf9` | fix: 그리기 상태 초기화 및 RuntimeError 처리 추가 |
| `1643640` | fix: 그리기 모드 종료 및 ROI 좌표 수집 후 annotation 초기화 추가 |
| `8442e59` | fix: stop_editing 메서드에서 RuntimeError 처리 추가 |
| `2a7b19e` | fix: torch 모듈을 필요할 때만 임포트하도록 수정 및 메모리 관리 개선 |
| `89785d3` | feat: SpatialGrid 클래스 추가 및 타일 마스크 생성 최적화 |

## 2026-02-05 (Segmentation 저장/로드 & 새 탭 추가)

| Hash | 메시지 |
|------|--------|
| `52cf2e2` | 바이너리 파일 업데이트: viewer, wsi_view_widget, __init__, coordinate_utils 캐시 파일 변경 |
| `890e72d` | feat: segmentation_rgba_cache 및 segmentation_roi_polygons 초기화 추가 |
| `f5ee6dc` | feat: Segmentation 결과 저장 및 로드 기능 추가 |
| `56d84a2` | feat: mask_to_polygons 및 polygons_to_mask 함수 추가 |
| `be358e9` | feat: Add new detection tabs for PD-L1, HER2, ER, PR, and Claudin 18.2 in the UI |

## 2026-02-04 (Tumor Segmentation & Epithelial 재분류)

| Hash | 메시지 |
|------|--------|
| `4c80f23` | 바이너리 파일 업데이트: detection, detection_service, annotation_items, viewer, wsi_view_widget 캐시 파일 변경 |
| `9d92653` | Segmentation 오버레이 기능 추가 및 줌 기능 개선 |
| `5dadddb` | 종양 분할 버튼 추가 |
| `aa2a47b` | Tumor Segmentation 기능 추가 및 UI 업데이트 |
| `f866b7e` | HnE 탭에 종양 분할 버튼 추가 및 텍스트 설정 |
| `90bfa39` | AnnotationGraphicsItem 및 DrawingRectangleItem에서 브러시를 투명으로 변경하여 채우기 없음으로 설정 |
| `6b88c49` | WSI 세그멘테이션 모델의 출력 MPP를 8.0에서 4.0으로 변경하고, ROI 영역을 처리할 수 있도록 예측 함수 수정 |
| `39b2396` | NMS 성능 최적화 및 Lymphocyte 검출 임계값 조정, ROI 경계 계산 추가 |
| `54fcbe4` | Add WSI segmentation prediction notebook and update binary files |
| `ed609b2` | AI 분석 UI 업데이트: HnE AI 탭 추가 및 조직 타입 선택 기능 구현 |
| `428239d` | WSIViewWidget: 예외 처리 추가로 삭제된 오버레이 아이템 무시 |
| `de43bff` | EpithelialClassificationService 통합: 조직 타입 선택 기능 추가 및 UI 요소 설정 |
| `b0d1dc4` | AI 분석 UI 업데이트: HnE AI 탭 추가 및 조직 타입 선택 기능 구현 |
| `17746c5` | EpithelialClassificationService 클래스 추가: WSI 분할 및 세포 검출을 통한 상피세포 재분류 기능 구현 |
| `c4723a4` | start_detection 메서드에 자동 상피세포 재분류 및 조직 타입 인자 추가 |
| `f1c9be2` | EpithelialClassificationService 추가: 서비스 레이어에 상피세포 분류 서비스를 포함 |
| `a2c1b13` | Epithelial 세포 재분류 모듈 추가: WSI 분할 결과와 세포 검출을 결합하여 상피세포를 조직 영역별로 재분류하는 기능 구현 |
| `25c20d2` | 클래스 및 색상 설정 업데이트: Epithelial 세포 자동 재분류 기능 추가 및 관련 색상 정의 수정 |
| `0a63adb` | .gitignore에 HnE_BR_segmentation.pt 추가 |
| `6ca2ae0` | requirements.txt에 segmentation-models-pytorch 패키지 추가 |
| `652afde` | 모델 파일 추가: HnE_ST_segmentation.pt를 .gitignore에 추가 |

## 2026-01-16 (오버레이 개선 & 아이콘 설정)

| Hash | 메시지 |
|------|--------|
| `6d8e8dd` | 바이너리 파일 변경: __pycache__ 디렉토리 내의 여러 .pyc 파일 업데이트 |
| `202c8ec` | 결과 리스트 항목의 텍스트 색상을 검은색으로 고정 |
| `3ba95bf` | 벡터 오버레이 관련 코드 제거 및 불필요한 임포트 정리 |
| `3791cd0` | 체크박스 기반의 결과 리스트 가시성 토글 기능 추가 및 UI 개선 |
| `fcc07a6` | TiledDetectionOverlay 클래스에서 전체 오버레이 생성 및 클리어 기능 제거 |
| `a45a522` | 바이너리 파일 변경: __pycache__ 디렉토리 내의 여러 .pyc 파일 업데이트 |
| `9000431` | 주석 중심으로 뷰 이동 기능 추가 및 브러시 관련 코드 제거 |
| `5436d5a` | 주석 선택 시 뷰어에서 해당 주석으로 이동하는 기능 추가 |
| `b1d52cb` | 줌 레벨 기준 수정: 0.3에서 0.2로 변경하여 레벨 선택 기준 조정 |
| `75559aa` | 전체 슬라이드 영역에 대한 오버레이 생성 및 클리어 기능 추가 |
| `d0b7fff` | 애플리케이션 아이콘 설정: 메인 윈도우와 애플리케이션 아이콘 추가 및 예외 처리 구현 |
| `bec25d4` | 그리기 브러시 아이템 클래스 제거: DrawingBrushItem 관련 코드 삭제 |

## 2026-01-15 (Annotation 도구 확장)

| Hash | 메시지 |
|------|--------|
| `5619616` | 바이너리 파일 업데이트: annotation_panel, viewer, wsi_view_widget의 변경 사항 반영 |
| `68afd13` | 그리기 모드에 브러시 추가: 브러시 그리기 기능 구현 및 관련 속성 수정 |
| `aafde7f` | 그리기 도구 종료 액션 추가 및 아이콘 설정 |
| `0f82d38` | 그리기 모드 개선: 지속 그리기 기능 추가 및 그리기 종료 액션 구현 |
| `ab673a1` | 주석 툴바에 그리기 종료 액션 추가 및 아이콘 설정 |
| `9f05fbf` | annotation 추가 기능 개선: 추가 후 해당 행으로 스크롤하고 선택하도록 수정 |
| `bb549ac` | 브러시 아이템 추가: 마우스 이동으로 점 추가 및 다각형 경계 좌표 반환 기능 구현 |
| `66641ff` | 아이콘 추가: 커서 아이콘 파일 추가 |
| `b2c36c1` | 주석 패널 및 WSI 뷰어 기능 개선: 색상 선택 및 이름 변경 기능 추가, 지속 그리기 모드 구현, 툴바 아이콘 추가 |
| `9016148` | 아이콘 추가: Point, Polygon, Rectangular ROI 측정 아이콘 파일 추가 |
| `46aeeed` | .gitignore 파일 수정: 불필요한 주석 제거 및 공백 정리 |
| `14c3720` | 주석 도구 추가: 사각형 및 포인트 그리기 기능 구현, UI 업데이트 및 관련 클래스 추가 |

## 2026-01-14 (빌드/배포 시스템)

| Hash | 메시지 |
|------|--------|
| `0e6e4c9` | README.md 업데이트: 사용자용 빠른 시작 가이드 및 배포 패키지 생성 방법 추가 |
| `b8fb9dc` | run_app.py 파일 추가: Pathology AI Viewer 실행을 위한 콘솔 없는 실행 프로그램 구현 |
| `3911b29` | PathologyAIViewer.spec 파일 추가: Pathology AI Viewer 실행을 위한 분석 및 실행 설정 포함 |
| `6b03c1a` | 로깅 설정 수정: 파일 출력 비활성화 및 로그 레벨을 WARNING으로 변경, 불필요한 로그 출력 주석 처리 |
| `5224c4e` | 런처 스크립트 추가: Pathology AI Viewer 실행을 위한 launcher.py 파일 생성 |
| `af6796a` | 콘솔 없는 실행 파일 생성: run_nogui.vbs 추가 및 실행 파일 안내 메시지 포함 |
| `b5593c2` | build 스크립트 추가: PathologyAIViewer.exe 생성을 위한 launcher.bat 파일 생성 |
| `0c92147` | build 스크립트 추가: PathologyAIViewer.exe 생성 및 아이콘 적용 기능 포함 |
| `f2a4936` | 아이콘 파일 추가: 애플리케이션의 아이콘을 위한 app_icon.ico 파일 생성 |
| `e617a90` | build 스크립트 및 설정 파일 삭제: cx_Freeze 관련 파일 제거 |
| `e6c1026` | cx_Freeze 설정 스크립트 추가: Pathology AI Viewer를 위한 패키지 및 모듈 포함 |
| `bb4bd95` | README.md에 EXE 파일 빌드 및 배포 섹션 추가: PyInstaller 사용법 및 배포 요구사항 설명 |
| `a8c8319` | 메인 애플리케이션 로깅 기능 추가 및 DLL 경로 설정 개선 |
| `57f68c6` | build_portable.ps1 파일 추가: Portable Python 환경 생성 및 배포 패키지 생성 스크립트 포함 |
| `dda7ad5` | build_portable.bat 파일 추가: Portable Python 환경 생성 및 배포 패키지 생성 스크립트 포함 |
| `e88d050` | cx_Freeze 빌드 스크립트 추가: cx_Freeze 설치 확인, 이전 빌드 삭제, 빌드 실행 및 결과 확인 기능 포함 |
| `8651583` | cx_Freeze 빌드 스크립트 추가: cx_Freeze 설치 확인, 이전 빌드 삭제 및 빌드 실행 기능 포함 |
| `46381fe` | .gitignore 업데이트: PathologyAIViewer_Portable 디렉토리 추가 |

## 2026-01-13 (UI 개선 & OpenSlide 설정)

| Hash | 메시지 |
|------|--------|
| `e4e7318` | UI 버튼 이름 변경 및 비활성화 상태 추가: HnE 세포 검출 버튼 이름 수정 및 분류 버튼 비활성화 설정 |
| `6d8520f` | 불필요한 파일 삭제 및 requirements.txt 정리: .spec 파일과 __pycache__ 디렉토리의 바이너리 파일 제거, 패키지 목록 간소화 |
| `042c41a` | OpenSlide DLL 경로 설정 개선: 환경변수 및 PATH 추가 방식 통합 |
| `32f1aee` | .gitignore 및 requirements.txt 업데이트: 빌드 및 실행에 필요한 디렉토리 및 패키지 추가, PathologyAI.spec 파일 생성 |

## 2026-01-12 (핵심 기능 구현: 검출, 서비스 레이어, AI 모듈)

| Hash | 메시지 |
|------|--------|
| `2f0113d` | README.md 업데이트: YOLOv11 기반 세포 검출 기능 및 결과 관리 추가 |
| `407259e` | 바이너리 파일 업데이트: viewer 및 wsi_view_widget의 변경 사항 반영 |
| `9dcb012` | 검출 결과 완전히 제거하는 기능 추가: 오버레이 및 데이터 초기화 메서드 구현 |
| `d0998b4` | UI 개선: HnE 세포 검출 버튼 이름 변경 및 결과 관리 버튼(지우기, 저장, 불러오기) 추가 |
| `71b6543` | UI 개선: HnE 세포 검출 버튼 추가 및 결과 관리 기능(지우기, 저장, 불러오기) 구현 |
| `2243f03` | Refactor code structure for improved readability and maintainability |
| `cb6ece4` | UI 개선: HnE 세포 검출 버튼 추가 및 결과 관리 버튼(지우기, 저장, 불러오기) 추가 |
| `ccd15f8` | AI 모듈 및 슬라이드 서비스 통합: 새로운 서비스 레이어 추가 및 기존 기능 개선, 슬라이드 파일 열기 및 정보 조회 기능 구현 |
| `9d92444` | UI 개선: 검출 결과 오버레이 업데이트를 위한 디바운싱 기능 추가 및 줌 레벨에 따른 다운샘플링 조정 |
| `79206ae` | UI 개선: 진행 상태 표시줄 초기화 및 결과 리스트를 검출 결과로 변경, 주석 도구 모음 추가 |
| `00f7796` | UI 개선: Annotation 툴바 설정 제거 및 결과 리스트 업데이트 기능 추가 |
| `748ea60` | UI 개선: 진행 상태 표시줄 초기화 및 검출 결과 리스트 추가, 주석 도구 모음 구성 |
| `dbf867b` | AI 모듈 서비스 통합: DetectionService를 통한 검출 및 슬라이드 열기 기능 개선 |
| `d6b3e53` | 바이너리 파일 업데이트: detection, viewer, wsi_view_widget 캐시 파일 변경 |
| `5841866` | 서비스 레이어 초기화: DetectionService, SlideService, AnnotationService 추가 및 AI 모듈 연결 |
| `4d5b5bd` | 슬라이드 관리 서비스 추가: 슬라이드 파일 열기, 정보 추출 및 유효성 검사 기능 구현 |
| `e9f080e` | 세포 검출 서비스 추가: 검출 모듈 초기화, 모델 로드 및 슬라이드 열기 기능 구현 |
| `87ad608` | Annotation 관리 서비스 추가: ROI annotation 저장/로드 및 유효성 검사 기능 구현 |
| `ddcb6b5` | 서비스 레이어 초기화: UI와 비즈니스 로직을 분리하는 서비스 클래스들 추가 |
| `a630b72` | 백엔드 패키지 설명 추가: 비즈니스 로직과 서비스 레이어에 대한 주석 작성 |
| `c8878a2` | Add compiled Python files for utility and coordinate transformation modules |
| `b527f73` | ROI 내부 세포 검출 기능 추가: ROI가 지정된 경우 세포가 ROI 내부에 있는지 체크하여 제외 |
| `f9d6f9b` | 검출 결과 오버레이 기능 추가: 세포 검출 결과를 표시하고 업데이트하는 메서드 구현 |
| `6b8f5cd` | AI 모듈 초기화 방식 변경: 지연 로딩으로 수정하여 필요 시에만 모듈을 생성하도록 개선 |
| `e40e1e5` | 유틸리티 모듈 추가: 다양한 기능을 포함한 util.py 파일 생성 |
| `53496cb` | 데이터셋 모듈 추가: 이미지 로딩, 증강 및 레이블 처리를 위한 Dataset 클래스 구현 |
| `753da7e` | 하이퍼파라미터 설정 파일 추가: 학습률, 모멘텀, 손실 가중치 등 포함 |
| `3a4ef5b` | Neural Network 모듈 추가: YOLOv11 아키텍처 구현 및 관련 클래스 정의 |
| `ae9a3c8` | Neural Network 모듈 추가: YOLO 기반 검출 네트워크를 위한 초기화 파일 생성 |
| `9700e34` | 세포 검출 기능 추가: YOLOv11 기반의 병리 이미지에서 세포를 검출하는 로직 구현 및 관련 클래스 리팩토링 |
| `8f4ca52` | 불필요한 openslide 임포트 제거 |

## 2026-01-06 ~ 2026-01-11 (초기 프로젝트 구축 & 리팩토링)

| Hash | 메시지 |
|------|--------|
| `a617da5` | 주석 아이템 및 경로 아이템 수정: QGraphicsPathItem 사용으로 다각형 그리기 로직 개선 |
| `d557529` | 바이너리 파일 변경: minimap 및 wsi_view_widget의 캐시 파일 업데이트 |
| `4fc26eb` | README.md 업데이트: 프로젝트 구조 리팩토링 및 주요 기능 설명 수정 |
| `b2cd591` | 미니맵 클릭 시 뷰 이동 기능 추가: 미니맵 클릭 이벤트와 뷰 이동 로직 연결 |
| `b35cb37` | 미니맵 위젯 클릭 및 드래그 기능 개선: 클릭 및 드래그 시 위치 처리 로직 통합 |
| `b8f9d56` | Add SlideInfoDialog and UI components for displaying slide information |
| `67ecc8e` | 좌표 변환 유틸리티 추가: 다양한 좌표계 간 변환 기능 구현 |
| `3611a8d` | 유틸리티 모듈 추가: 좌표 변환 및 헬퍼 함수 제공 |
| `34277ca` | WSI 뷰어 위젯 추가: 대용량 병리 이미지 표시 및 줌/패닝 기능 구현 |
| `75b37b4` | 병리 이미지 뷰어 리팩토링: WSI 뷰어 및 Annotation 패널 통합, AI 모듈 초기화 기능 추가 |
| `242cfa6` | 병리 이미지 뷰어 리팩토링: UI 구성 및 AI 모듈 초기화 기능 추가 |
| `b2310ab` | 슬라이드 정보 다이얼로그 추가: 슬라이드의 상세 정보를 표시하는 UI 및 관련 기능 구현 |
| `11c2eff` | UI 다이얼로그 모듈 추가: SlideInfoDialog 및 show_slide_info_dialog 임포트 및 __all__ 목록 정의 |
| `db09735` | WSIViewer 및 PathologyViewer 클래스 추가: 대용량 병리 이미지 로드, 표시 및 줌/패닝 기능 구현 |
| `90dfce0` | Annotation 패널 추가: Annotation 목록을 표시하고 관리하는 UI 구성 및 기능 구현 |
| `14890aa` | Annotation 그래픽 아이템 추가: QGraphicsItem을 사용한 Annotation 렌더링 기능 구현 |
| `d7d91d2` | WSIViewer 별칭 업데이트: WSIViewWidget을 사용하여 호환성 유지 및 __all__ 목록 수정 |
| `64fb194` | 슬라이드 정보 관리 모듈 추가: WSI 파일의 메타데이터 및 속성 정보 추출 기능 구현 |
| `b43b914` | 주석 데이터 모델 추가: Annotation 클래스 및 관련 기능 구현 |
| `49ce14a` | 병리 이미지 주석 추가: 다각형 형태의 ROI(관심 영역) 정의 및 속성 설정 |
| `e26fa28` | 조직 분할 모듈 추가: 병리 이미지에서 조직 영역을 분할하는 AI 기능 구현 |
| `4515f40` | 병변 검출 모듈 추가: 병리 이미지에서 병변을 검출하는 AI 기능 구현 |
| `f02b77a` | 암 분류 모듈 추가: 병리 이미지에서 암 조직을 분류하는 기능 구현 |
| `80eefe6` | AI 모듈 초기화: 병리 이미지 분석을 위한 AI 기능 제공 및 모듈 구성 추가 |
| `d0ce2f5` | 코드 리팩토링 완료: viewer.py를 기능별로 분리하여 유지보수성과 확장성 향상 |
| `2301f06` | README.md 업데이트: 프로젝트 구조 및 리팩토링 주요 변경사항 추가 |
| `87fb8ca` | Polygon ROI 그리기 기능 추가: 데이터 모델, 그래픽 아이템, WSI 뷰어 통합 및 UI 컨트롤 구현 |
| `6e83184` | 병리 이미지 뷰어 레이아웃 개선: 수직 스페이서 추가로 UI 공간 조정 |
| `8eb3a05` | 바이너리 파일 업데이트: wsi_tile_manager 및 viewer 모듈의 캐시 파일 변경 |
| `58f798a` | 병리 이미지 뷰어 UI 개선: 클래스 및 위젯 이름 변경, 레이아웃 수정, AI 분석 패널 추가 |
| `e87984e` | 병리 이미지 뷰어 기능 개선: FOV 업데이트 및 타일 관리 최적화, 슬라이드 정보 표시 기능 추가 |
| `15b04f2` | 병리 이미지 뷰어 UI 개선: 레이아웃 수정, AI 분석 패널 추가 및 메뉴 기능 구현 |
| `a4e406b` | 아이콘 추가: Info, Open, ScreenFill, Save 이미지 파일 추가 |
| `758549e` | 타일 로더 및 WSI 타일 매니저 개선: 슬라이드 경계 체크 추가, 타일 크기 조정, 캐시 관리 최적화, 슬라이드 정보 반환 기능 구현 |
| `05105be` | add: pathology viewer |
| `3f4e249` | first commit |
| `ebe78ce` | 병리 이미지 뷰어 기능 구현: 이미지 로드, 표시, 줌/패닝 기능 추가 |
| `f929d8d` | requirements.txt 파일 추가: 병리 이미지 뷰어 및 AI 분석에 필요한 패키지 목록 정의 |
| `1266337` | main.py 파일 추가: 병리 이미지 뷰어 및 AI 분석 프로그램의 메인 진입점 구현 |
| `64b9158` | README.md 파일 추가: 병리 이미지 뷰어 및 AI 분석 기능 설명 |

---

## 개발 타임라인 요약

| 기간 | 주요 마일스톤 |
|------|--------------|
| **2026-01-06 ~ 01-11** | 프로젝트 초기화, WSI 뷰어 구현, 코드 리팩토링 (viewer.py 분리) |
| **2026-01-12** | 핵심 기능 대량 구현 - YOLOv11 세포 검출, 서비스 레이어, AI 모듈 통합 |
| **2026-01-13** | UI 개선, OpenSlide DLL 경로 설정 |
| **2026-01-14** | 빌드/배포 시스템 구축 (PyInstaller, cx_Freeze, Portable) |
| **2026-01-15** | Annotation 도구 확장 (폴리곤, 사각형, 포인트, 브러시) |
| **2026-01-16** | 오버레이 개선, 아이콘, 가시성 토글 |
| **2026-02-04** | Tumor Segmentation & Epithelial 재분류 기능 |
| **2026-02-05** | Segmentation 결과 저장/로드, 새 검출 탭 추가 |
| **2026-02-06** | 안정성 개선 (RuntimeError 처리, 메모리 관리) |
| **2026-02-10** | PD-L1 검출 모듈, 자동저장, DBSCAN 클러스터링 |
| **2026-02-12** | 클래스별 confidence 슬라이더 |
| **2026-02-19** | confidence threshold 조정 |
| **2026-02-24** | 결과 시각화 다이얼로그 (DetectionVisualizationDialog) |
| **2026-02-25** | PDF 내보내기, 히트맵 마스크, 병렬 I/O 최적화 |
| **2026-02-26** | 성능 최적화, 메모리 관리, MPP 로직 개선 |
| **2026-02-27** | Nuitka 빌드, 병렬 I/O & GPU 추론 최적화 |
| **2026-03-03** | 스플래시 스크린, 로고, PyInstaller onedir 배포 |
| **2026-03-05** | ROI 저장/로드 개선, README 업데이트 |
