"""
병변 검출 (Lesion Detection) 모듈
병리 이미지에서 세포를 검출하는 AI 기능
YOLOv11 기반 HnE 세포 검출
"""

import os
import json
import shutil
import xml.etree.ElementTree as ET
from xml.dom import minidom
from glob import glob
from pathlib import Path

import numpy as np
import torch
import torchvision
import cv2

from PyQt5.QtCore import QObject, pyqtSignal, QThread

# AI 모델 경로 설정
AI_ROOT = Path(__file__).parent
NETS_PATH = AI_ROOT / "nets"
UTILS_PATH = AI_ROOT / "utils"

import sys
# AI 폴더를 sys.path에 추가 (nets, utils 접근용)
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from nets import nn


# 클래스 설정
CLASS_NAMES = {
    0: "Epithelial",
    1: "Stromal",
    2: "Lymphocyte",
    3: "Plasma",
    4: "Neutrophil",
    5: "Eosinophil"
}

CLASS_COLORS = {
    0: "#00FF00",  # Epithelial - 밝은 녹색
    1: "#808080",  # Stromal - 회색
    2: "#0000FF",  # Lymphocyte - 파란색
    3: "#FFFF00",  # Plasma - 밝은 노란색
    4: "#FF4500",  # Neutrophil - 붉은 주황색
    5: "#8A2BE2"   # Eosinophil - 청보라
}

# RGB 색상 (마스크 생성용)
CLASS_COLORS_RGB = {
    0: (0, 255, 0),      # Epithelial - 밝은 녹색
    1: (128, 128, 128),  # Stromal - 회색
    2: (0, 0, 255),      # Lymphocyte - 파란색
    3: (255, 255, 0),    # Plasma - 밝은 노란색
    4: (255, 69, 0),     # Neutrophil - 붉은 주황색
    5: (138, 43, 226)    # Eosinophil - 청보라
}


def wh2xy(x):
    """Width-Height를 XY 좌표로 변환"""
    y = x.clone() if isinstance(x, torch.Tensor) else np.copy(x)
    y[:, 0] = x[:, 0] - x[:, 2] / 2  # top left x
    y[:, 1] = x[:, 1] - x[:, 3] / 2  # top left y
    y[:, 2] = x[:, 0] + x[:, 2] / 2  # bottom right x
    y[:, 3] = x[:, 1] + x[:, 3] / 2  # bottom right y
    return y


def non_max_suppression(outputs, confidence_threshold=0.1, iou_threshold=0.35, class_thresholds=None):
    """
    빠른 클래스별 NMS - 성능 최적화 버전
    """
    max_wh = 7680


    bs = outputs.shape[0]
    nc = outputs.shape[1] - 4
    
    # 빠른 필터링을 위해 가장 낮은 threshold 사용
    min_conf = confidence_threshold
    if class_thresholds:
        min_conf = min(min(class_thresholds.values()), confidence_threshold)
    
    # 전체 confidence가 낮은 것들 먼저 제거
    xc = outputs[:, 4:4 + nc].amax(1) > min_conf
    
    output = [torch.zeros((0, 6), device=outputs.device)] * bs
    
    for xi, x in enumerate(outputs):
        x = x.transpose(0, -1)[xc[xi]]
        
        if not x.shape[0]:
            continue

        # 박스와 클래스 분리
        box, cls = x.split((4, nc), 1)
        box = wh2xy(box)
        
        # 각 검출의 최고 클래스와 confidence 찾기
        conf, j = cls.max(1, keepdim=True)
        x = torch.cat((box, conf, j.float()), 1)
        
        # 클래스별 threshold 적용
        if class_thresholds:
            keep = torch.zeros(x.shape[0], dtype=torch.bool, device=x.device)
            for i, detection in enumerate(x):
                class_id = int(detection[5].item())
                threshold = class_thresholds.get(class_id, confidence_threshold)
                if detection[4].item() >= threshold:
                    keep[i] = True
            x = x[keep]
        else:
            x = x[x[:, 4] > confidence_threshold]
        
        if not x.shape[0]:
            continue
            
        # confidence로 정렬하고 상위 max_nms개만 유지
        x = x[x[:, 4].argsort(descending=True)]
        
        # 빠른 NMS - PyTorch 내장 함수 사용
        c = x[:, 5:6] * max_wh  # 클래스별 offset
        boxes = x[:, :4] + c
        scores = x[:, 4]
        
        # NMS 적용
        keep = torchvision.ops.nms(boxes, scores, iou_threshold)
        
        output[xi] = x[keep]
    
    return output


class DetectionWorker(QThread):
    """병변 검출 작업을 백그라운드에서 수행하는 워커 스레드"""
    
    finished = pyqtSignal(dict)  # 결과 딕셔너리 전달
    progress = pyqtSignal(int)   # 진행률 (0-100)
    error = pyqtSignal(str)      # 에러 메시지
    status = pyqtSignal(str)     # 상태 메시지
    
    def __init__(self, slide, model, roi_polygons=None, device='cuda', auto_classify_epithelial=True, tissue_type="Stomach"):
        super().__init__()
        self.slide = slide  # pyvips 또는 openslide 이미지
        self.model = model
        self.roi_polygons = roi_polygons  # ROI 폴리곤 리스트
        self.device = device
        self.is_cancelled = False
        self.auto_classify_epithelial = auto_classify_epithelial  # 자동 Epithelial 재분류
        self.tissue_type = tissue_type  # 조직 타입 (Breast, Stomach, Other)

        # 설정
        self.image_size = 1024
        
        # MPP 정보 가져오기 (OpenSlide)
        try:
            mpp_x = slide.properties.get('openslide.mpp-x')
            mpp_y = slide.properties.get('openslide.mpp-y')
            if mpp_x and mpp_y:
                self.origin_mpp = (float(mpp_x) + float(mpp_y)) / 2
                print(f"슬라이드 MPP: {self.origin_mpp:.4f} (x={mpp_x}, y={mpp_y})")
            else:
                self.origin_mpp = 0.25
                print(f"MPP 정보 없음, 기본값 사용: {self.origin_mpp}")
        except:
            self.origin_mpp = 0.25
            print(f"MPP 읽기 실패, 기본값 사용: {self.origin_mpp}")
        
        self.output_mpp = 0.5
        self.original_size = int(self.image_size * self.output_mpp / self.origin_mpp)
        self.magnification = self.original_size / self.image_size
        
        # 클래스별 confidence threshold
        self.class_thresholds = {
            0: 0.1,  # Epithelial
            1: 0.1,  # Stromal
            2: 0.1,  # Lymphocyte - 밀집 영역 검출 향상
            3: 0.1,  # Plasma
            4: 0.1,  # Neutrophil
            5: 0.1   # Eosinophil
        }
    
    def run(self):
        """검출 작업 실행"""
        try:
            import time
            start_total = time.time()
            
            self.status.emit("검출 시작...")
            self.progress.emit(1)
            
            all_cells = []
            
            # 슬라이드 크기 가져오기 (openslide)
            self.status.emit("슬라이드 정보 확인 중...")
            width, height = self.slide.dimensions
            
            self.status.emit(f"슬라이드 크기: {width}x{height}")
            self.progress.emit(3)
            
            # 마스크 생성 (조직 영역만 처리)
            self.status.emit("조직 영역 감지 중... (썸네일 생성)")
            start_mask = time.time()
            thumb_mask = self._create_tissue_mask()
            mask_time = time.time() - start_mask
            self.status.emit(f"조직 마스크 생성 완료 ({mask_time:.2f}s)")
            self.progress.emit(5)
            
            # 총 패치 수 계산
            total_patches = (width // self.image_size) * (height // self.image_size)
            processed_patches = 0
            detected_cells_count = 0
            tissue_patches = 0  # 조직 영역 패치 수
            roi_patches = 0  # ROI 내부 패치 수
            
            import time
            start_time = time.time()
            last_update_time = start_time
            
            self.status.emit(f"세포 검출 중... (총 {total_patches}개 패치)")
            
            # 패치별 처리
            for patch_row in range(width // self.image_size - 1):
                if self.is_cancelled:
                    break
                    
                for patch_col in range(height // self.image_size - 1):
                    if self.is_cancelled:
                        break
                    
                    # 마스크 체크 (조직 영역인지)
                    mask_x = (patch_row * self.image_size) // 64
                    mask_y = (patch_col * self.image_size) // 64
                    mask_region = thumb_mask[mask_y:mask_y + self.image_size // 64,
                                            mask_x:mask_x + self.image_size // 64]
                    
                    if np.sum(mask_region) == 0:
                        processed_patches += 1
                        continue
                    
                    tissue_patches += 1
                    
                    # ROI 체크 (ROI가 지정된 경우)
                    patch_x = patch_row * self.image_size
                    patch_y = patch_col * self.image_size
                    
                    if self.roi_polygons and not self._is_in_roi(patch_x, patch_y):
                        processed_patches += 1
                        continue
                    
                    roi_patches += 1
                    
                    # 패치 추출 및 처리
                    cells = self._process_patch(patch_x, patch_y)
                    all_cells.extend(cells)
                    detected_cells_count = len(all_cells)
                    
                    processed_patches += 1
                    progress = int(5 + (processed_patches / total_patches) * 90)
                    self.progress.emit(progress)
                    
                    # 상태 메시지 업데이트 (매 10개 패치마다 또는 1초마다)
                    current_time = time.time()
                    if processed_patches % 10 == 0 or (current_time - last_update_time) >= 1.0:
                        elapsed = current_time - start_time
                        patches_per_sec = processed_patches / elapsed if elapsed > 0 else 0
                        remaining_patches = total_patches - processed_patches
                        eta = remaining_patches / patches_per_sec if patches_per_sec > 0 else 0
                        
                        status_msg = f"패치 {processed_patches}/{total_patches} | 조직:{tissue_patches} ROI:{roi_patches} | 세포:{detected_cells_count}개 | {patches_per_sec:.1f}it/s | ETA:{eta:.0f}s"
                        self.status.emit(status_msg)
                        last_update_time = current_time
            
            if self.is_cancelled:
                self.error.emit("검출이 취소되었습니다.")
                return

            self.status.emit(f"결과 정리 중... ({detected_cells_count}개 검출)")
            self.progress.emit(50)

            # Epithelial 재분류 (자동 실행)
            if self.auto_classify_epithelial:
                epithelial_count = sum(1 for cell in all_cells if cell.get('cls_id') == 1)
                if epithelial_count > 0:
                    self.status.emit(f"Epithelial 세포 재분류 시작... ({epithelial_count}개)")
                    all_cells = self._run_epithelial_classification(all_cells)
                else:
                    self.status.emit("Epithelial 세포가 없어 재분류를 건너뜁니다.")

            # 결과 정리
            result = {
                'status': 'success',
                'cells': all_cells,
                'num_cells': len(all_cells),
                'class_counts': self._count_by_class(all_cells),
                'message': f'총 {len(all_cells)}개 세포 검출 완료 (재분류 포함)'
            }

            self.progress.emit(100)
            self.finished.emit(result)
            
        except Exception as e:
            import traceback
            self.error.emit(f"병변 검출 중 오류 발생: {str(e)}\n{traceback.format_exc()}")
    
    def _create_tissue_mask(self):
        """조직 영역 마스크 생성 (고속 최적화)"""
        try:
            # 더 큰 다운샘플로 빠르게 처리 (64 -> 128)
            downsample = 128
            
            # openslide get_thumbnail
            thumbnail = self.slide.get_thumbnail((self.slide.dimensions[0] // downsample,
                                                  self.slide.dimensions[1] // downsample))
            thumbnail = np.array(thumbnail)
            
            # 그레이스케일 변환 및 이진화
            if len(thumbnail.shape) == 3:
                gray = cv2.cvtColor(thumbnail[:, :, :3], cv2.COLOR_RGB2GRAY)
            else:
                gray = thumbnail
            
            # 빠른 이진화 (작은 커널)
            mask = cv2.threshold(255 - gray, 30, 255, cv2.THRESH_BINARY)[1]
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            
            # 원래 크기로 리사이즈 (64 downsample 기준)
            target_width = self.slide.dimensions[0] // 64
            target_height = self.slide.dimensions[1] // 64
            mask = cv2.resize(mask, (target_width, target_height), interpolation=cv2.INTER_NEAREST)
            
            return mask
            
        except Exception as e:
            print(f"마스크 생성 실패: {e}")
            # 실패 시 전체 영역 처리
            width, height = self.slide.dimensions
            return np.ones((height // 64, width // 64), dtype=np.uint8) * 255
    
    def _is_in_roi(self, patch_x, patch_y):
        """패치가 ROI 영역과 겹치는지 확인 (교차 판정)"""
        if not self.roi_polygons:
            return True
        
        # 패치의 4개 모서리 좌표
        patch_corners = [
            (patch_x, patch_y),  # 좌상
            (patch_x + self.image_size, patch_y),  # 우상
            (patch_x + self.image_size, patch_y + self.image_size),  # 우하
            (patch_x, patch_y + self.image_size)  # 좌하
        ]
        
        # 패치 중심점도 체크
        patch_center_x = patch_x + self.image_size // 2
        patch_center_y = patch_y + self.image_size // 2
        
        for polygon in self.roi_polygons:
            # 중심점이 안에 있는지 체크
            if polygon.contains_point(patch_center_x, patch_center_y):
                return True
            
            # 4개 모서리 중 하나라도 안에 있는지 체크
            for corner_x, corner_y in patch_corners:
                if polygon.contains_point(corner_x, corner_y):
                    return True
        
        return False

    
    def _process_patch(self, start_x, start_y):
        """단일 패치 처리"""
        cells = []
        
        try:
            # 패치 추출 (openslide)
            patch = self.slide.read_region((start_x, start_y), 0,
                                           (self.image_size, self.image_size))
            patch = np.array(patch)[:, :, :3]
            
            # 리사이즈
            patch = cv2.resize(patch[:, :, :3], (512, 512))
            
            # 텐서 변환
            torch_patch = torch.from_numpy(patch).permute(2, 0, 1).unsqueeze(0).float() / 255.
            torch_patch = torch_patch.to(self.device)
            
            # 추론
            self.model.eval()
            with torch.no_grad():
                with torch.amp.autocast('cuda'):
                    pred = self.model(torch_patch)
                
                results = non_max_suppression(pred, confidence_threshold=0.1,
                                             iou_threshold=0.3,
                                             class_thresholds=self.class_thresholds)
                
                if len(results[0]) > 0:
                    detections = results[0]
                    xyxy = detections[:, :4]
                    confs = detections[:, 4]
                    cls_ids = detections[:, 5]
                    
                    # 중심점 계산
                    centers_x = (xyxy[:, 0] + xyxy[:, 2]) / 2
                    centers_y = (xyxy[:, 1] + xyxy[:, 3]) / 2
                    
                    # 실제 좌표 계산
                    actual_x = start_x + centers_x * 2  # magnification
                    actual_y = start_y + centers_y * 2
                    
                    for i in range(len(detections)):
                        cell_x = actual_x[i].item()
                        cell_y = actual_y[i].item()
                        
                        # ROI가 지정된 경우, 세포가 ROI 내부에 있는지 체크
                        if self.roi_polygons:
                            in_roi = False
                            for polygon in self.roi_polygons:
                                if polygon.contains_point(cell_x, cell_y):
                                    in_roi = True
                                    break
                            if not in_roi:
                                continue  # ROI 밖의 세포는 제외
                        
                        cell_data = {
                            'x': cell_x,
                            'y': cell_y,
                            'cls_id': int(cls_ids[i].item()),
                            'confidence': confs[i].item()
                        }
                        cells.append(cell_data)
        
        except Exception as e:
            print(f"패치 처리 오류 ({start_x}, {start_y}): {e}")
        
        return cells
    
    def _count_by_class(self, cells):
        """클래스별 세포 수 카운트"""
        counts = {name: 0 for name in CLASS_NAMES.values()}
        for cell in cells:
            cls_name = CLASS_NAMES.get(cell['cls_id'], 'Unknown')
            counts[cls_name] = counts.get(cls_name, 0) + 1

        # 디버그: 총합 확인
        total_from_classes = sum(counts.values())
        print(f"세포 카운트 검증: 전체={len(cells)}, 클래스별 합계={total_from_classes}")
        if total_from_classes != len(cells):
            print(f"경고: 카운트 불일치! 차이={len(cells) - total_from_classes}")

        return counts

    def _run_epithelial_classification(self, cells):
        """
        Epithelial 세포 재분류 (WSI Segmentation 기반)

        Args:
            cells: 검출된 세포 리스트

        Returns:
            재분류된 세포 리스트
        """
        print("\n" + "="*50)
        print("Epithelial 재분류 시작")
        print("="*50)

        try:
            from ai.epithelial_classifier import WSISegmentationModel
            if self.tissue_type == "Other":
                print("조직 타입이 'Other'로 설정되어 있어 재분류를 건너뜁니다.")
                self.status.emit("조직 타입이 'Other'로 설정되어 있어 재분류를 건너뜁니다.")
                return cells
            # Segmentation 모델 로딩
            print("Segmentation 모델 로딩 중...")
            self.status.emit("Segmentation 모델 로딩 중...")
            self.progress.emit(52)

            from pathlib import Path
            project_root = Path(__file__).parent.parent
            if self.tissue_type == "Breast":
                model_path = project_root / "model" / "HnE_BR_segmentation.pt"
            elif self.tissue_type == "Stomach":
                model_path = project_root / "model" / "HnE_ST_segmentation.pt"

            print(f"Segmentation 모델 경로: {model_path}")
            print(f"모델 파일 존재: {model_path.exists()}")

            # WSISegmentationModel은 __init__에서 자동으로 모델 로딩
            try:
                seg_model = WSISegmentationModel(
                    model_path=str(model_path),
                    model_mpp=1.0,
                    output_mpp=4.0,
                    device=self.device
                )
                print("Segmentation 모델 로드 성공!")
            except (FileNotFoundError, ImportError) as e:
                print(f"Segmentation 모델 로드 실패: {e}")
                self.status.emit(f"Segmentation 모델 로드 실패, 재분류 건너뜀: {str(e)}")
                return cells

            # ROI bounds 계산 (ROI가 있으면)
            roi_bounds = None
            if self.roi_polygons:
                # 모든 ROI polygon의 bounding box 계산
                min_x = float('inf')
                min_y = float('inf')
                max_x = float('-inf')
                max_y = float('-inf')
                
                for polygon in self.roi_polygons:
                    # Annotation 객체는 coordinates 속성 사용
                    coords = polygon.coordinates
                    xs = [p[0] for p in coords]
                    ys = [p[1] for p in coords]
                    min_x = min(min_x, min(xs))
                    min_y = min(min_y, min(ys))
                    max_x = max(max_x, max(xs))
                    max_y = max(max_y, max(ys))
                
                roi_bounds = (int(min_x), int(min_y), int(max_x), int(max_y))
                print(f"ROI bounds: {roi_bounds}")
            else:
                print("ROI 없음, 전체 WSI Segmentation 실행")

            # WSI Segmentation 실행
            print("WSI Segmentation 실행 중...")
            self.status.emit("WSI Segmentation 실행 중...")

            def progress_callback(progress_pct):
                # Segmentation: 55-90% 범위
                adjusted_progress = 55 + int(progress_pct * 0.35)
                self.progress.emit(adjusted_progress)
                if int(progress_pct) % 10 == 0:
                    self.status.emit(f"Segmentation 진행 중... {int(progress_pct)}%")

            prediction_mask, metadata = seg_model.predict_wsi(
                self.slide,
                patch_size=512,
                overlap_ratio=0.4,
                batch_size=8,
                progress_callback=progress_callback,
                roi_bounds=roi_bounds
            )

            self.status.emit("Epithelial 세포 재분류 중...")
            self.progress.emit(92)

            # MPP 정보 및 ROI offset
            wsi_mpp = self.origin_mpp
            output_mpp = seg_model.output_mpp
            scale_factor = wsi_mpp / output_mpp
            
            # ROI offset 가져오기
            region_offset_x = metadata.get('region_offset', (0, 0))[0]
            region_offset_y = metadata.get('region_offset', (0, 0))[1]

            # Epithelial cells 재분류
            print(f"Scale factor: {scale_factor} (wsi_mpp={wsi_mpp}, output_mpp={output_mpp})")
            print(f"Prediction mask shape: {prediction_mask.shape}")
            print(f"Region offset: ({region_offset_x}, {region_offset_y})")

            epithelial_count = sum(1 for cell in cells if cell.get('cls_id') == 1)
            print(f"Epithelial cells to reclassify: {epithelial_count}")

            # 1단계: Epithelial 세포별 seg_class 수집
            epi_indices = []   # cells 리스트 내 인덱스
            epi_coords = []    # [[x, y], ...]
            epi_seg_classes = []  # 각 세포의 원본 seg_class

            for i, cell in enumerate(cells):
                if cell.get('cls_id') == 1:  # Epithelial
                    cell_x_in_region = cell['x'] - region_offset_x
                    cell_y_in_region = cell['y'] - region_offset_y

                    mask_x = int(cell_x_in_region * scale_factor)
                    mask_y = int(cell_y_in_region * scale_factor)

                    if 0 <= mask_x < prediction_mask.shape[1] and 0 <= mask_y < prediction_mask.shape[0]:
                        seg_class = int(prediction_mask[mask_y, mask_x])
                    else:
                        seg_class = 0  # Out of bounds → Background

                    epi_indices.append(i)
                    epi_coords.append([cell['x'], cell['y']])
                    epi_seg_classes.append(seg_class)

            # 2단계: DBSCAN 클러스터링 (관 단위 그룹핑)
            if len(epi_coords) > 0:
                from sklearn.cluster import DBSCAN
                from collections import Counter

                coords_arr = np.array(epi_coords)
                clustering = DBSCAN(eps=100, min_samples=3).fit(coords_arr)
                labels = clustering.labels_
                n_clusters = len(set(labels) - {-1})
                print(f"DBSCAN 클러스터링: {n_clusters}개 클러스터, {sum(labels == -1)}개 노이즈")

                # 3단계: 클러스터별 Tumor 존재 판정 (10% 이상이면 Tumor 관)
                TUMOR_RATIO_THRESHOLD = 0.1
                for cluster_id in set(labels):
                    if cluster_id == -1:
                        continue  # 노이즈 세포는 개별 판정 유지
                    cluster_mask = (labels == cluster_id)
                    cluster_seg = [epi_seg_classes[j] for j in range(len(labels)) if cluster_mask[j]]
                    tumor_count = sum(1 for s in cluster_seg if s == 3)  # Tumor 픽셀
                    tumor_ratio = tumor_count / len(cluster_seg)
                    # Tumor 비율이 10% 이상이면 관 전체를 Tumor로 판정
                    assign_class = 3 if tumor_ratio >= TUMOR_RATIO_THRESHOLD else 2
                    for j in range(len(labels)):
                        if cluster_mask[j]:
                            epi_seg_classes[j] = assign_class

            # 4단계: 최종 cls_id 할당
            reclassified_count = 0
            class_distribution = {6: 0, 7: 0}

            for k, idx in enumerate(epi_indices):
                if epi_seg_classes[k] == 2:  # Non_Tumor 영역
                    cells[idx]['cls_id'] = 7  # benign epithelial
                    class_distribution[7] += 1
                else:  # Tumor (3), Stroma (1), Background (0)
                    cells[idx]['cls_id'] = 6  # tumor epithelial(Invasive)
                    class_distribution[6] += 1
                reclassified_count += 1

            print(f"재분류 완료: {reclassified_count}개")
            print(f"  - tumor epithelial(Invasive): {class_distribution[6]}")
            print(f"  - benign epithelial: {class_distribution[7]}")
            print("="*50 + "\n")

            self.status.emit(f"Epithelial 재분류 완료 ({reclassified_count}개)")
            self.progress.emit(98)

            # GPU 메모리 정리
            del seg_model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            return cells

        except Exception as e:
            import traceback
            print(f"Epithelial 재분류 실패: {e}\n{traceback.format_exc()}")
            self.status.emit(f"재분류 실패, 원본 결과 사용: {str(e)}")
            return cells

    def cancel(self):
        """작업 취소"""
        self.is_cancelled = True


class CellDetection(QObject):
    """
    세포 검출 클래스
    병리 이미지에서 세포를 검출하는 YOLOv11 기반 AI
    """
    
    detectionComplete = pyqtSignal(dict)
    detectionProgress = pyqtSignal(int)
    detectionStatus = pyqtSignal(str)
    detectionError = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.worker = None
        self.model = None
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        
        # 기본 모델 경로 설정 (프로젝트 루트/model/HnE_detection.pt)
        project_root = Path(__file__).parent.parent
        self.default_model_path = project_root / "model" / "HnE_detection.pt"
        
        print(f"Detection device: {self.device}")
        print(f"Default model path: {self.default_model_path}")
    
    def load_model(self, model_path=None):
        """
        AI 모델 로드
        
        Args:
            model_path: 모델 파일 경로 (None이면 기본 경로 사용)
        
        Returns:
            bool: 로드 성공 여부
        """
        try:
            # YOLO 모델은 원래 6개 클래스로 학습됨
            # 새로운 3개 클래스(Tumor/NT/Stroma-epithelial)는 재분류 단계에서 생성
            num_classes = 6  # 원본 YOLO 모델 클래스 수
            self.model = nn.yolo_v11_m(num_classes).to(self.device)
            
            # 경로가 지정되지 않으면 기본 경로 사용
            if model_path is None:
                model_path = str(self.default_model_path)
            
            if model_path:
                if not os.path.exists(model_path):
                    error_msg = f"모델 파일을 찾을 수 없습니다: {model_path}"
                    print(error_msg)
                    self.detectionError.emit(error_msg)
                    return False
                
                checkpoint = torch.load(model_path, map_location=self.device, weights_only=False)
                self.model.load_state_dict(checkpoint['model_state_dict'])
                print(f"모델 로드 완료: {model_path}")
            else:
                print("경고: 모델 경로가 지정되지 않았습니다")
            
            self.model.eval()
            return True
            
        except Exception as e:
            error_msg = f"모델 로드 실패: {str(e)}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            self.detectionError.emit(error_msg)
            return False
    
    def run_detection(self, slide, roi_polygons=None, auto_classify_epithelial=True, tissue_type="Stomach"):
        """
        세포 검출 실행

        Args:
            slide: pyvips 또는 openslide 이미지 객체
            roi_polygons: ROI Annotation 리스트 (선택사항)
            auto_classify_epithelial: Epithelial 자동 재분류 여부 (기본값: True)
            tissue_type: 조직 타입 (Breast, Stomach, Other)
        """
        if self.model is None:
            self.detectionError.emit("모델이 로드되지 않았습니다.")
            return

        if self.worker and self.worker.isRunning():
            print("이미 검출 작업이 실행 중입니다.")
            return

        # auto_classify_epithelial과 tissue_type 파라미터 전달
        self.worker = DetectionWorker(slide, self.model, roi_polygons, self.device,
                                       auto_classify_epithelial=auto_classify_epithelial,
                                       tissue_type=tissue_type)
        self.worker.finished.connect(self._on_finished)
        self.worker.progress.connect(self._on_progress)
        self.worker.status.connect(self._on_status)
        self.worker.error.connect(self._on_error)
        self.worker.start()
    
    def _on_finished(self, result):
        """검출 완료 시 호출"""
        self.detectionComplete.emit(result)
    
    def _on_progress(self, progress):
        """진행률 업데이트 시 호출"""
        self.detectionProgress.emit(progress)
    
    def _on_status(self, status):
        """상태 메시지 업데이트 시 호출"""
        self.detectionStatus.emit(status)
    
    def _on_error(self, error_msg):
        """에러 발생 시 호출"""
        self.detectionError.emit(error_msg)
    
    def cancel(self):
        """실행 중인 작업 취소"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
    
    def unload_model(self):
        """모델 언로드 및 GPU 리소스 해제"""
        if self.model is not None:
            del self.model
            self.model = None
        
        # GPU 캐시 정리
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        
        import gc
        gc.collect()
        
        print("모델 언로드 및 GPU 리소스 해제 완료")
    
    def is_model_loaded(self):
        """모델이 로드되어 있는지 확인"""
        return self.model is not None


def save_results_to_xml(cells, output_path):
    """
    검출 결과를 ASAP XML 형식으로 저장
    
    Args:
        cells: 검출된 세포 리스트
        output_path: 출력 XML 파일 경로
    """
    root = ET.Element("ASAP_Annotations")
    annotations = ET.SubElement(root, "Annotations")
    
    for i, cell in enumerate(cells):
        cls_id = cell.get('cls_id', 0)
        
        annotation = ET.SubElement(annotations, "Annotation")
        annotation.set("Name", f"Annotation {i}")
        annotation.set("Type", "Dot")
        annotation.set("PartOfGroup", CLASS_NAMES.get(cls_id, f"Class_{cls_id}"))
        annotation.set("Color", CLASS_COLORS.get(cls_id, "#FFFFFF"))
        
        coordinates = ET.SubElement(annotation, "Coordinates")
        coordinate = ET.SubElement(coordinates, "Coordinate")
        coordinate.set("Order", "0")
        coordinate.set("X", str(float(cell['x'])))
        coordinate.set("Y", str(float(cell['y'])))
    
    # AnnotationGroups 생성
    annotation_groups = ET.SubElement(root, "AnnotationGroups")
    for cls_id, class_name in CLASS_NAMES.items():
        group = ET.SubElement(annotation_groups, "Group")
        group.set("Name", class_name)
        group.set("PartOfGroup", "None")
        group.set("Color", CLASS_COLORS.get(cls_id, "#FFFFFF"))
        ET.SubElement(group, "Attributes")
    
    # XML 저장
    rough_string = ET.tostring(root, 'unicode')
    reparsed = minidom.parseString(rough_string)
    pretty_xml = reparsed.toprettyxml(indent="\t")
    
    lines = pretty_xml.split('\n')
    lines[0] = '<?xml version="1.0"?>'
    pretty_xml = '\n'.join(lines[1:])
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(pretty_xml)
    
    print(f"XML 저장 완료: {output_path}")


class DetectionOverlay:
    """
    검출 결과를 마스크 이미지로 생성하여 오버레이하는 클래스
    각 세포를 개별 포인트로 그리는 대신 마스크 이미지를 사용하여 리소스 절약
    """
    
    def __init__(self, image_width, image_height, downsample=64, color_map=None):
        """
        Args:
            image_width: 원본 이미지 너비 (레벨 0)
            image_height: 원본 이미지 높이 (레벨 0)
            downsample: 다운샘플 비율 (기본 64배 축소)
            color_map: 커스텀 색상맵 (None이면 CLASS_COLORS_RGB 사용)
        """
        self.image_width = image_width
        self.image_height = image_height
        self.downsample = downsample
        self.color_map = color_map

        # 마스크 크기 계산
        self.mask_width = image_width // downsample
        self.mask_height = image_height // downsample

        # RGBA 마스크 이미지 (투명 배경)
        self.mask = np.zeros((self.mask_height, self.mask_width, 4), dtype=np.uint8)

        # 클래스별 가시성
        self.class_visibility = {cls_id: True for cls_id in CLASS_NAMES.keys()}
        
        # 점 크기 (마스크 좌표 기준)
        self.point_radius = 10
    
    def clear(self):
        """마스크 초기화"""
        self.mask = np.zeros((self.mask_height, self.mask_width, 4), dtype=np.uint8)
    
    def add_cells(self, cells, alpha=180):
        """
        검출된 세포들을 마스크에 추가
        
        Args:
            cells: 세포 리스트 [{'x': x, 'y': y, 'cls_id': cls_id, 'confidence': conf}, ...]
            alpha: 투명도 (0-255, 기본 180)
        """
        for cell in cells:
            cls_id = cell.get('cls_id', 0)
            
            # 가시성 체크
            if not self.class_visibility.get(cls_id, True):
                continue
            
            # 마스크 좌표로 변환
            mask_x = int(cell['x'] / self.downsample)
            mask_y = int(cell['y'] / self.downsample)
            
            # 범위 체크
            if 0 <= mask_x < self.mask_width and 0 <= mask_y < self.mask_height:
                # 색상 가져오기
                active_colors = self.color_map if self.color_map else CLASS_COLORS_RGB
                color = active_colors.get(cls_id, (255, 255, 255))

                # 원 그리기 (RGBA) - 테두리만 (속이 빈 원)
                cv2.circle(self.mask, (mask_x, mask_y), self.point_radius,
                          (color[0], color[1], color[2], alpha), 3)  # 3 = 선 두께
    
    def set_class_visibility(self, cls_id, visible):
        """특정 클래스의 가시성 설정"""
        self.class_visibility[cls_id] = visible
    
    def set_all_visibility(self, visible):
        """모든 클래스의 가시성 설정"""
        for cls_id in self.class_visibility:
            self.class_visibility[cls_id] = visible
    
    def get_mask_image(self):
        """마스크 이미지 반환 (numpy RGBA)"""
        return self.mask
    
    def get_qpixmap(self):
        """QPixmap으로 변환하여 반환"""
        from PyQt5.QtGui import QImage, QPixmap
        
        # numpy RGBA -> QImage
        height, width, channels = self.mask.shape
        bytes_per_line = channels * width
        
        qimage = QImage(self.mask.data, width, height, bytes_per_line, QImage.Format_RGBA8888)
        return QPixmap.fromImage(qimage)
    
    def get_scaled_qpixmap(self, target_width, target_height):
        """지정된 크기로 스케일된 QPixmap 반환"""
        from PyQt5.QtCore import Qt
        
        pixmap = self.get_qpixmap()
        return pixmap.scaled(target_width, target_height,
                            Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    
    def rebuild_mask(self, cells, alpha=180):
        """마스크를 다시 빌드 (가시성 변경 후 사용)"""
        self.clear()
        self.add_cells(cells, alpha)


class SpatialGrid:
    """
    공간 격자 인덱스 — 셀 좌표를 격자(grid)에 미리 분류하여
    특정 영역의 셀을 O(1)에 조회 (전체 순회 O(N) 제거)
    """

    def __init__(self, grid_size=2048):
        self.grid_size = grid_size
        self.grid = {}  # (gx, gy) -> [cell, ...]

    def build(self, cells):
        """셀 리스트로 격자 인덱스 구축"""
        self.grid.clear()
        gs = self.grid_size
        for cell in cells:
            gx = int(cell['x']) // gs
            gy = int(cell['y']) // gs
            key = (gx, gy)
            if key not in self.grid:
                self.grid[key] = []
            self.grid[key].append(cell)

    def clear(self):
        self.grid.clear()

    def query(self, x_min, y_min, x_max, y_max):
        """영역 내 셀 리스트 반환 (격자 단위로 빠르게 필터링)"""
        gs = self.grid_size
        gx_min = int(x_min) // gs
        gy_min = int(y_min) // gs
        gx_max = int(x_max) // gs
        gy_max = int(y_max) // gs

        result = []
        for gx in range(gx_min, gx_max + 1):
            for gy in range(gy_min, gy_max + 1):
                bucket = self.grid.get((gx, gy))
                if bucket:
                    for cell in bucket:
                        cx, cy = cell['x'], cell['y']
                        if x_min <= cx < x_max and y_min <= cy < y_max:
                            result.append(cell)
        return result


class TiledDetectionOverlay:
    """
    타일 기반 검출 결과 오버레이
    대용량 이미지에서 현재 뷰에 해당하는 영역만 마스크 생성
    SpatialGrid를 이용한 공간 인덱싱으로 대량 셀에서도 빠른 렌더링
    """

    def __init__(self, tile_size=512, color_map=None):
        self.tile_size = tile_size
        self.cells = []
        self.spatial_grid = SpatialGrid(grid_size=2048)
        self.class_visibility = {cls_id: True for cls_id in CLASS_NAMES.keys()}
        self.color_map = color_map  # 커스텀 색상맵 (None이면 CLASS_COLORS_RGB 사용)
        self.point_radius = 16
        self.alpha = 180

    def set_cells(self, cells, color_map=None):
        """검출된 세포 리스트 설정 및 공간 인덱스 구축"""
        self.cells = cells
        self.spatial_grid.build(cells)
        if color_map is not None:
            self.color_map = color_map
            self.class_visibility = {cls_id: True for cls_id in color_map.keys()}

    def clear_cells(self):
        """세포 리스트 초기화"""
        self.cells = []
        self.spatial_grid.clear()

    def set_class_visibility(self, cls_id, visible):
        """특정 클래스의 가시성 설정"""
        self.class_visibility[cls_id] = visible

    def create_tile_mask(self, tile_x, tile_y, tile_width, tile_height, downsample=1):
        """
        특정 타일 영역의 마스크 생성 (SpatialGrid로 영역 내 셀만 빠르게 조회)
        """
        mask_width = tile_width // downsample
        mask_height = tile_height // downsample

        tile_end_x = tile_x + tile_width
        tile_end_y = tile_y + tile_height

        # 공간 인덱스로 뷰 영역 내 셀만 조회
        visible_cells = self.spatial_grid.query(tile_x, tile_y, tile_end_x, tile_end_y)

        if not visible_cells:
            return None

        # 빈 RGBA 마스크
        mask = np.zeros((mask_height, mask_width, 4), dtype=np.uint8)

        adjusted_radius = max(2, int(self.point_radius / downsample))
        line_thickness = max(2, int(5 // downsample))

        cell_count = 0
        for cell in visible_cells:
            cls_id = cell.get('cls_id', 0)
            if not self.class_visibility.get(cls_id, True):
                continue

            cell_x = cell['x']
            cell_y = cell['y']

            mask_x = int((cell_x - tile_x) / downsample)
            mask_y = int((cell_y - tile_y) / downsample)

            if 0 <= mask_x < mask_width and 0 <= mask_y < mask_height:
                active_colors = self.color_map if self.color_map else CLASS_COLORS_RGB
                color = active_colors.get(cls_id, (255, 255, 255))
                cv2.circle(mask, (mask_x, mask_y), adjusted_radius,
                          (color[0], color[1], color[2], self.alpha), line_thickness)
                cell_count += 1

        if cell_count == 0:
            return None

        return mask

    def create_view_mask(self, view_rect, downsample=1):
        """현재 뷰 영역의 마스크 생성"""
        from PyQt5.QtGui import QImage, QPixmap

        x = int(view_rect.x())
        y = int(view_rect.y())
        width = int(view_rect.width())
        height = int(view_rect.height())

        mask = self.create_tile_mask(x, y, width, height, downsample)

        if mask is None:
            return None, x, y

        h, w, c = mask.shape
        bytes_per_line = c * w
        qimage = QImage(mask.data, w, h, bytes_per_line, QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimage)

        return pixmap, x, y

    def get_cells_in_region(self, x, y, width, height):
        """특정 영역 내의 세포 리스트 반환"""
        return self.spatial_grid.query(x, y, x + width, y + height)


# 기존 호환성을 위한 별칭
LesionDetection = CellDetection
