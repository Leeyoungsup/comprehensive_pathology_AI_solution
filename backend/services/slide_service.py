"""
Slide management service
Business logic for opening slide files, querying information, etc.
"""

import openslide
from pathlib import Path
from typing import Optional, Dict, Any, Tuple


class SlideService:
    """Service handling slide management business logic"""

    @staticmethod
    def open_slide(file_path: str) -> Tuple[Optional[openslide.OpenSlide], str]:
        """
        Open slide file

        Args:
            file_path: Slide file path

        Returns:
            (slide object or None, message)
        """
        try:
            slide = openslide.OpenSlide(file_path)
            file_name = Path(file_path).name
            return slide, f"Slide loaded successfully: {file_name}"
        except Exception as e:
            return None, f"Failed to load slide: {str(e)}"

    @staticmethod
    def get_slide_info(slide: openslide.OpenSlide) -> Dict[str, Any]:
        """
        Extract slide information

        Args:
            slide: OpenSlide object

        Returns:
            Slide information dictionary
        """
        info = {
            'dimensions': slide.dimensions,
            'level_count': slide.level_count,
            'level_dimensions': slide.level_dimensions,
            'level_downsamples': slide.level_downsamples,
            'properties': dict(slide.properties),
        }

        # Extract MPP information
        mpp_x = slide.properties.get('openslide.mpp-x')
        mpp_y = slide.properties.get('openslide.mpp-y')
        if mpp_x and mpp_y:
            info['mpp'] = (float(mpp_x) + float(mpp_y)) / 2

        return info

    @staticmethod
    def validate_file_path(file_path: str) -> Tuple[bool, str]:
        """
        Validate file path

        Args:
            file_path: File path to validate

        Returns:
            (is_valid, message)
        """
        if not file_path:
            return False, "No file path specified."

        path = Path(file_path)

        if not path.exists():
            return False, f"File does not exist: {file_path}"

        if not path.is_file():
            return False, f"Path is a directory: {file_path}"

        # Check supported extensions
        supported_extensions = {'.svs', '.tif', '.tiff', '.ndpi', '.mrxs', '.vms', '.vmu', '.scn'}
        if path.suffix.lower() not in supported_extensions:
            return False, f"Unsupported file format: {path.suffix}"

        return True, "Valid file path"

    @staticmethod
    def format_slide_info(info: Dict[str, Any]) -> str:
        """
        Format slide information as a display string for the user

        Args:
            info: Slide information dictionary

        Returns:
            Formatted information string
        """
        width, height = info['dimensions']
        level_count = info['level_count']

        text = f"""Slide Information

Size: {width:,} x {height:,} pixels
Levels: {level_count}
"""

        if 'mpp' in info:
            text += f"MPP: {info['mpp']:.4f} \u00b5m/pixel\n"

        text += "\nPer-level Information:\n"
        for i, (dims, downsample) in enumerate(zip(info['level_dimensions'], info['level_downsamples'])):
            text += f"  Level {i}: {dims[0]:,} x {dims[1]:,} (downsample: {downsample:.2f}x)\n"

        return text
