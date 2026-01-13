# cx_Freeze 빌드 스크립트 (PowerShell)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "cx_Freeze로 빌드 시작" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. cx_Freeze 설치 확인
Write-Host "[1/4] cx_Freeze 설치 확인 중..." -ForegroundColor Yellow
try {
    pip show cx_Freeze | Out-Null
    Write-Host "  설치됨" -ForegroundColor Green
} catch {
    Write-Host "  cx_Freeze가 설치되지 않았습니다. 설치 중..." -ForegroundColor Yellow
    pip install cx_Freeze
}
Write-Host ""

# 2. 이전 빌드 삭제
Write-Host "[2/4] 이전 빌드 정리 중..." -ForegroundColor Yellow
if (Test-Path "build") {
    Remove-Item -Recurse -Force "build"
}
Write-Host "  정리 완료" -ForegroundColor Green
Write-Host ""

# 3. 빌드 실행
Write-Host "[3/4] 빌드 실행 중..." -ForegroundColor Yellow
Write-Host "  (10-20분 소요될 수 있습니다)" -ForegroundColor Gray
Write-Host ""

python setup_cx_freeze.py build

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "빌드 실패!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[4/4] 빌드 완료!" -ForegroundColor Green
Write-Host ""

# 빌드 결과 확인
$buildDir = Get-ChildItem "build" -Directory | Where-Object { $_.Name -like "exe.*" } | Select-Object -First 1

if ($buildDir -and (Test-Path "$($buildDir.FullName)\PathologyAIViewer.exe")) {
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "빌드 성공!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "실행 파일: $($buildDir.FullName)\PathologyAIViewer.exe" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "배포 방법:" -ForegroundColor Yellow
    Write-Host "  1. '$($buildDir.FullName)' 폴더 전체를 압축" -ForegroundColor White
    Write-Host "  2. 사용자에게 압축 파일 배포" -ForegroundColor White
    Write-Host "  3. 압축 해제 후 PathologyAIViewer.exe 실행" -ForegroundColor White
    Write-Host ""
    
    $response = Read-Host "빌드된 파일을 실행하시겠습니까? (Y/N)"
    if ($response -eq "Y" -or $response -eq "y") {
        Start-Process "$($buildDir.FullName)\PathologyAIViewer.exe"
    }
} else {
    Write-Host "빌드 실패: 실행 파일을 찾을 수 없습니다." -ForegroundColor Red
}

Write-Host ""
