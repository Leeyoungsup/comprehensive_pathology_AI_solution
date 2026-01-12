"""
슬라이드 관리 서비스
슬라이드 파일 열기, 정보 조회 등의 비즈니스 로직
"""

import openslide
from pathlib import Path
from typing import Optional, Dict, Any, Tuple


class SlideService:
    """슬라이드 관리 관련 비즈니스 로직을 처리하는 서비스"""
    
    @staticmethod
    def open_slide(file_path: str) -> Tuple[Optional[openslide.OpenSlide], str]:
        """
        슬라이드 파일 열기
        
        Args:
            file_path: 슬라이드 파일 경로
            
        Returns:
            (슬라이드 객체 또는 None, 메시지)
        """
        try:
            slide = openslide.OpenSlide(file_path)
            file_name = Path(file_path).name
            return slide, f"슬라이드 로드 완료: {file_name}"
        except Exception as e:
            return None, f"슬라이드 로드 실패: {str(e)}"
    
    @staticmethod
    def get_slide_info(slide: openslide.OpenSlide) -> Dict[str, Any]:
        """
        슬라이드 정보 추출
        
        Args:
            slide: OpenSlide 객체
            
        Returns:
            슬라이드 정보 딕셔너리
        """
        info = {
            'dimensions': slide.dimensions,
            'level_count': slide.level_count,
            'level_dimensions': slide.level_dimensions,
            'level_downsamples': slide.level_downsamples,
            'properties': dict(slide.properties),
        }
        
        # MPP 정보 추출
        mpp_x = slide.properties.get('openslide.mpp-x')
        mpp_y = slide.properties.get('openslide.mpp-y')
        if mpp_x and mpp_y:
            info['mpp'] = (float(mpp_x) + float(mpp_y)) / 2
        
        return info
    
    @staticmethod
    def validate_file_path(file_path: str) -> Tuple[bool, str]:
        """
        파일 경로 유효성 검사
        
        Args:
            file_path: 검사할 파일 경로
            
        Returns:
            (유효 여부, 메시지)
        """
        if not file_path:
            return False, "파일 경로가 지정되지 않았습니다."
        
        path = Path(file_path)
        
        if not path.exists():
            return False, f"파일이 존재하지 않습니다: {file_path}"
        
        if not path.is_file():
            return False, f"디렉토리입니다: {file_path}"
        
        # 지원되는 확장자 체크
        supported_extensions = {'.svs', '.tif', '.tiff', '.ndpi', '.mrxs', '.vms', '.vmu', '.scn'}
        if path.suffix.lower() not in supported_extensions:
            return False, f"지원되지 않는 파일 형식: {path.suffix}"
        
        return True, "유효한 파일 경로"
    
    @staticmethod
    def format_slide_info(info: Dict[str, Any]) -> str:
        """
        슬라이드 정보를 사용자에게 표시할 문자열로 포맷
        
        Args:
            info: 슬라이드 정보 딕셔너리
            
        Returns:
            포맷된 정보 문자열
        """
        width, height = info['dimensions']
        level_count = info['level_count']
        
        text = f"""슬라이드 정보
        
크기: {width:,} x {height:,} pixels
레벨 수: {level_count}
"""
        
        if 'mpp' in info:
            text += f"MPP: {info['mpp']:.4f} µm/pixel\n"
        
        text += "\n레벨별 정보:\n"
        for i, (dims, downsample) in enumerate(zip(info['level_dimensions'], info['level_downsamples'])):
            text += f"  Level {i}: {dims[0]:,} x {dims[1]:,} (downsample: {downsample:.2f}x)\n"
        
        return text
