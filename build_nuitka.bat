@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo Nuitka 빌드 (PyTorch + PyQt5 네이티브 컴파일)
echo ========================================
echo.

:: conda 환경 확인
if "%CONDA_PREFIX%"=="" (
    echo   오류: CONDA_PREFIX 환경변수가 없습니다. conda 환경을 활성화하세요.
    pause
    exit /b 1
)

:: Nuitka 설치 확인
echo [1/4] Nuitka 설치 확인...
python -m nuitka --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   Nuitka 설치 중...
    pip install nuitka ordered-set
    if %errorlevel% neq 0 (
        echo   오류: Nuitka 설치 실패
        pause
        exit /b 1
    )
)
echo   완료
echo.

:: 기존 빌드 정리
echo [2/4] 기존 빌드 정리...
if exist dist_nuitka rd /s /q dist_nuitka
if exist main.build rd /s /q main.build
if exist main.dist rd /s /q main.dist
echo   완료
echo.

:: Nuitka 빌드 (앱 코드만 컴파일)
echo [3/4] 빌드 시작 (앱 코드만 컴파일, 라이브러리는 raw 포함)...
echo   (화면이 멈춘 것처럼 보여도 정상입니다)
echo.

python -m nuitka ^
  --standalone ^
  --plugin-enable=pyqt5 ^
  --nofollow-import-to=torch,torchvision,torchaudio ^
  --nofollow-import-to=ultralytics,segmentation_models_pytorch,timm ^
  --nofollow-import-to=cv2,skimage,scipy,PIL,yaml,pandas,matplotlib,openslide ^
  --nofollow-import-to=pyparsing,packaging,cycler,kiwisolver,contourpy,fonttools ^
  --nofollow-import-to=dateutil,pytz,requests,urllib3,certifi,tqdm,psutil ^
  --include-data-dir=model=model ^
  --include-data-dir=libs=libs ^
  --include-data-dir=icon=icon ^
  --include-data-dir=logo=logo ^
  --include-data-dir=ui=ui ^
  --module-parameter=torch-disable-jit=no ^
  --windows-console-mode=attach ^
  --windows-icon-from-ico=icon\app_icon.ico ^
  --output-dir=dist_nuitka ^
  main.py

if %errorlevel% neq 0 (
    echo.
    echo   오류: 빌드 실패
    pause
    exit /b 1
)

:: site-packages 전체 + stdlib 전체 복사
echo.
echo [4/4] site-packages 전체 + stdlib 복사 중 (기존 파일 유지)...
echo   (라이브러리 용량이 커서 시간이 걸립니다)
set SITE_PKG=%CONDA_PREFIX%\Lib\site-packages
set DIST=%~dp0dist_nuitka\main.dist

:: Python 스크립트로 전체 복사 (기존 항목은 덮어쓰지 않음 = Nuitka 컴파일 버전 보호)
"%CONDA_PREFIX%\python.exe" "%~dp0build_copy_deps.py" "%DIST%"

if %errorlevel% neq 0 (
    echo   경고: 일부 복사 실패 (무시하고 계속)
)

:: OpenSlide DLL을 main.dist 루트로 복사
if exist "%~dp0libs\openslide_lib\bin" (
    xcopy "%~dp0libs\openslide_lib\bin\*" "%DIST%\" /Y /Q >nul
    echo   OpenSlide DLL 복사 완료
)

echo.
echo ========================================
echo 빌드 완료!
echo ========================================
echo.
echo 실행 파일: dist_nuitka\main.dist\main.exe
echo.
echo 배포 시:
echo   dist_nuitka\main.dist\ 폴더 전체를 배포
echo.
pause
