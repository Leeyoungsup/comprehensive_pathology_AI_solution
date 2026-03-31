"""
MeDICus Studio Launcher
Launcher that runs without console
"""
import sys
import os
import subprocess
from pathlib import Path

def get_python_executable():
    """Find Python executable path for the portable environment"""
    if getattr(sys, 'frozen', False):
        # Built with PyInstaller
        base_path = Path(sys.executable).parent
    else:
        # Development environment
        base_path = Path(__file__).parent

    # Portable environment Python path
    python_exe = base_path / "python_env" / "python.exe"

    if python_exe.exists():
        return str(python_exe)

    # Try pythonw.exe (no console)
    pythonw_exe = base_path / "python_env" / "pythonw.exe"
    if pythonw_exe.exists():
        return str(pythonw_exe)

    return None

def main():
    # Find Python executable
    python_exe = get_python_executable()

    if not python_exe:
        # Show error message (simple GUI)
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Error",
                "Python environment not found.\n\n"
                "Please check that the python_env folder exists\n"
                "inside the PathologyAIViewer_Portable folder."
            )
        except:
            pass
        sys.exit(1)

    # main.py path
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
                "Error",
                f"main.py not found.\n\nPath: {main_py}"
            )
        except:
            pass
        sys.exit(1)

    # Run Python script (without console)
    # Using pythonw.exe prevents console window from appearing
    subprocess.Popen(
        [python_exe, str(main_py)],
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
        close_fds=True
    )

if __name__ == "__main__":
    main()
