@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo Portable Python 환경 생성
echo ========================================
echo.

:: 1. conda-pack 설치 확인
echo [1/5] conda-pack 설치 확인...
call conda list conda-pack 2>nul | findstr "conda-pack" >nul
if %errorlevel% neq 0 (
    echo   conda-pack 설치 중... (1-2분 소요)
    call conda install -c conda-forge conda-pack -y
    if %errorlevel% neq 0 (
        echo   오류: conda-pack 설치 실패
        pause
        exit /b 1
    )
) else (
    echo   이미 설치됨
)
echo.

:: 2. 현재 환경 패키징
echo [2/5] 현재 conda 환경 패키징 중...
echo   환경: %CONDA_DEFAULT_ENV%
echo.

if exist portable_env.tar.gz (
    echo   기존 portable_env.tar.gz 파일 발견!
    echo   재사용하시겠습니까? (Y/N^)
    choice /C YN /N /M "  [Y] 재사용  [N] 새로 생성: "
    if errorlevel 2 (
        echo   기존 파일 삭제 중...
        del portable_env.tar.gz
        goto :create_pack
    ) else (
        echo   기존 파일 재사용
        goto :pack_done
    )
)

:create_pack
echo   *** 10-15분 소요됩니다. 진행 중이니 기다려주세요! ***
echo.
echo   conda pack 실행 중...
echo   (화면이 멈춘 것처럼 보여도 정상입니다)
echo.
call conda pack -n %CONDA_DEFAULT_ENV% -o portable_env.tar.gz

if %errorlevel% neq 0 (
    echo.
    echo   오류: conda pack 실패
    pause
    exit /b 1
)

:pack_done
echo.
echo   패키징 완료!
echo.

:: 3. 배포 폴더 생성
echo [3/5] 배포 폴더 생성 중...

if exist PathologyAIViewer_Portable (
    echo   기존 폴더 삭제 중...
    rd /s /q PathologyAIViewer_Portable
)

mkdir PathologyAIViewer_Portable
mkdir PathologyAIViewer_Portable\python_env
echo   폴더 생성 완료
echo.

:: 4. 환경 압축 해제
echo [4/5] 환경 압축 해제 중...
echo   (3-5분 소요)
tar -xzf portable_env.tar.gz -C PathologyAIViewer_Portable\python_env

if %errorlevel% neq 0 (
    echo.
    echo   오류: 압축 해제 실패
    pause
    exit /b 1
)
echo   압축 해제 완료!
echo.

:: 5. 프로젝트 파일 복사
echo [5/5] 프로젝트 파일 복사 중...

:: 개별 파일 복사
if exist main.py (copy main.py PathologyAIViewer_Portable\ >nul && echo   main.py 복사)
if exist requirements.txt (copy requirements.txt PathologyAIViewer_Portable\ >nul && echo   requirements.txt 복사)
if exist README.md (copy README.md PathologyAIViewer_Portable\ >nul && echo   README.md 복사)

:: 폴더 복사
if exist ai (xcopy ai PathologyAIViewer_Portable\ai\ /E /I /Y /Q >nul && echo   ai\ 폴더 복사)
if exist backend (xcopy backend PathologyAIViewer_Portable\backend\ /E /I /Y /Q >nul && echo   backend\ 폴더 복사)
if exist core (xcopy core PathologyAIViewer_Portable\core\ /E /I /Y /Q >nul && echo   core\ 폴더 복사)
if exist ui (xcopy ui PathologyAIViewer_Portable\ui\ /E /I /Y /Q >nul && echo   ui\ 폴더 복사)
if exist utils (xcopy utils PathologyAIViewer_Portable\utils\ /E /I /Y /Q >nul && echo   utils\ 폴더 복사)
if exist libs (xcopy libs PathologyAIViewer_Portable\libs\ /E /I /Y /Q >nul && echo   libs\ 폴더 복사)
if exist model (xcopy model PathologyAIViewer_Portable\model\ /E /I /Y /Q >nul && echo   model\ 폴더 복사)
if exist icon (xcopy icon PathologyAIViewer_Portable\icon\ /E /I /Y /Q >nul && echo   icon\ 폴더 복사)

echo   파일 복사 완료!
echo.

:: 실행 배치 파일 생성
echo @echo off > PathologyAIViewer_Portable\run.bat
echo chcp 65001 ^>nul >> PathologyAIViewer_Portable\run.bat
echo echo Pathology AI Viewer 시작 중... >> PathologyAIViewer_Portable\run.bat
echo echo. >> PathologyAIViewer_Portable\run.bat
echo. >> PathologyAIViewer_Portable\run.bat
echo REM Python 환경 활성화 >> PathologyAIViewer_Portable\run.bat
echo call python_env\Scripts\activate.bat >> PathologyAIViewer_Portable\run.bat
echo. >> PathologyAIViewer_Portable\run.bat
echo REM 프로그램 실행 >> PathologyAIViewer_Portable\run.bat
echo python main.py >> PathologyAIViewer_Portable\run.bat
echo. >> PathologyAIViewer_Portable\run.bat
echo pause >> PathologyAIViewer_Portable\run.bat

echo.
echo ========================================
echo 배포 패키지 생성 완료!
echo ========================================
echo.
echo 배포 폴더: PathologyAIViewer_Portable\
echo 실행 방법: run.bat 더블클릭
echo.
echo 배포 시:
echo 1. PathologyAIViewer_Portable 폴더 전체를 압축
echo 2. 대상 PC에서 압축 해제
echo 3. run.bat 실행
echo.
echo 임시 파일 정리 중...
if exist portable_env.tar.gz del portable_env.tar.gz
echo 완료!
echo.
pause
