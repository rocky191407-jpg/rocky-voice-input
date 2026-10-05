import ctypes as C
from ctypes import wintypes as W
import threading
import time
from .winapi import user32, kernel32, HOOKPROC, KBDLLHOOKSTRUCT

MODIFIERS = {0xA0: 0x10, 0xA1: 0x10, 0xA2: 0x11, 0xA3: 0x11, 0xA4: 0x12, 0xA5: 0x12,
             0x5C: 0x5B}
NAMES = {"capslock": 0x14, "space": 0x20, "ctrl": 0x11, "control": 0x11,
         "alt": 0x12, "shift": 0x10, "win": 0x5B, "windows": 0x5B,
         "scrolllock": 0x91, "pause": 0x13, "insert": 0x2D}
NAMES.update({f"f{i}": 0x6F + i for i in range(1, 25)})


def parse_binding(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("快捷键必须是非空文本")
    parts = [p.strip().lower() for p in value.split("+")]
    try:
        keys = [NAMES[p] if p in NAMES else ord(p.upper()) if len(p) == 1 and p.isascii()
                and p.isalnum() else None for p in parts]
        if None in keys or len(set(keys)) != len(keys):
            raise ValueError
        mods = frozenset(keys[:-1])
        if not mods <= {0x10, 0x11, 0x12, 0x5B} or keys[-1] in {0x10, 0x11, 0x12, 0x5B}:
            raise ValueError
        return mods, keys[-1]
    except (ValueError, KeyError):
        raise ValueError(f"不支持的快捷键：{value}（V1 支持键盘单键/组合键）") from None


class KeyState:
    """Pure state machine: repeat suppression, modifier release, and paired key-up blocking."""
    def __init__(self, cfg, emit):
        self.bindings = [(parse_binding(cfg.hotkey), "ptt")]
        for value, action in ((cfg.toggle_hotkey, "toggle"), (cfg.retry_hotkey, "retry")):
            if value:
                self.bindings.append((parse_binding(value), action))
        self.emit = emit
        self.down = set()
        self.consumed = set()
        self.active_ptt = None
        self.enabled = False

    def feed(self, vk, pressed):
        normalized = MODIFIERS.get(vk, vk)
        repeated = vk in self.down
        if pressed:
            self.down.add(vk)
        else:
            self.down.discard(vk)
        current = {MODIFIERS.get(x, x) for x in self.down}
        swallowed = vk in self.consumed
        if not pressed and self.active_ptt:
            mods, base = self.active_ptt
            if base not in current or not mods <= current:
                self.active_ptt = None
                self.emit("stop", time.perf_counter())
        if not pressed:
            self.consumed.discard(vk)
            return swallowed
        if swallowed:
            return True
        if not self.enabled or repeated:
            return False
        for (mods, base), action in self.bindings:
            held_mods = current & {0x10, 0x11, 0x12, 0x5B}
            if normalized == base and mods == held_mods:
                self.consumed.add(vk)
                if action == "ptt":
                    self.active_ptt = (mods, base)
                    action = "start"
                self.emit(action, time.perf_counter())
                return True
        return False


class HotkeyManager:
    def __init__(self, cfg, emit):
        self.state = KeyState(cfg, emit)
        self.ready = threading.Event()
        self.error = None
        self.thread_id = None
        self.hook = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)
        self.thread.start()
        if not self.ready.wait(3):
            raise RuntimeError("快捷键线程未启动")
        if self.error:
            raise self.error

    def _run(self):
        @HOOKPROC
        def callback(code, message, pointer):
            if code >= 0:
                event = C.cast(pointer, C.POINTER(KBDLLHOOKSTRUCT)).contents
                if not event.flags & 0x10:  # Never trigger ourselves with injected keys.
                    try:
                        if self.state.feed(event.vkCode, message in (0x100, 0x104)):
                            return 1
                    except Exception:
                        self.error = RuntimeError("快捷键回调失败")
            return user32.CallNextHookEx(self.hook, code, message, pointer)
        self.callback = callback
        self.thread_id = kernel32.GetCurrentThreadId()
        msg = W.MSG()
        user32.PeekMessageW(C.byref(msg), None, 0, 0, 0)
        self.hook = user32.SetWindowsHookExW(13, callback, kernel32.GetModuleHandleW(None), 0)
        if not self.hook:
            self.error = C.WinError(C.get_last_error())
        self.ready.set()
        if self.error:
            return
        try:
            while user32.GetMessageW(C.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(C.byref(msg))
                user32.DispatchMessageW(C.byref(msg))
        finally:
            user32.UnhookWindowsHookEx(self.hook)

    def stop(self):
        self.state.enabled = False
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, 0x12, 0, 0)
            self.thread.join(timeout=3)
