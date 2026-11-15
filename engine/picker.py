"""Native folder picker, isolated in a subprocess.

Tk must own the main thread of its process; running it in a separate Python
process is more reliable than trying to create a Tk root inside an HTTP worker
thread. The server only needs the selected path on stdout.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys


class PickerError(RuntimeError):
    pass


def _interpreter() -> str:
    """Prefer pythonw.exe on Windows so the dialog does not drag a console along."""
    exe = sys.executable
    if not exe:
        return exe
    quiet = pathlib.Path(exe).with_name("pythonw.exe")
    if quiet.is_file():
        return str(quiet)
    return exe


def pick_folder(initial: str = "") -> str | None:
    """Open the OS folder dialog. Returns None if cancelled.

    Raises PickerError when the desktop dialog is unavailable, so the UI can say
    that instead of silently doing nothing.
    """
    script = pathlib.Path(__file__).resolve()
    try:
        proc = subprocess.run(
            [_interpreter(), str(script), initial or ""],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PickerError(f"无法启动文件夹选择器：{exc}") from exc
    if proc.returncode == 0:
        value = proc.stdout.strip()
        return value or None
    detail = (proc.stderr or proc.stdout or "").strip()
    raise PickerError(detail or "系统文件夹选择器不可用（可能没有桌面环境）")


def _dialog(initial: str) -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        print(f"tkinter unavailable: {exc}", file=sys.stderr)
        sys.exit(2)
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        path = filedialog.askdirectory(
            initialdir=initial or None,
            mustexist=True,
            title="选择要阅读的项目目录",
        )
        root.destroy()
        return path or ""
    except Exception as exc:
        print(f"folder dialog failed: {exc}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    initial = sys.argv[1] if len(sys.argv) > 1 else ""
    print(_dialog(initial))
