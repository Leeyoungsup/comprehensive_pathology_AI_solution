@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo Nuitka 빌드 (PyTorch + PyQt5 네이티브 컴파일)
echo ========================================
echo.

:: Nuitka 설치 확인
echo [1/3] Nuitka 설치 확인...
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
echo [2/3] 기존 빌드 정리...
if exist dist_nuitka rd /s /q dist_nuitka
if exist main.build rd /s /q main.build
if exist main.dist rd /s /q main.dist
echo   완료
echo.

:: Nuitka 빌드
echo [3/3] 빌드 시작 (앱 코드만 컴파일, 무거운 라이브러리는 raw 포함)...
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

:: 제외된 패키지를 conda env에서 dist 폴더로 복사
echo.
echo [4/4] 제외된 패키지 복사 중 (torch, ultralytics 등)...
set SITE_PKG=%CONDA_PREFIX%\Lib\site-packages
set DIST=%~dp0dist_nuitka\main.dist

if "%CONDA_PREFIX%"=="" (
    echo   경고: CONDA_PREFIX 환경변수가 없습니다. conda 환경을 활성화하세요.
    pause
    exit /b 1
)

:: 대형 패키지 (폴더명 = 패키지명)
for %%p in (torch torchvision torchaudio ultralytics segmentation_models_pytorch timm skimage scipy pandas matplotlib openslide) do (
    if exist "%SITE_PKG%\%%p" (
        xcopy "%SITE_PKG%\%%p" "%DIST%\%%p\" /E /I /Y /Q >nul
        echo   %%p 복사 완료
    )
)

:: 파일명이 다른 패키지들
if exist "%SITE_PKG%\cv2" (xcopy "%SITE_PKG%\cv2" "%DIST%\cv2\" /E /I /Y /Q >nul && echo   cv2 복사 완료)
if exist "%SITE_PKG%\PIL" (xcopy "%SITE_PKG%\PIL" "%DIST%\PIL\" /E /I /Y /Q >nul && echo   PIL 복사 완료)
if exist "%SITE_PKG%\yaml" (xcopy "%SITE_PKG%\yaml" "%DIST%\yaml\" /E /I /Y /Q >nul && echo   yaml 복사 완료)

:: pyyaml .pyd 파일 (있는 경우)
for %%f in ("%SITE_PKG%\_yaml*.pyd") do (copy "%%f" "%DIST%\" /Y >nul 2>nul)
for %%f in ("%SITE_PKG%\PyYAML*.dist-info") do (xcopy "%%f" "%DIST%\%%~nxf\" /E /I /Y /Q >nul 2>nul)

:: 소형 트랜지티브 의존성 패키지들 (matplotlib, pandas, ultralytics 등의 deps)
echo   트랜지티브 의존성 복사 중...
for %%p in (
    packaging pyparsing cycler kiwisolver contourpy fonttools
    dateutil pytz six tzdata
    requests urllib3 certifi charset_normalizer idna
    tqdm psutil cpuinfo
    attr attrs
    filelock sympy networkx
    accelerate safetensors huggingface_hub tokenizers
    regex sentencepiece
    colorama coloredlogs humanfriendly
    thop
) do (
    if exist "%SITE_PKG%\%%p" (
        xcopy "%SITE_PKG%\%%p" "%DIST%\%%p\" /E /I /Y /Q >nul
    )
)

:: 단일 파일 패키지 (.py) 복사
for %%f in (
    six.py pytz.py typing_extensions.py tzlocal.py
    tomllib.py exceptiongroup.py iniconfig.py pluggy.py
) do (
    if exist "%SITE_PKG%\%%f" (copy "%SITE_PKG%\%%f" "%DIST%\" /Y >nul 2>nul)
)

:: .pyd 확장 모듈 루트 수준 복사 (kiwisolver, contourpy 등)
for %%f in ("%SITE_PKG%\kiwisolver*.pyd") do (copy "%%f" "%DIST%\" /Y >nul 2>nul)
for %%f in ("%SITE_PKG%\contourpy*.pyd") do (copy "%%f" "%DIST%\" /Y >nul 2>nul)
for %%f in ("%SITE_PKG%\_imaging*.pyd") do (copy "%%f" "%DIST%\" /Y >nul 2>nul)

echo   트랜지티브 의존성 복사 완료

:: 표준 라이브러리 모듈 복사 (raw 패키지들이 import하는 stdlib)
echo   표준 라이브러리 모듈 복사 중...
python -c "import shutil, os; pkgs=['unittest','email','html','http','xml','multiprocessing','concurrent','asyncio','logging','json','re','collections','importlib']; [shutil.copytree(os.path.join(os.path.dirname(os.__file__), p), os.path.join(r'%DIST%', p), dirs_exist_ok=True) for p in pkgs if os.path.isdir(os.path.join(os.path.dirname(os.__file__), p))]" 2>nul
echo   표준 라이브러리 복사 완료

:: OpenSlide DLL을 main.dist 루트로 복사 (EXE 옆에 있어야 로딩 확실)
if exist "%~dp0libs\openslide_lib\bin" (
    xcopy "%~dp0libs\openslide_lib\bin\*" "%DIST%\" /Y /Q >nul
    echo   OpenSlide DLL 복사 완료
)

echo   패키지 복사 완료
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
