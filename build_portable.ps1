# Portable Python 환경 생성 스크립트
# conda-pack을 사용하여 전체 환경 패키징

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Portable Python 환경 생성" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. conda-pack 설치
Write-Host "[1/5] conda-pack 설치 확인..." -ForegroundColor Yellow
try {
    conda list conda-pack | Select-String "conda-pack" | Out-Null
    Write-Host "  이미 설치됨" -ForegroundColor Green
} catch {
    Write-Host "  conda-pack 설치 중..." -ForegroundColor Yellow
    conda install -c conda-forge conda-pack -y
}
Write-Host ""

# 2. 현재 환경 패키징
Write-Host "[2/5] 현재 conda 환경 패키징 중..." -ForegroundColor Yellow
Write-Host "  (5-10분 소요)" -ForegroundColor Gray

$envName = (conda info --json | ConvertFrom-Json).active_prefix_name
if (-not $envName) {
    $envName = "base"
}

Write-Host "  환경: $envName" -ForegroundColor Cyan

if (Test-Path "portable_env.tar.gz") {
    Remove-Item "portable_env.tar.gz"
}

conda pack -n $envName -o portable_env.tar.gz

Write-Host "  패키징 완료" -ForegroundColor Green
Write-Host ""

# 3. 배포 폴더 생성
Write-Host "[3/5] 배포 폴더 생성 중..." -ForegroundColor Yellow

if (Test-Path "PathologyAIViewer_Portable") {
    Remove-Item -Recurse -Force "PathologyAIViewer_Portable"
}

New-Item -ItemType Directory -Path "PathologyAIViewer_Portable" | Out-Null
New-Item -ItemType Directory -Path "PathologyAIViewer_Portable\python_env" | Out-Null

# 4. 환경 압축 해제
Write-Host "[4/5] 환경 압축 해제 중..." -ForegroundColor Yellow
tar -xzf portable_env.tar.gz -C PathologyAIViewer_Portable\python_env

# 5. 프로젝트 파일 복사
Write-Host "[5/5] 프로젝트 파일 복사 중..." -ForegroundColor Yellow

$filesToCopy = @("main.py", "requirements.txt", "README.md")
$foldersToCopy = @("ai", "backend", "core", "ui", "utils", "libs", "model", "icon")

foreach ($file in $filesToCopy) {
    if (Test-Path $file) {
        Copy-Item $file "PathologyAIViewer_Portable\" -Force
    }
}

foreach ($folder in $foldersToCopy) {
    if (Test-Path $folder) {
        Copy-Item $folder "PathologyAIViewer_Portable\" -Recurse -Force
    }
}

# 실행 배치 파일 생성
$runScript = @"
@echo off
chcp 65001 >nul
echo Pathology AI Viewer 시작 중...
echo.

REM Python 환경 활성화
call python_env\Scripts\activate.bat

REM 프로그램 실행
python main.py

pause
"@

$runScript | Out-File -FilePath "PathologyAIViewer_Portable\run.bat" -Encoding ASCII

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "배포 패키지 생성 완료!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "배포 폴더: PathologyAIViewer_Portable\" -ForegroundColor Cyan
Write-Host "실행 방법: run.bat 더블클릭" -ForegroundColor Cyan
Write-Host ""
Write-Host "배포 시:" -ForegroundColor Yellow
Write-Host "  1. PathologyAIViewer_Portable 폴더 전체를 압축" -ForegroundColor White
Write-Host "  2. 사용자에게 배포" -ForegroundColor White
Write-Host "  3. 사용자는 압축 해제 후 run.bat 실행" -ForegroundColor White
Write-Host ""
Write-Host "✅ Python 설치 불필요" -ForegroundColor Green
Write-Host "✅ 모든 의존성 포함" -ForegroundColor Green
Write-Host "✅ 즉시 실행 가능" -ForegroundColor Green
Write-Host ""

# 정리
Remove-Item "portable_env.tar.gz"

$size = [math]::Round((Get-ChildItem "PathologyAIViewer_Portable" -Recurse | Measure-Object -Property Length -Sum).Sum / 1GB, 2)
Write-Host "전체 크기: $size GB" -ForegroundColor Cyan
Write-Host ""
