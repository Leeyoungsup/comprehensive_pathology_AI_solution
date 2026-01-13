@echo off
chcp 65001 >nul
REM cx_Freeze 빌드 스크립트

echo ========================================
echo cx_Freeze로 빌드 시작
echo ========================================
echo.

REM 1. cx_Freeze 설치 확인
echo [1/4] cx_Freeze 설치 확인 중...
pip show cx_Freeze >nul 2>&1
if %errorlevel% neq 0 (
    echo   cx_Freeze가 설치되지 않았습니다. 설치 중...
    pip install cx_Freeze
)
echo   설치 완료
echo.

REM 2. 이전 빌드 삭제
echo [2/4] 이전 빌드 정리 중...
if exist build (
    rmdir /s /q build
)
echo   정리 완료
echo.

REM 3. 빌드 실행
echo [3/4] 빌드 실행 중...
echo   (10-20분 소요될 수 있습니다)
echo.

python setup_cx_freeze.py build

if %errorlevel% neq 0 (
    echo.
    echo 빌드 실패!
    pause
    exit /b 1
)

echo.
echo [4/4] 빌드 완료!
echo.

REM 빌드 결과 확인
for /d %%i in (build\exe.*) do set BUILD_DIR=%%i

if exist "%BUILD_DIR%\PathologyAIViewer.exe" (
    echo ========================================
    echo 빌드 성공!
    echo ========================================
    echo.
    echo 실행 파일: %BUILD_DIR%\PathologyAIViewer.exe
    echo.
    echo 배포 방법:
    echo   1. '%BUILD_DIR%' 폴더 전체를 압축
    echo   2. 사용자에게 압축 파일 배포
    echo   3. 압축 해제 후 PathologyAIViewer.exe 실행
    echo.
    
    set /p response="빌드된 파일을 실행하시겠습니까? (Y/N): "
    if /i "%response%"=="Y" (
        start "" "%BUILD_DIR%\PathologyAIViewer.exe"
    )
) else (
    echo 빌드 실패: 실행 파일을 찾을 수 없습니다.
)

echo.
pause
