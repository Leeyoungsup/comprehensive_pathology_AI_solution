"""
Comprehensive Pathology AI Solution - Main Entry Point
병리 이미지 뷰어 및 AI 분석 통합 프로그램
"""

import sys
import os
from pathlib import Path

# PyInstaller 실행 파일인 경우와 스크립트 실행 구분
if getattr(sys, 'frozen', False):
    # PyInstaller로 빌드된 실행 파일의 디렉토리
    application_path = Path(sys.executable).parent
    # _MEIPASS는 PyInstaller의 임시 폴더
    if hasattr(sys, '_MEIPASS'):
        bundle_dir = Path(sys._MEIPASS)
    else:
        bundle_dir = application_path
else:
    # 스크립트로 실행
    application_path = Path(__file__).parent
    bundle_dir = application_path

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(application_path))

# OpenSlide DLL 경로 설정 (import 전에 반드시 실행)
dll_paths = [
    bundle_dir,  # 실행 파일과 같은 디렉토리
    bundle_dir / "libs",
    bundle_dir / "libs" / "openslide_lib" / "bin",
    bundle_dir / "openslide_bin",
    application_path / "libs",
    application_path / "libs" / "openslide_lib" / "bin",
]

# OpenSlide 환경변수 설정 (중요!)
for dll_path in dll_paths:
    if dll_path.exists():
        os.environ['OPENSLIDE_PATH'] = str(dll_path)
        print(f"Set OPENSLIDE_PATH: {dll_path}")
        break

# PATH 환경 변수에 추가
for dll_path in dll_paths:
    if dll_path.exists():
        path_str = str(dll_path)
        if path_str not in os.environ.get('PATH', ''):
            os.environ['PATH'] = path_str + os.pathsep + os.environ.get('PATH', '')
            print(f"Added to PATH: {dll_path}")

# Windows 10+ DLL 디렉토리 추가
for dll_path in dll_paths:
    if dll_path.exists():
        try:
            os.add_dll_directory(str(dll_path))
            print(f"Added DLL directory: {dll_path}")
        except (AttributeError, OSError) as e:
            print(f"Failed to add DLL directory {dll_path}: {e}")

from PyQt5.QtWidgets import QApplication
from ui.viewer import PathologyViewer


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
