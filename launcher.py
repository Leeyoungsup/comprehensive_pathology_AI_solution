"""
Pathology AI Viewer Launcher
콘솔 없이 실행되는 런처
"""
import sys
import os
import subprocess
from pathlib import Path

def get_python_executable():
    """포터블 환경의 Python 실행 파일 경로 찾기"""
    if getattr(sys, 'frozen', False):
        # PyInstaller로 빌드된 경우
        base_path = Path(sys.executable).parent
    else:
        # 개발 환경
        base_path = Path(__file__).parent
    
    # 포터블 환경 Python 경로
    python_exe = base_path / "python_env" / "python.exe"
    
    if python_exe.exists():
        return str(python_exe)
    
    # pythonw.exe 시도 (콘솔 없이)
    pythonw_exe = base_path / "python_env" / "pythonw.exe"
    if pythonw_exe.exists():
        return str(pythonw_exe)
    
    return None

def main():
    # Python 실행 파일 찾기
    python_exe = get_python_executable()
    
    if not python_exe:
        # 오류 메시지 표시 (간단한 GUI)
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "오류",
                "Python 환경을 찾을 수 없습니다.\n\n"
                "PathologyAIViewer_Portable 폴더 내에\n"
                "python_env 폴더가 있는지 확인하세요."
            )
        except:
            pass
        sys.exit(1)
    
    # main.py 경로
    if getattr(sys, 'frozen', False):
        main_py = Path(sys.executable).parent / "main.py"
    else:
        main_py = Path(__file__).parent / "main.py"
    
    if not main_py.exists():
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "오류",
                f"main.py를 찾을 수 없습니다.\n\n경로: {main_py}"
            )
        except:
            pass
        sys.exit(1)
    
    # Python 스크립트 실행 (콘솔 없이)
    # pythonw.exe 사용 시 콘솔 창 표시 안 됨
    subprocess.Popen(
        [python_exe, str(main_py)],
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
        close_fds=True
    )

if __name__ == "__main__":
    main()
