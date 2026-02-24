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

# DLL 경로 설정 (import 전에 반드시 실행)
dll_paths = [
    bundle_dir,  # 실행 파일과 같은 디렉토리
    bundle_dir / "torch" / "lib",  # PyTorch DLL
    bundle_dir / "_internal",
    bundle_dir / "_internal" / "torch" / "lib",
    bundle_dir / "libs",
    bundle_dir / "libs" / "openslide_lib" / "bin",
    bundle_dir / "openslide_bin",
    application_path / "libs",
    application_path / "libs" / "openslide_lib" / "bin",
    application_path / "torch" / "lib",  # PyTorch DLL (개발 모드)
]

# OpenSlide 환경변수 설정 (중요!)
for dll_path in dll_paths:
    if dll_path.exists():
        os.environ['OPENSLIDE_PATH'] = str(dll_path)
        print(f"Set OPENSLIDE_PATH: {dll_path}")
        break

# PATH 환경 변수에 추가 (앞쪽에 배치)
path_additions = []
for dll_path in dll_paths:
    if dll_path.exists():
        path_str = str(dll_path)
        if path_str not in os.environ.get('PATH', ''):
            path_additions.append(path_str)
            print(f"Added to PATH: {dll_path}")

if path_additions:
    os.environ['PATH'] = os.pathsep.join(path_additions) + os.pathsep + os.environ.get('PATH', '')

# Windows 10+ DLL 디렉토리 추가
for dll_path in dll_paths:
    if dll_path.exists():
        try:
            os.add_dll_directory(str(dll_path))
            print(f"Added DLL directory: {dll_path}")
        except (AttributeError, OSError) as e:
            print(f"Failed to add DLL directory {dll_path}: {e}")

from PyQt5.QtWidgets import QApplication, QMessageBox
from ui.viewer import PathologyViewer
import traceback
import logging
from datetime import datetime

# 로깅 설정 (파일 출력 비활성화, 콘솔만 사용)
logging.basicConfig(
    level=logging.WARNING,  # WARNING 이상만 출력
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def main():
    """메인 애플리케이션 실행"""
    try:

        app = QApplication(sys.argv)
        app.setApplicationName("Pathology AI Viewer")
        
        # 애플리케이션 아이콘 설정 (bundle_dir 기준으로 icon/app_icon.ico 사용)
        try:
            from PyQt5.QtGui import QIcon
            icon_path = bundle_dir / "icon" / "app_icon.ico"
            if icon_path.exists():
                app.setWindowIcon(QIcon(str(icon_path)))
            else:
                # fallback: check application_path/icon
                alt_icon = application_path / "icon" / "app_icon.ico"
                if alt_icon.exists():
                    app.setWindowIcon(QIcon(str(alt_icon)))
        except Exception:
            pass
        
        # logger.info("메인 뷰어 윈도우 생성 중...")
        viewer = PathologyViewer()
        try:
            # 메인 윈도우에도 아이콘 명시적으로 설정
            if 'icon_path' in locals() and icon_path.exists():
                viewer.setWindowIcon(QIcon(str(icon_path)))
        except Exception:
            pass
        viewer.show()
        
        
        # logger.info("애플리케이션 실행")
        sys.exit(app.exec())
        
    except Exception as e:
        error_msg = f"치명적인 오류 발생:\n\n{str(e)}\n\n{traceback.format_exc()}"
        logger.critical(error_msg)

        sys.exit(1)


if __name__ == "__main__":
    main()
