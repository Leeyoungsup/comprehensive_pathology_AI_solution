"""
Pathology AI Viewer - Launch Program
Run without console
"""
import sys
import os
import subprocess
from pathlib import Path

def main():
    # Determine executable location
    if getattr(sys, 'frozen', False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent

    # python_env\pythonw.exe path
    pythonw_exe = base_path / "python_env" / "pythonw.exe"

    # If python.exe is not found, check for pythonw.exe
    if not pythonw_exe.exists():
        pythonw_exe = base_path / "python_env" / "python.exe"

    # main.py path
    main_py = base_path / "main.py"

    # Check file existence
    if not pythonw_exe.exists():
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            f"Python executable not found.\n\nPath: {pythonw_exe}",
            "Error",
            0x10  # MB_ICONERROR
        )
        sys.exit(1)

    if not main_py.exists():
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            f"main.py not found.\n\nPath: {main_py}",
            "Error",
            0x10
        )
        sys.exit(1)

    # First run: re-configure paths with conda-unpack (build machine -> current machine)
    unpacked_flag = base_path / "python_env" / ".unpacked"
    if not unpacked_flag.exists():
        conda_unpack = base_path / "python_env" / "Scripts" / "conda-unpack.exe"
        if conda_unpack.exists():
            subprocess.run([str(conda_unpack)], check=False, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                unpacked_flag.touch()
            except OSError:
                pass

    # Set environment variables - directly inject essential conda-pack environment PATHs without activate.bat
    env = os.environ.copy()
    python_env = base_path / "python_env"

    # DLL/executable paths needed when conda environment runs without activate.bat
    # (order matters: earlier paths are searched first)
    conda_paths = [
        python_env,                                        # pythonw.exe location
        python_env / "Library" / "bin",                   # Native DLLs: libtiff, zlib, libpng, etc.
        python_env / "Library" / "mingw-w64" / "bin",     # GCC runtime (if present)
        python_env / "Scripts",                           # conda scripts
        base_path / "libs" / "openslide_lib" / "bin",     # OpenSlide DLL
    ]

    path_prepend = [str(p) for p in conda_paths if p.exists()]
    if path_prepend:
        env['PATH'] = os.pathsep.join(path_prepend) + os.pathsep + env.get('PATH', '')

    # PYTHONPATH: explicitly set project root (compensates for path issues before conda-unpack)
    env['PYTHONPATH'] = str(base_path) + os.pathsep + env.get('PYTHONPATH', '')

    # Run Python (without console)
    subprocess.Popen(
        [str(pythonw_exe), str(main_py)],
        cwd=str(base_path),
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
        close_fds=True
    )

if __name__ == "__main__":
    main()
