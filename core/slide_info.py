"""
슬라이드 정보 관리 모듈
WSI 파일의 메타데이터 및 속성 정보 추출 및 관리
"""

import os
from pathlib import Path


class SlideInfo:
    """슬라이드 정보 추출 및 관리 클래스"""
    
    def __init__(self, slide):
        """
        Args:
            slide: openslide.OpenSlide 객체
        """
        self.slide = slide
        self.properties = slide.properties if slide else {}
    
    def get_basic_info(self):
        """기본 정보 반환"""
        if not self.slide:
            return None
        
        return {
            'level_count': self.slide.level_count,
            'dimensions': self.slide.level_dimensions[0],
            'level_dimensions': list(self.slide.level_dimensions),
            'level_downsamples': list(self.slide.level_downsamples)
        }
    
    def get_mpp(self):
        """MPP (Microns Per Pixel) 정보 반환"""
        if 'openslide.mpp-x' in self.properties:
            return {
                'mpp_x': float(self.properties['openslide.mpp-x']),
                'mpp_y': float(self.properties['openslide.mpp-y'])
            }
        return {'mpp_x': None, 'mpp_y': None}
    
    def get_objective_power(self):
        """배율 정보 반환"""
        return self.properties.get('openslide.objective-power', 'Unknown')
    
    def get_vendor(self):
        """벤더 정보 반환"""
        return self.properties.get('openslide.vendor', 'Unknown')
    
    def get_physical_size(self):
        """물리적 크기 반환 (mm 단위)"""
        mpp_info = self.get_mpp()
        if mpp_info['mpp_x'] and mpp_info['mpp_y']:
            dimensions = self.get_basic_info()['dimensions']
            width_mm = dimensions[0] * mpp_info['mpp_x'] / 1000
            height_mm = dimensions[1] * mpp_info['mpp_y'] / 1000
            return {'width_mm': width_mm, 'height_mm': height_mm}
        return None
    
    def get_all_properties(self):
        """모든 속성 정보 반환"""
        return dict(self.properties)
    
    def get_complete_info(self, filename=None):
        """완전한 슬라이드 정보 반환"""
        basic_info = self.get_basic_info()
        mpp_info = self.get_mpp()
        
        info = {
            'filename': filename or 'Unknown',
            'level_count': basic_info['level_count'],
            'dimensions': basic_info['dimensions'],
            'level_dimensions': basic_info['level_dimensions'],
            'level_downsamples': basic_info['level_downsamples'],
            'mpp_x': mpp_info['mpp_x'],
            'mpp_y': mpp_info['mpp_y'],
            'objective_power': self.get_objective_power(),
            'vendor': self.get_vendor()
        }
        
        # 물리적 크기 추가
        physical_size = self.get_physical_size()
        if physical_size:
            info['physical_width_mm'] = physical_size['width_mm']
            info['physical_height_mm'] = physical_size['height_mm']
        
        return info
    
    def format_info_text(self, filename=None):
        """정보를 텍스트로 포맷팅"""
        info = self.get_complete_info(filename)
        
        lines = []
        lines.append(f"파일명: {info['filename']}")
        lines.append(f"벤더: {info['vendor']}")
        lines.append(f"배율: {info['objective_power']}x")
        lines.append(f"픽셀 크기 (Level 0): {info['dimensions'][0]} x {info['dimensions'][1]}")
        
        if info['mpp_x'] and info['mpp_y']:
            lines.append(f"MPP: {info['mpp_x']:.4f} x {info['mpp_y']:.4f} µm/pixel")
        
        if 'physical_width_mm' in info:
            lines.append(f"물리적 크기: {info['physical_width_mm']:.2f} x {info['physical_height_mm']:.2f} mm")
        
        lines.append(f"\n총 레벨 수: {info['level_count']}")
        for i, (dim, downsample) in enumerate(zip(info['level_dimensions'], info['level_downsamples'])):
            lines.append(f"  Level {i}: {dim[0]} x {dim[1]} (downsample: {downsample:.2f})")
        
        return '\n'.join(lines)
