"""Explicit current-user logon registration; no Windows service or admin privileges."""
import argparse
import ctypes
from pathlib import Path
import sys
import winreg
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT

parser = argparse.ArgumentParser()
parser.add_argument("action", choices=["enable", "disable", "status"])
args = parser.parse_args()
key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
name = "RockyVoiceInput"
pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
launcher = ROOT / "launch.py"
sys.stdout.reconfigure(encoding="utf-8")
if args.action == "status":
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            exists = bool(winreg.QueryValueEx(key, name)[0])
    except FileNotFoundError:
        exists = False
    print("已开启" if exists else "未开启")
else:
    verb = "开启" if args.action == "enable" else "关闭"
    answer = ctypes.windll.user32.MessageBoxW(None,
        f"是否{verb} Rocky Voice Input 的登录后自动启动？\n仅修改当前用户的启动项。",
        "Rocky Voice Input", 0x24)
    if answer != 6:
        sys.exit(0)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        if args.action == "enable":
            if not pythonw.is_file():
                raise RuntimeError("请先安装依赖")
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, f'"{pythonw}" "{launcher}"')
        else:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
    # Only change the owned config key; preserve the user's remaining YAML/comments.
    import re
    path = ROOT / "config.yaml"
    text = path.read_text(encoding="utf-8")
    value = "true" if args.action == "enable" else "false"
    text = re.sub(r"(?m)^auto_start:.*$", f"auto_start: {value}", text)
    path.write_text(text, encoding="utf-8")
    print(f"已{verb}")
