"""
SlideManager — 열린 슬라이드 객체 관리 (세션 기반)
OpenSlide 객체를 캐싱하여 매 타일 요청마다 다시 열지 않도록 함
"""

import threading
import time
from pathlib import Path
from typing import Optional, Dict, Tuple

import openslide


class SlideInfo:
    """열린 슬라이드의 메타 정보"""

    def __init__(self, slide: openslide.OpenSlide, file_path: str):
        self.slide = slide
        self.file_path = file_path
        self.opened_at = time.time()
        self.last_accessed = time.time()

        # 메타데이터 캐싱
        self.dimensions = slide.dimensions
        self.level_count = slide.level_count
        self.level_dimensions = list(slide.level_dimensions)
        self.level_downsamples = list(slide.level_downsamples)

        # MPP
        mpp_x = slide.properties.get("openslide.mpp-x")
        mpp_y = slide.properties.get("openslide.mpp-y")
        if mpp_x and mpp_y:
            self.mpp_x = float(mpp_x)
            self.mpp_y = float(mpp_y)
            self.mpp = (self.mpp_x + self.mpp_y) / 2
        else:
            self.mpp_x = 0.25
            self.mpp_y = 0.25
            self.mpp = 0.25  # 기본값 (40x)

        # 추가 메타데이터
        self.vendor = slide.properties.get("openslide.vendor", "Unknown")
        self.objective_power = slide.properties.get("openslide.objective-power", "Unknown")

        # 물리적 크기 (mm)
        w, h = self.dimensions
        self.physical_width_mm = w * self.mpp_x / 1000.0
        self.physical_height_mm = h * self.mpp_y / 1000.0

        # 4단계 레벨 매핑
        self.level_stages = self._setup_level_stages()

    def _setup_level_stages(self):
        """기존 WSITileManager._setup_level_stages와 동일 로직"""
        total = self.level_count
        if total == 1:
            return [0, 0, 0, 0]
        elif total == 2:
            return [0, 0, 1, 1]
        elif total == 3:
            return [0, 1, 2, 2]
        else:
            step = (total - 1) / 3.0
            return [
                0,
                int(round(step)),
                int(round(step * 2)),
                min(total - 1, int(round(step * 3))),
            ]

    def get_stage_level(self, effective_mpp: float) -> int:
        """effective MPP 기반 4단계 레벨 선택"""
        if effective_mpp < 2.0:
            return self.level_stages[0]
        elif effective_mpp < 15.0:
            return self.level_stages[1]
        elif effective_mpp < 100.0:
            return self.level_stages[2]
        else:
            return self.level_stages[3]

    def touch(self):
        self.last_accessed = time.time()


class SlideManager:
    """열린 슬라이드 관리자 (thread-safe)"""

    def __init__(self):
        self._slides: Dict[str, SlideInfo] = {}
        self._lock = threading.Lock()

    def open(self, slide_id: str, file_path: str) -> SlideInfo:
        """슬라이드 열기 (이미 열려있으면 캐시 반환)"""
        with self._lock:
            if slide_id in self._slides:
                info = self._slides[slide_id]
                info.touch()
                return info

            slide = openslide.OpenSlide(file_path)
            info = SlideInfo(slide, file_path)
            self._slides[slide_id] = info
            return info

    def get(self, slide_id: str) -> Optional[SlideInfo]:
        """열린 슬라이드 가져오기"""
        with self._lock:
            info = self._slides.get(slide_id)
            if info:
                info.touch()
            return info

    def close(self, slide_id: str):
        """슬라이드 닫기"""
        with self._lock:
            info = self._slides.pop(slide_id, None)
            if info:
                try:
                    info.slide.close()
                except Exception:
                    pass

    def close_all(self):
        """모든 슬라이드 닫기"""
        with self._lock:
            for info in self._slides.values():
                try:
                    info.slide.close()
                except Exception:
                    pass
            self._slides.clear()

    def list_slides(self):
        """열린 슬라이드 목록"""
        with self._lock:
            return {
                sid: {
                    "file_path": info.file_path,
                    "dimensions": info.dimensions,
                    "level_count": info.level_count,
                    "mpp": info.mpp,
                }
                for sid, info in self._slides.items()
            }


# 싱글톤
slide_manager = SlideManager()
