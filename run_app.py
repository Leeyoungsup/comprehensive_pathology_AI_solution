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
    
    # 환경 변수 설정
    env = os.environ.copy()
    
    # OpenSlide DLL 경로 추가
    libs_path = base_path / "libs" / "openslide_lib" / "bin"
    if libs_path.exists():
        env['PATH'] = str(libs_path) + os.pathsep + env.get('PATH', '')
    
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
