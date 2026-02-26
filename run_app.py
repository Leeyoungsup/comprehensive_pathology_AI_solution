"""
Pathology AI Viewer - 실행 프로그램
콘솔 없이 실행
"""
import sys
import os
import subprocess
from pathlib import Path

def main():
    # 실행 파일의 위치 확인
    if getattr(sys, 'frozen', False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent
    
    # python_env\pythonw.exe 경로
    pythonw_exe = base_path / "python_env" / "pythonw.exe"
    
    # python.exe가 없으면 pythonw.exe 확인
    if not pythonw_exe.exists():
        pythonw_exe = base_path / "python_env" / "python.exe"
    
    # main.py 경로
    main_py = base_path / "main.py"
    
    # 파일 존재 확인
    if not pythonw_exe.exists():
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            f"Python 실행 파일을 찾을 수 없습니다.\n\n경로: {pythonw_exe}",
            "오류",
            0x10  # MB_ICONERROR
        )
        sys.exit(1)

    if not main_py.exists():
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            f"main.py를 찾을 수 없습니다.\n\n경로: {main_py}",
            "오류",
            0x10
        )
        sys.exit(1)

    # 최초 1회: conda-unpack으로 경로 재설정 (빌드 머신 → 현재 머신)
    unpacked_flag = base_path / "python_env" / ".unpacked"
    if not unpacked_flag.exists():
        conda_unpack = base_path / "python_env" / "Scripts" / "conda-unpack.exe"
        if conda_unpack.exists():
            subprocess.run([str(conda_unpack)], check=False, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                unpacked_flag.touch()
            except OSError:
                pass

    # 환경 변수 설정 - activate.bat 없이 conda-pack 환경의 핵심 PATH를 직접 주입
    env = os.environ.copy()
    python_env = base_path / "python_env"

    # conda 환경이 activate.bat 없이 실행될 때 필요한 DLL/실행파일 경로들
    # (순서 중요: 앞쪽 경로가 우선 검색됨)
    conda_paths = [
        python_env,                                        # pythonw.exe 위치
        python_env / "Library" / "bin",                   # libtiff, zlib, libpng 등 네이티브 DLL
        python_env / "Library" / "mingw-w64" / "bin",     # GCC 런타임 (있는 경우)
        python_env / "Scripts",                           # conda 스크립트
        base_path / "libs" / "openslide_lib" / "bin",     # OpenSlide DLL
    ]

    path_prepend = [str(p) for p in conda_paths if p.exists()]
    if path_prepend:
        env['PATH'] = os.pathsep.join(path_prepend) + os.pathsep + env.get('PATH', '')

    # PYTHONPATH: 프로젝트 루트 명시 (conda-unpack 전 경로 문제 보완)
    env['PYTHONPATH'] = str(base_path) + os.pathsep + env.get('PYTHONPATH', '')

    # Python 실행 (콘솔 없이)
    subprocess.Popen(
        [str(pythonw_exe), str(main_py)],
        cwd=str(base_path),
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
        close_fds=True
    )

if __name__ == "__main__":
    main()
