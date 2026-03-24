"""
Comprehensive Pathology AI Solution - Main Entry Point
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

    # Explicitly enable Torch JIT in Nuitka standalone
    os.environ.setdefault('PYTORCH_JIT', '1')
else:
    # Running as script (development mode)
    application_path = Path(__file__).parent
    bundle_dir = application_path

# Add project root to Python path
sys.path.insert(0, str(application_path))

# DLL path configuration (must run before imports)
dll_paths = [
    bundle_dir,  # Same directory as the executable
    bundle_dir / "torch" / "lib",  # PyTorch DLL
    bundle_dir / "_internal",
    bundle_dir / "_internal" / "torch" / "lib",
    bundle_dir / "libs",
    bundle_dir / "libs" / "openslide_lib" / "bin",
    bundle_dir / "openslide_bin",
    application_path / "libs",
    application_path / "libs" / "openslide_lib" / "bin",
    application_path / "torch" / "lib",  # PyTorch DLL (development mode)
]

# Set OpenSlide environment variable (important!)
for dll_path in dll_paths:
    if dll_path.exists():
        os.environ['OPENSLIDE_PATH'] = str(dll_path)
        break

# Add to PATH environment variable (prepend)
path_additions = []
for dll_path in dll_paths:
    if dll_path.exists():
        path_str = str(dll_path)
        if path_str not in os.environ.get('PATH', ''):
            path_additions.append(path_str)

if path_additions:
    os.environ['PATH'] = os.pathsep.join(path_additions) + os.pathsep + os.environ.get('PATH', '')

# Add DLL directories for Windows 10+
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

# Logging configuration (file output disabled, console only)
logging.basicConfig(
    level=logging.WARNING,  # Only output WARNING and above
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def main():
    """Run the main application"""
    try:

        app = QApplication(sys.argv)
        app.setApplicationName("Pathology AI Viewer")

        # Set application icon
        try:
            icon_path = bundle_dir / "icon" / "app_icon.ico"
            if not icon_path.exists():
                icon_path = application_path / "icon" / "app_icon.ico"
            if icon_path.exists():
                app.setWindowIcon(QIcon(str(icon_path)))
        except Exception:
            pass

        # Show splash screen (display before heavy imports)
        splash = None
        logo_path = bundle_dir / "logo" / "Logo.png"
        if not logo_path.exists():
            logo_path = application_path / "logo" / "Logo.png"
        if logo_path.exists():
            splash_pixmap = QPixmap(str(logo_path))
            splash = QSplashScreen(splash_pixmap, Qt.WindowStaysOnTopHint)
            splash.show()
            app.processEvents()

        # Heavy imports (after splash screen)
        from ui.viewer import PathologyViewer

        viewer = PathologyViewer()
        try:
            if 'icon_path' in locals() and icon_path.exists():
                viewer.setWindowIcon(QIcon(str(icon_path)))
        except Exception:
            pass

        if splash:
            splash.finish(viewer)
        viewer.show()
        
        
        # logger.info("Application started")
        sys.exit(app.exec())
        
    except Exception as e:
        error_msg = f"Fatal error occurred:\n\n{str(e)}\n\n{traceback.format_exc()}"
        logger.critical(error_msg)

        sys.exit(1)


if __name__ == "__main__":
    main()
