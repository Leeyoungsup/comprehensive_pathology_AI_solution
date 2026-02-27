"""
빌드 후 의존성 복사 스크립트
site-packages 전체 + stdlib 전체를 main.dist에 복사
(기존 파일은 건드리지 않아 Nuitka 컴파일 버전 보호)
"""
import shutil
import os
import sys

if len(sys.argv) < 2:
    print("Usage: python build_copy_deps.py <dist_path>")
    sys.exit(1)

dst = sys.argv[1]
stdlib = os.path.dirname(os.__file__)

# site-packages 경로: 'site-packages'가 포함된 경로를 선택
import site as _site
site_pkgs = _site.getsitepackages()
site_pkg = next((p for p in site_pkgs if p.endswith('site-packages')), None)
if site_pkg is None:
    # fallback: stdlib 옆의 site-packages
    site_pkg = os.path.join(stdlib, 'site-packages')
print(f"  site-packages: {site_pkg}")
print(f"  stdlib: {stdlib}")
print(f"  dst: {dst}")

skip_names = {'__pycache__', 'test', 'tests', 'idle', 'tkinter', 'turtle',
              'turtledemo', 'ensurepip', 'venv', 'distutils'}

def copy_tree_if_new(src_root, dst_root, label):
    if not os.path.isdir(src_root):
        print(f"  경고: {src_root} 없음, 건너뜀")
        return
    copied = 0
    errors = 0
    for name in os.listdir(src_root):
        if name in skip_names:
            continue
        if name.endswith(('.dist-info', '.egg-info', '.egg-link')):
            continue
        src = os.path.join(src_root, name)
        dst_path = os.path.join(dst_root, name)
        if os.path.exists(dst_path):
            continue  # 이미 있으면 건드리지 않음
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst_path,
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
            else:
                shutil.copy2(src, dst_path)
            copied += 1
        except Exception as e:
            errors += 1
    print(f"  {label}: {copied}개 항목 복사 완료 (오류: {errors}개)")

print("site-packages 복사 중...")
copy_tree_if_new(site_pkg, dst, 'site-packages')

print("stdlib 복사 중...")
copy_tree_if_new(stdlib, dst, 'stdlib')

print("완료!")
