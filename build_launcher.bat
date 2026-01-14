@echo off
chcp 65001 >nul
echo ========================================
echo Launcher EXE 파일 생성
echo ========================================
echo.

echo [1/2] PyInstaller 설치 확인...
call pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo   PyInstaller 설치 중...
    call pip install pyinstaller
)
echo   설치 완료
echo.

echo [2/2] Launcher 빌드 중...
echo   콘솔 없는 GUI 모드로 빌드
echo.

:: 기존 빌드 정리
if exist build rd /s /q build
if exist dist rd /s /q dist
if exist launcher.spec del launcher.spec

:: PyInstaller 실행 (콘솔 없이, 단일 파일)
call pyinstaller --onefile --noconsole --name="PathologyAIViewer" --clean launcher.py

if %errorlevel% neq 0 (
    echo.
    echo   오류: 빌드 실패
    pause
    exit /b 1
)

echo.
echo ========================================
echo Launcher 빌드 완료!
echo ========================================
echo.
echo 생성된 파일: dist\PathologyAIViewer.exe
echo.
echo 다음 단계:
echo 1. dist\PathologyAIViewer.exe를 PathologyAIViewer_Portable\ 폴더로 복사
echo 2. PathologyAIViewer.exe 더블클릭으로 실행
echo.
pause
