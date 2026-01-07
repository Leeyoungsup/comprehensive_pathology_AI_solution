"""
Comprehensive Pathology AI Solution - Main Entry Point
병리 이미지 뷰어 및 AI 분석 통합 프로그램
"""

import sys
import os
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# OpenSlide DLL 경로 설정
openslide_dll_path = project_root / "libs"
if openslide_dll_path.exists():
    os.add_dll_directory(str(openslide_dll_path))

from PyQt5.QtWidgets import QApplication
from ui.viewer import PathologyViewer
import openslide


def main():
    """메인 애플리케이션 실행"""
    app = QApplication(sys.argv)
    app.setApplicationName("Pathology AI Viewer")
    
    # 메인 뷰어 윈도우 생성
    viewer = PathologyViewer()
    viewer.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
