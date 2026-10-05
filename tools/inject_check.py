"""Exercise the real injector ONLY against an explicitly selected local test window.

Never prints clipboard content. This is a manual developer diagnostic, not an IPC server.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Config
from app.inject import create_injector, clipboard_open, snapshot_clipboard
from app.winapi import Focus, user32
import win32process
import win32api
import win32con
import ctypes

parser = argparse.ArgumentParser()
parser.add_argument("--expected-title", required=True)
parser.add_argument("--method", choices=["clipboard", "sendinput"], default="clipboard")
parser.add_argument("--count", type=int, default=1)
parser.add_argument("--text", default="帮我检查一下这个 Python API 有没有 bug。")
args = parser.parse_args()
sys.stdout.reconfigure(encoding="utf-8")
target = Focus.current()
import win32gui
actual_title = win32gui.GetWindowText(target.window)
if args.expected_title not in actual_title:
    raise RuntimeError("当前窗口与指定测试标题不匹配，未输入")
with clipboard_open():
    try:
        before = snapshot_clipboard()
    except ValueError:
        before = None
        sequence_before = __import__("win32clipboard").GetClipboardSequenceNumber()
injector = create_injector(replace(Config.load(), paste_method=args.method))
times = []
for _ in range(min(max(args.count, 1), 10)):
    target.check()
    began = time.perf_counter()
    method = injector.inject(args.text, target)
    times.append(round((time.perf_counter() - began) * 1000, 2))
with clipboard_open():
    if before is not None:
        after = snapshot_clipboard()
        restored = dict(before) == dict(after)
        changed_formats = [fmt for fmt in set(dict(before)) | set(dict(after))
                           if dict(before).get(fmt) != dict(after).get(fmt)]
    else:
        restored = sequence_before == __import__("win32clipboard").GetClipboardSequenceNumber()
print(json.dumps({"method": method, "count": len(times), "latency_ms": times,
                  "clipboard_preserved": restored, "focus_preserved": target == Focus.current(),
                  "changed_format_ids": changed_formats if before is not None else []}, ensure_ascii=False))
if not restored:
    raise RuntimeError("剪贴板发生变化，请检查")
