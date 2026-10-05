"""Typed Win32 calls. Correct pointer sizes are essential on 64-bit Windows."""
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import time

user32 = C.WinDLL("user32", use_last_error=True)
kernel32 = C.WinDLL("kernel32", use_last_error=True)
LRESULT = C.c_ssize_t
ULONG_PTR = C.c_size_t
HOOKPROC = C.WINFUNCTYPE(LRESULT, C.c_int, W.WPARAM, W.LPARAM)


class KBDLLHOOKSTRUCT(C.Structure):
    _fields_ = [("vkCode", W.DWORD), ("scanCode", W.DWORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class GUITHREADINFO(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("flags", W.DWORD), ("hwndActive", W.HWND),
                ("hwndFocus", W.HWND), ("hwndCapture", W.HWND), ("hwndMenuOwner", W.HWND),
                ("hwndMoveSize", W.HWND), ("hwndCaret", W.HWND), ("rcCaret", W.RECT)]


class KEYBDINPUT(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(C.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD),
                ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class INPUTUNION(C.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", W.DWORD), ("u", INPUTUNION)]


def signature(lib, name, result, *args):
    f = getattr(lib, name)
    f.restype, f.argtypes = result, args
    return f


signature(user32, "GetForegroundWindow", W.HWND)
signature(user32, "GetWindowThreadProcessId", W.DWORD, W.HWND, C.POINTER(W.DWORD))
signature(user32, "GetGUIThreadInfo", W.BOOL, W.DWORD, C.POINTER(GUITHREADINFO))
signature(user32, "SendInput", W.UINT, W.UINT, C.POINTER(INPUT), C.c_int)
signature(user32, "GetAsyncKeyState", C.c_short, C.c_int)
signature(user32, "GetKeyState", C.c_short, C.c_int)
signature(user32, "SetWindowsHookExW", W.HANDLE, C.c_int, HOOKPROC, W.HINSTANCE, W.DWORD)
signature(user32, "CallNextHookEx", LRESULT, W.HANDLE, C.c_int, W.WPARAM, W.LPARAM)
signature(user32, "UnhookWindowsHookEx", W.BOOL, W.HANDLE)
signature(user32, "GetMessageW", C.c_int, C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT)
signature(user32, "PeekMessageW", W.BOOL, C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT)
signature(user32, "PostThreadMessageW", W.BOOL, W.DWORD, W.UINT, W.WPARAM, W.LPARAM)
signature(kernel32, "GetModuleHandleW", W.HMODULE, W.LPCWSTR)
signature(kernel32, "GetCurrentThreadId", W.DWORD)
signature(kernel32, "CreateMutexW", W.HANDLE, C.c_void_p, W.BOOL, W.LPCWSTR)
signature(kernel32, "CloseHandle", W.BOOL, W.HANDLE)


@dataclass(frozen=True)
class Focus:
    window: int
    control: int

    @classmethod
    def current(cls):
        window = user32.GetForegroundWindow()
        if not window:
            raise RuntimeError("没有活动输入窗口")
        tid = user32.GetWindowThreadProcessId(window, None)
        info = GUITHREADINFO(cbSize=C.sizeof(GUITHREADINFO))
        if not user32.GetGUIThreadInfo(tid, C.byref(info)):
            raise C.WinError(C.get_last_error())
        return cls(int(window), int(info.hwndFocus or 0))

    def check(self):
        if self != self.current():
            raise RuntimeError("输入焦点已变化；结果保留在内存，可按重试键输入")


def key(vk=0, scan=0, flags=0):
    return INPUT(type=1, ki=KEYBDINPUT(vk, scan, flags, 0, 0))


def send_inputs(events):
    array = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(array), array, C.sizeof(INPUT))
    if sent != len(array):
        raise RuntimeError("Windows 拒绝或只接受部分输入；请检查目标程序的管理员权限")


def wait_modifiers(timeout=2):
    deadline = time.monotonic() + timeout
    while any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
        if time.monotonic() > deadline:
            raise RuntimeError("请先松开 Ctrl/Alt/Shift/Win，再按重试键")
        time.sleep(0.01)


class SingleInstance:
    def __init__(self, name="Local\\RockyVoiceInput.v1"):
        self.name = name

    def __enter__(self):
        self.handle = kernel32.CreateMutexW(None, False, self.name)
        if not self.handle:
            raise C.WinError(C.get_last_error())
        if C.get_last_error() == 183:
            kernel32.CloseHandle(self.handle)
            raise RuntimeError("Rocky Voice Input 已经运行，请查看系统托盘")
        return self

    def __exit__(self, *args):
        kernel32.CloseHandle(self.handle)
