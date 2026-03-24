@echo off
chcp 65001 >nul
echo ========================================
echo Creating Launcher EXE
echo ========================================
echo.

echo [1/2] Checking PyInstaller...
call pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo   Installing PyInstaller...
    call pip install pyinstaller
)
echo   Installation complete
echo.

echo [2/2] Building Launcher...
echo   Building GUI mode without console
echo.

:: 기존 빌드 정리
if exist build rd /s /q build
if exist dist rd /s /q dist
if exist launcher.spec del launcher.spec

:: PyInstaller 실행 (콘솔 없이, 단일 파일)
call pyinstaller --onefile --noconsole --name="PathologyAIViewer" --clean launcher.py

if %errorlevel% neq 0 (
    echo.
    echo   Error: build failed
    pause
    exit /b 1
)

echo.
echo ========================================
echo Launcher build complete!
echo ========================================
echo.
echo Generated file: dist\PathologyAIViewer.exe
echo.
echo Next steps:
echo 1. Copy dist\PathologyAIViewer.exe to PathologyAIViewer_Portable\ folder
echo 2. Run PathologyAIViewer.exe by double clicking
echo.
pause
