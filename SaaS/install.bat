@echo off
REM ============================================================
REM  MeDICus Studio SaaS — 의존성 설치 스크립트
REM  - conda env 생성/갱신
REM  - PyTorch CUDA 빌드 설치
REM  - backend/requirements.txt 전체 설치
REM ============================================================
setlocal
cd /d "%~dp0"

set ENV_NAME=medicus-saas
set PY_VER=3.12
set CUDA_TAG=cu121

where conda >nul 2>&1
if errorlevel 1 (
    echo [ERROR] conda not found. Install Miniconda/Anaconda first:
    echo         https://docs.conda.io/en/latest/miniconda.html
    pause
    exit /b 1
)

echo.
echo [STEP 1/3] Checking conda environment "%ENV_NAME%" ...
call conda env list | findstr /b /c:"%ENV_NAME% " >nul
if errorlevel 1 (
    echo [INFO] Creating new env: %ENV_NAME% ^(python %PY_VER%^)
    call conda create -y -n %ENV_NAME% python=%PY_VER%
    if errorlevel 1 (
        echo [ERROR] Failed to create conda env.
        pause
        exit /b 1
    )
) else (
    echo [INFO] Env "%ENV_NAME%" already exists.
)

echo.
echo [STEP 2/3] Installing PyTorch ^(CUDA %CUDA_TAG%^) ...
call conda run -n %ENV_NAME% pip install --upgrade pip
call conda run -n %ENV_NAME% pip install torch torchvision --index-url https://download.pytorch.org/whl/%CUDA_TAG%
if errorlevel 1 (
    echo [WARN] CUDA build failed. Falling back to CPU-only PyTorch ...
    call conda run -n %ENV_NAME% pip install torch torchvision
)

echo.
echo [STEP 3/3] Installing backend requirements ...
call conda run -n %ENV_NAME% pip install -r "%~dp0backend\requirements.txt"
if errorlevel 1 (
    echo [ERROR] pip install failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo [DONE] Install complete.
echo        Run start.bat to launch the SaaS server.
echo ============================================================
pause
endlocal
