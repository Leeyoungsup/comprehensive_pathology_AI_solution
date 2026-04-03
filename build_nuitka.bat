@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo MeDICus Studio - Nuitka Build
echo ========================================
echo.

echo [1/4] Checking build environment...

call pip show nuitka >nul 2>&1
if %errorlevel% neq 0 (
    echo   Installing Nuitka...
    call pip install nuitka ordered-set zstandard
    if %errorlevel% neq 0 (
        echo   Error: Nuitka install failed
        pause
        exit /b 1
    )
)
echo   Nuitka: OK

where cl >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   [WARNING] MSVC compiler cl.exe not found in PATH.
    echo   Please run this script from Developer Command Prompt
    echo   or install Visual Studio Build Tools.
    echo.
    pause
)
echo   Compiler: OK
echo.

echo [2/4] Cleaning previous build...
if exist dist_nuitka rd /s /q dist_nuitka
if exist main.build rd /s /q main.build
echo   Done
echo.

echo [3/4] Starting Nuitka build...
echo   This may take 30 min to 1 hour. Please wait.
echo.

set ICON_OPTION=
if exist icon\app_icon.ico (
    set ICON_OPTION=--windows-icon-from-ico=icon\app_icon.ico
    echo   Icon: icon\app_icon.ico
)

echo   Building...
echo.

python -m nuitka --standalone --windows-console-mode=disable --output-dir=dist_nuitka --company-name=MeDICus --product-name="MeDICus Studio" --product-version=1.0.0 %ICON_OPTION% --enable-plugin=pyqt5 --include-package=ai --include-package=backend --include-package=core --include-package=ui --include-package=utils --include-package=ultralytics --include-package=segmentation_models_pytorch --include-data-dir=icon=icon --include-data-dir=logo=logo --include-data-dir=model=model --include-data-dir=libs/openslide_lib=libs/openslide_lib --include-data-files=libs/openslide_lib/bin/libopenslide-1.dll=libs/openslide_lib/bin/libopenslide-1.dll main.py

if %errorlevel% neq 0 (
    echo.
    echo   Error: Nuitka build failed
    echo   1. Check Visual Studio Build Tools
    echo   2. Run from Developer Command Prompt
    echo   3. pip install nuitka --upgrade
    echo.
    pause
    exit /b 1
)

echo.
echo   Build complete!
echo.

echo [4/4] Creating deploy folder...

set DIST_DIR=dist_nuitka\main.dist
set DEPLOY_DIR=MeDICusStudio

if not exist "%DIST_DIR%" (
    echo   Error: %DIST_DIR% not found.
    pause
    exit /b 1
)

if exist %DEPLOY_DIR% (
    echo   Removing old %DEPLOY_DIR%...
    rd /s /q %DEPLOY_DIR%
)

echo   Copying %DIST_DIR% to %DEPLOY_DIR%...
xcopy "%DIST_DIR%" "%DEPLOY_DIR%\" /E /I /Y /Q >nul

if not exist "%DEPLOY_DIR%\libs\openslide_lib\bin\libopenslide-1.dll" (
    echo.
    echo   [WARNING] OpenSlide DLL missing. Copying manually...
    if not exist "%DEPLOY_DIR%\libs\openslide_lib\bin" mkdir "%DEPLOY_DIR%\libs\openslide_lib\bin"
    xcopy "libs\openslide_lib" "%DEPLOY_DIR%\libs\openslide_lib\" /E /I /Y /Q >nul
    echo   OpenSlide DLL copied
)

if exist "%DEPLOY_DIR%\main.exe" (
    rename "%DEPLOY_DIR%\main.exe" MeDICusStudio.exe
    echo   Renamed main.exe to MeDICusStudio.exe
)

echo.
echo ========================================
echo Nuitka Build Complete!
echo ========================================
echo.
echo Deploy folder: %DEPLOY_DIR%\
echo Executable:    %DEPLOY_DIR%\MeDICusStudio.exe
echo.
echo Resources:
if exist "%DEPLOY_DIR%\libs\openslide_lib\bin\libopenslide-1.dll" (echo   [O] OpenSlide DLL) else (echo   [X] OpenSlide DLL - check needed!)
if exist "%DEPLOY_DIR%\model" (echo   [O] AI model files) else (echo   [X] AI model files - check needed!)
if exist "%DEPLOY_DIR%\icon" (echo   [O] Icons)
if exist "%DEPLOY_DIR%\logo" (echo   [O] Logo)
echo.

if exist main.build (
    echo Cleaning build cache...
    rd /s /q main.build
    echo Done
    echo.
)

pause
