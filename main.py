"""
MeDICus Studio - Main Entry Point
Pathology image viewer and integrated AI analysis program
"""

import sys
import os
from pathlib import Path

# Detect Nuitka build (__compiled__ is a Nuitka-specific builtin)
_is_nuitka = False
try:
    import __compiled__
    _is_nuitka = True
except ImportError:
    pass

# Distinguish between PyInstaller / Nuitka executable and script execution
if getattr(sys, 'frozen', False) or _is_nuitka:
    application_path = Path(sys.executable).parent
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller --onefile: temporary extraction folder
        bundle_dir = Path(sys._MEIPASS)
    else:
        # PyInstaller --onedir or Nuitka --standalone: same folder as EXE
        bundle_dir = application_path
    os.environ.setdefault('PYTORCH_JIT', '1')
else:
    # Running as script (development mode)
    application_path = Path(__file__).parent
    bundle_dir = application_path

sys.path.insert(0, str(application_path))

# DLL path configuration (must run before imports)
dll_paths = [
    bundle_dir,
    bundle_dir / "torch" / "lib",
    bundle_dir / "_internal",
    bundle_dir / "_internal" / "torch" / "lib",
    bundle_dir / "libs",
    bundle_dir / "libs" / "openslide_lib" / "bin",
    bundle_dir / "openslide_bin",
    application_path / "libs",
    application_path / "libs" / "openslide_lib" / "bin",
    application_path / "torch" / "lib",
]

# Set OpenSlide environment variable
for dll_path in dll_paths:
    if dll_path.exists():
        os.environ['OPENSLIDE_PATH'] = str(dll_path)
        break

# Add existing paths to PATH (prepend)
path_additions = [
    str(p) for p in dll_paths
    if p.exists() and str(p) not in os.environ.get('PATH', '')
]
if path_additions:
    os.environ['PATH'] = os.pathsep.join(path_additions) + os.pathsep + os.environ.get('PATH', '')

# Register DLL directories for Windows 10+
for dll_path in dll_paths:
    if dll_path.exists():
        try:
            os.add_dll_directory(str(dll_path))
        except (AttributeError, OSError):
            pass

from PyQt5.QtWidgets import QApplication, QMessageBox, QSplashScreen
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtCore import Qt
import traceback
import logging

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def main():
    """Run the main application"""
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("MeDICus Studio")

        # Set application icon
        icon_path = bundle_dir / "icon" / "app_icon.ico"
        if not icon_path.exists():
            icon_path = application_path / "icon" / "app_icon.ico"
        if icon_path.exists():
            try:
                app.setWindowIcon(QIcon(str(icon_path)))
            except Exception:
                pass

        # Show splash screen before heavy imports
        splash = None
        logo_path = bundle_dir / "logo" / "Logo.png"
        if not logo_path.exists():
            logo_path = application_path / "logo" / "Logo.png"
        if logo_path.exists():
            splash_pixmap = QPixmap(str(logo_path))
            splash = QSplashScreen(splash_pixmap, Qt.WindowStaysOnTopHint)
            splash.show()
            app.processEvents()

        def splash_msg(text):
            if splash:
                splash.showMessage(
                    f"{text}  ",
                    Qt.AlignBottom | Qt.AlignRight,
                    Qt.black,
                )
                app.processEvents()

        splash_msg("Loading libraries...")
        import numpy  # noqa: preload
        import cv2  # noqa: preload
        app.processEvents()

        splash_msg("Loading AI frameworks...")
        import torch  # noqa: preload
        import torchvision  # noqa: preload
        app.processEvents()

        splash_msg("Loading slide engine...")
        import openslide  # noqa: preload
        app.processEvents()

        splash_msg("Initializing UI...")
        from ui.viewer import PathologyViewer

        splash_msg("Starting application...")
        viewer = PathologyViewer()
        if icon_path.exists():
            try:
                viewer.setWindowIcon(QIcon(str(icon_path)))
            except Exception:
                pass

        if splash:
            splash.finish(viewer)
        viewer.show()

        sys.exit(app.exec())

    except Exception as e:
        logger.critical(f"Fatal error occurred:\n\n{e}\n\n{traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
    