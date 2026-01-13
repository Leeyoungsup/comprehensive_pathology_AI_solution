"""
cx_Freeze Setup Script for Pathology AI Viewer
PyTorch와 호환성이 우수한 cx_Freeze 사용
"""
import sys
from cx_Freeze import setup, Executable
from pathlib import Path

# 재귀 깊이 증가 (pandas/numpy 등 복잡한 패키지 스캔을 위해)
sys.setrecursionlimit(5000)

# 프로젝트 루트
project_root = Path(__file__).parent

# 포함할 패키지 - zip_include_packages로 이동할 것
packages = [
    "numpy",
    "cv2",
    "PIL",
    "torch",
    "torchvision",
    "ultralytics",
    "openslide",
]

# 포함할 모듈
includes = [
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.QtWidgets",
    "PyQt5.QtPrintSupport",
]

# zip으로 포함할 패키지 (재귀 문제 방지)
zip_include_packages = [
    "pandas",
    "skimage",
    "scipy",
    "matplotlib",
    "tqdm",
    "yaml",
    "certifi",
    "charset_normalizer",
]

# 제외할 패키지 (용량 줄이기 및 재귀 방지)
excludes = [
    "tkinter",
    "unittest",
    "xml",
    "pydoc",
    "test",
    "tests",
    "IPython",
    "jupyter",
    "notebook",
    "sphinx",
    "pytest",
    "setuptools",
    "pip",
    # PyQt5 중 불필요한 모듈
    "PyQt5.QtQml",
    "PyQt5.QtQuick",
    "PyQt5.QtQuickWidgets",
    "PyQt5.QtWebEngine",
    "PyQt5.QtWebEngineCore",
    "PyQt5.QtWebEngineWidgets",
    "PyQt5.QtNetwork",
    "PyQt5.QtBluetooth",
    "PyQt5.QtDBus",
    "PyQt5.QtDesigner",
    "PyQt5.QtHelp",
    "PyQt5.QtLocation",
    "PyQt5.QtMultimedia",
    "PyQt5.QtMultimediaWidgets",
    "PyQt5.QtNfc",
    "PyQt5.QtOpenGL",
    "PyQt5.QtPositioning",
    "PyQt5.QtSensors",
    "PyQt5.QtSerialPort",
    "PyQt5.QtSql",
    "PyQt5.QtSvg",
    "PyQt5.QtTest",
    "PyQt5.QtWebChannel",
    "PyQt5.QtWebKit",
    "PyQt5.QtWebKitWidgets",
    "PyQt5.QtWebSockets",
    "PyQt5.QtX11Extras",
    "PyQt5.QtXml",
    "PyQt5.QtXmlPatterns",
]

# 포함할 파일들
include_files = []

# 1. OpenSlide DLL
openslide_lib = project_root / "libs" / "openslide_lib" / "bin"
if openslide_lib.exists():
    for dll in openslide_lib.glob("*.dll"):
        include_files.append((str(dll), f"lib/{dll.name}"))

# 2. AI 모델
model_path = project_root / "model"
if model_path.exists():
    for model_file in model_path.glob("*.pt"):
        include_files.append((str(model_file), f"model/{model_file.name}"))
    for model_file in model_path.glob("*.pth"):
        include_files.append((str(model_file), f"model/{model_file.name}"))

# 3. AI 설정
ai_utils = project_root / "ai" / "utils"
if (ai_utils / "args.yaml").exists():
    include_files.append((str(ai_utils / "args.yaml"), "ai/utils/args.yaml"))

# 4. UI 파일
ui_path = project_root / "ui"
if ui_path.exists():
    for ui_file in ui_path.glob("*.ui"):
        include_files.append((str(ui_file), f"ui/{ui_file.name}"))

# 5. 아이콘
icon_path = project_root / "icon"
if icon_path.exists():
    for icon_file in icon_path.glob("*"):
        if icon_file.is_file():
            include_files.append((str(icon_file), f"icon/{icon_file.name}"))

# Build 옵션
build_exe_options = {
    "packages": packages,
    "includes": includes,
    "excludes": excludes,
    "include_files": include_files,
    "zip_include_packages": zip_include_packages,
    "optimize": 2,
    "silent": False,
}

# 실행 파일 설정
base = "Win32GUI" if sys.platform == "win32" else None

executables = [
    Executable(
        "main.py",
        base=base,
        target_name="PathologyAIViewer.exe",
        icon=str(project_root / "icon" / "app.ico") if (project_root / "icon" / "app.ico").exists() else None,
    )
]

setup(
    name="PathologyAIViewer",
    version="1.0.0",
    description="Comprehensive Pathology AI Solution",
    options={"build_exe": build_exe_options},
    executables=executables,
)
