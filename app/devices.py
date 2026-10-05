"""Read the live Windows default endpoint, without changing any system settings."""
import ctypes as C
import uuid
from .winapi import signature

ole32 = C.WinDLL("ole32", use_last_error=True)
HRESULT = C.c_long


class GUID(C.Structure):
    _fields_ = [("data", C.c_ubyte * 16)]

    @classmethod
    def parse(cls, value):
        result = cls()
        result.data[:] = uuid.UUID(value).bytes_le
        return result


signature(ole32, "CoInitializeEx", HRESULT, C.c_void_p, C.c_uint)
signature(ole32, "CoUninitialize", None)
signature(ole32, "CoCreateInstance", HRESULT, C.POINTER(GUID), C.c_void_p, C.c_uint,
          C.POINTER(GUID), C.POINTER(C.c_void_p))
signature(ole32, "CoTaskMemFree", None, C.c_void_p)


def method(pointer, slot, result, *arguments):
    table = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p))).contents
    return C.WINFUNCTYPE(result, C.c_void_p, *arguments)(table[slot])


def default_input_endpoint():
    initialized = ole32.CoInitializeEx(None, 0) in (0, 1)
    enumerator, device = C.c_void_p(), C.c_void_p()
    identifier = C.c_void_p()
    try:
        clsid = GUID.parse("BCDE0395-E52F-467C-8E3D-C4579291692E")
        iid = GUID.parse("A95664D2-9614-4F35-A746-DE8DB63617E6")
        if ole32.CoCreateInstance(C.byref(clsid), None, 1, C.byref(iid), C.byref(enumerator)) < 0:
            raise RuntimeError("无法读取 Windows 默认麦克风")
        get_default = method(enumerator, 4, HRESULT, C.c_int, C.c_int, C.POINTER(C.c_void_p))
        if get_default(enumerator, 1, 0, C.byref(device)) < 0:
            return None
        get_id = method(device, 5, HRESULT, C.POINTER(C.c_void_p))
        if get_id(device, C.byref(identifier)) < 0:
            raise RuntimeError("无法读取麦克风标识")
        return C.wstring_at(identifier)
    finally:
        if identifier:
            ole32.CoTaskMemFree(identifier)
        for pointer in (device, enumerator):
            if pointer:
                method(pointer, 2, C.c_ulong)(pointer)
        if initialized:
            ole32.CoUninitialize()
