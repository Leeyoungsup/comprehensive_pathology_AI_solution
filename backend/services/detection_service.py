"""
세포 검출 서비스
검출 관련 비즈니스 로직을 담당하는 서비스 레이어
"""

import openslide
from pathlib import Path
from typing import Optional, List, Dict, Any


class DetectionService:
    """세포 검출 관련 비즈니스 로직을 처리하는 서비스"""
    
    def __init__(self):
        self.detection_module = None
        self._model_loaded = False
        
    def _ensure_detection_module(self):
        """검출 모듈 lazy initialization"""
        if self.detection_module is None:
            from ai.detection import CellDetection
            self.detection_module = CellDetection()
        return self.detection_module
    
    def load_model(self, model_path: Optional[str] = None) -> tuple[bool, str]:
        """
        AI 모델 로드
        
        Args:
            model_path: 모델 파일 경로 (None이면 기본 경로)
            
        Returns:
            (성공 여부, 메시지)
        """
        try:
            detection = self._ensure_detection_module()
            
            if detection.load_model(model_path):
                self._model_loaded = True
                return True, "모델 로드 완료"
            else:
                return False, f"모델 로드 실패: {detection.default_model_path}"
                
        except Exception as e:
            return False, f"모델 로드 중 오류: {str(e)}"
    
    def is_model_loaded(self) -> bool:
        """모델 로드 상태 확인"""
        if self.detection_module is None:
            return False
        return self.detection_module.is_model_loaded()
    
    def open_slide(self, slide_path: str) -> tuple[Optional[openslide.OpenSlide], str]:
        """
        WSI 슬라이드 열기
        
        Args:
            slide_path: 슬라이드 파일 경로
            
        Returns:
            (슬라이드 객체, 메시지)
        """
        try:
            slide = openslide.OpenSlide(slide_path)
            return slide, "슬라이드 열기 완료"
        except Exception as e:
            return None, f"슬라이드 열기 실패: {str(e)}"
    
    def start_detection(self, slide: openslide.OpenSlide, roi_polygons: Optional[List] = None):
        """
        검출 시작
        
        Args:
            slide: OpenSlide 객체
            roi_polygons: ROI 폴리곤 리스트 (없으면 전체 영역)
        """
        detection = self._ensure_detection_module()
        
        if not self.is_model_loaded():
            raise RuntimeError("모델이 로드되지 않았습니다.")
        
        detection.run_detection(slide, roi_polygons)
    
    def cancel_detection(self):
        """진행 중인 검출 취소"""
        if self.detection_module is not None:
            self.detection_module.cancel()
    
    def unload_model(self):
        """모델 언로드 및 GPU 리소스 해제"""
        if self.detection_module is not None:
            self.detection_module.unload_model()
            self._model_loaded = False
    
    def get_detection_module(self):
        """검출 모듈 반환 (시그널 연결용)"""
        return self._ensure_detection_module()
    
    def format_detection_result(self, result: Dict[str, Any]) -> str:
        """
        검출 결과를 사용자에게 표시할 문자열로 포맷
        
        Args:
            result: 검출 결과 딕셔너리
            
        Returns:
            포맷된 결과 문자열
        """
        num_cells = result.get('num_cells', 0)
        message = f"세포 검출 완료\n{result.get('message', '')}"
        
        # 클래스별 카운트 표시
        class_counts = result.get('class_counts', {})
        total_from_classes = 0
        
        if class_counts:
            message += "\n\n클래스별 검출 수:"
            for cls_name, count in class_counts.items():
                if count > 0:
                    message += f"\n  {cls_name}: {count:,}"
                    total_from_classes += count
            
            # 합계 표시
            message += f"\n\n클래스별 합계: {total_from_classes:,}"
            message += f"\n전체 세포 수: {num_cells:,}"
            
            if total_from_classes != num_cells:
                message += f"\n⚠️ 카운트 불일치 감지!"
        
        return message
    
    def format_detection_progress(self, status: str) -> str:
        """
        검출 진행 상태를 사용자에게 표시할 문자열로 포맷 (진행바 포함)
        
        Args:
            status: 상태 메시지
            
        Returns:
            포맷된 진행 상태 문자열
        """
        if "패치" in status and "/" in status:
            try:
                parts = status.split("|")
                patch_info = parts[0].strip()
                
                # 진행률 추출
                nums = patch_info.split()[1].split("/")
                current = int(nums[0])
                total = int(nums[1])
                percent = (current / total) * 100
                
                # 텍스트 기반 진행바
                bar_length = 30
                filled = int(bar_length * current / total)
                bar = "█" * filled + "░" * (bar_length - filled)
                
                return f"""세포 검출 진행 중...

[패치 처리]
{bar} {percent:.1f}%

{status}
"""
            except:
                pass
        
        return f"세포 검출 진행 중...\n\n{status}"
