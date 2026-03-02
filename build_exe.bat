@echo off
chcp 65001 >nul
echo ========================================
echo PathologyAIViewer.exe 생성
echo ========================================
echo.

echo [1/2] PyInstaller 확인...
call pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo   PyInstaller 설치 중...
    call pip install pyinstaller
)
echo   완료
echo.

echo [2/2] EXE 파일 빌드 중...

:: 기존 빌드 정리
if exist build rd /s /q build
if exist dist rd /s /q dist
if exist PathologyAIViewer.spec del PathologyAIViewer.spec

:: 아이콘 파일 확인
set ICON_OPTION=
if exist icon\app_icon.ico (
    echo   아이콘: icon\app_icon.ico
    set ICON_OPTION=--icon=icon\app_icon.ico
) else (
    echo   아이콘 없음 (기본 아이콘 사용)
)

echo   빌드 시작...
:: PyInstaller 실행
call pyinstaller --onefile --noconsole --name=PathologyAIViewer %ICON_OPTION% --clean run_app.py

if %errorlevel% neq 0 (
    echo.
    echo   오류: 빌드 실패
    pause
    exit /b 1
)

echo.
echo ========================================
echo 빌드 완료!
echo ========================================
echo.
echo 생성된 파일: dist\PathologyAIViewer.exe
echo.
echo 다음 단계:
echo 1. dist\PathologyAIViewer.exe를 PathologyAIViewer_Portable\ 폴더로 복사
echo 2. PathologyAIViewer.exe 더블클릭으로 실행 (콘솔 없음)
echo.

:: 자동으로 복사
if exist PathologyAIViewer_Portable (
    echo 자동으로 Portable 폴더에 복사 중...
    
    :: 기존 파일 삭제 (아이콘 캐시 문제 방지)
    if exist PathologyAIViewer_Portable\PathologyAIViewer.exe (
        del PathologyAIViewer_Portable\PathologyAIViewer.exe
    )
    
    :: 아이콘 캐시 삭제 (Windows 10/11)
    echo   아이콘 캐시 초기화 중...
    taskkill /f /im explorer.exe >nul 2>&1
    del /f /s /q /a "%LOCALAPPDATA%\IconCache.db" >nul 2>&1
    del /f /s /q /a "%LOCALAPPDATA%\Microsoft\Windows\Explorer\iconcache*" >nul 2>&1
    start explorer.exe
    timeout /t 2 /nobreak >nul
    
    :: 새 파일 복사
    copy dist\PathologyAIViewer.exe PathologyAIViewer_Portable\ >nul
    echo   복사 완료: PathologyAIViewer_Portable\PathologyAIViewer.exe
    echo   아이콘이 적용되었습니다!
    echo.
)

pause
