@echo off
chcp 65001 >nul
echo ========================================
echo Creating PathologyAIViewer.exe
echo ========================================
echo.

echo [1/2] Checking PyInstaller...
call pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo   Installing PyInstaller...
    call pip install pyinstaller
)
echo   Done
echo.

echo [2/2] Building EXE...

:: 기존 빌드 정리
if exist build rd /s /q build
if exist dist rd /s /q dist
if exist PathologyAIViewer.spec del PathologyAIViewer.spec

:: 아이콘 파일 확인
set ICON_OPTION=
if exist icon\app_icon.ico (
    echo   Icon: icon\app_icon.ico
    set ICON_OPTION=--icon=icon\app_icon.ico
) else (
    echo   No icon (using default)
)

echo   Starting build...
:: PyInstaller 실행
call pyinstaller --onedir --noconsole --name=PathologyAIViewer %ICON_OPTION% --clean run_app.py

if %errorlevel% neq 0 (
    echo.
    echo   Error: build failed
    pause
    exit /b 1
)

echo.
echo ========================================
echo Build complete!
echo ========================================
echo.
echo Generated file: dist\PathologyAIViewer.exe
echo.
echo Next steps:
echo 1. Copy dist\PathologyAIViewer.exe to PathologyAIViewer_Portable\ folder
echo 2. Run PathologyAIViewer.exe by double clicking (no console)
echo.

:: 자동으로 복사
if exist PathologyAIViewer_Portable (
    echo Copying to Portable folder automatically...
    
    :: 기존 파일/폴더 삭제
    if exist PathologyAIViewer_Portable\PathologyAIViewer.exe (
        del PathologyAIViewer_Portable\PathologyAIViewer.exe
    )
    if exist PathologyAIViewer_Portable\_internal (
        rd /s /q PathologyAIViewer_Portable\_internal
    )

    :: exe + _internal 폴더 복사 (--onedir 방식: 압축 해제 없이 즉시 실행)
    copy dist\PathologyAIViewer\PathologyAIViewer.exe PathologyAIViewer_Portable\ >nul
    if exist dist\PathologyAIViewer\_internal (
        xcopy dist\PathologyAIViewer\_internal PathologyAIViewer_Portable\_internal\ /E /I /Y /Q >nul
    )
    echo   Copy complete: PathologyAIViewer_Portable\PathologyAIViewer.exe
    echo   Icon applied!
    echo.
)

pause
