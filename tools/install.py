"""Project-local dependency install, using the existing Windows download proxy."""
from pathlib import Path
import os
import subprocess
import sys
import winreg
root = Path(__file__).resolve().parents[1]
os.chdir(root)
try:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
        enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
        proxy = winreg.QueryValueEx(key, "ProxyServer")[0] if enabled else ""
    if proxy and ";" not in proxy and "=" not in proxy:
        proxy = proxy if "://" in proxy else "http://" + proxy
        os.environ.setdefault("HTTPS_PROXY", proxy)
        os.environ.setdefault("HTTP_PROXY", proxy)
except OSError:
    pass
subprocess.run([sys.executable, "-m", "pip", "install", "--timeout", "60",
                "-r", "requirements-gpu.txt"], check=True)
subprocess.run([sys.executable, "-m", "app.main", "--download-model"], check=True)
