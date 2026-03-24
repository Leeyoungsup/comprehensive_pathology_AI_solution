"""
Post-build dependency copy script
Copies entire site-packages + stdlib into main.dist
(Existing files are not touched, preserving Nuitka-compiled versions)
"""
import shutil
import os
import sys

if len(sys.argv) < 2:
    print("Usage: python build_copy_deps.py <dist_path>")
    sys.exit(1)

dst = sys.argv[1]
stdlib = os.path.dirname(os.__file__)

# site-packages path: select path containing 'site-packages'
import site as _site
site_pkgs = _site.getsitepackages()
site_pkg = next((p for p in site_pkgs if p.endswith('site-packages')), None)
if site_pkg is None:
    # fallback: site-packages next to stdlib
    site_pkg = os.path.join(stdlib, 'site-packages')
print(f"  site-packages: {site_pkg}")
print(f"  stdlib: {stdlib}")
print(f"  dst: {dst}")

skip_names = {'__pycache__', 'test', 'tests', 'idle', 'tkinter', 'turtle',
              'turtledemo', 'ensurepip', 'venv', 'distutils'}

def copy_tree_if_new(src_root, dst_root, label):
    if not os.path.isdir(src_root):
        print(f"  Warning: {src_root} not found, skipping")
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
            continue  # Skip if already exists
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst_path,
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
            else:
                shutil.copy2(src, dst_path)
            copied += 1
        except Exception as e:
            errors += 1
    print(f"  {label}: {copied} items copied (errors: {errors})")

print("Copying site-packages...")
copy_tree_if_new(site_pkg, dst, 'site-packages')

print("Copying stdlib...")
copy_tree_if_new(stdlib, dst, 'stdlib')

print("Done!")
