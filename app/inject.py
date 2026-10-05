from abc import ABC, abstractmethod
from contextlib import contextmanager
import logging
import struct
import time
import win32clipboard as cb
import win32con
from .winapi import Focus, key, send_inputs, wait_modifiers

log = logging.getLogger(__name__)


@contextmanager
def clipboard_open(timeout=1):
    deadline = time.monotonic() + timeout
    while True:
        try:
            cb.OpenClipboard()
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise RuntimeError("剪贴板被其他程序占用") from None
            time.sleep(0.01)
    try:
        yield
    finally:
        cb.CloseClipboard()


def snapshot_clipboard():
    """Run while open. Abort without mutation if any format cannot round-trip safely."""
    formats = []
    fmt = cb.EnumClipboardFormats(0)
    while fmt:
        formats.append(fmt)
        fmt = cb.EnumClipboardFormats(fmt)
    # Pywin32 exposes these as handles/tuples, not owned, restorable byte buffers.
    unsafe = {win32con.CF_BITMAP, win32con.CF_PALETTE, win32con.CF_METAFILEPICT,
              win32con.CF_ENHMETAFILE, win32con.CF_HDROP, win32con.CF_OWNERDISPLAY}
    if any(f in unsafe or 0x200 <= f <= 0x3FF for f in formats):
        raise ValueError("剪贴板包含无法安全恢复的格式")
    snapshot = []
    for fmt in formats:
        value = cb.GetClipboardData(fmt)
        if not isinstance(value, (str, bytes)):
            raise ValueError("剪贴板格式无法安全恢复")
        snapshot.append((fmt, value))
    return snapshot


def private_clipboard_flags():
    # Tell Windows not to put temporary dictation into clipboard history/cloud sync.
    for name in ("ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory",
                 "CanUploadToCloudClipboard"):
        cb.SetClipboardData(cb.RegisterClipboardFormat(name), struct.pack("<I", 0))


class TextInjector(ABC):
    @abstractmethod
    def inject(self, text, target):
        pass


class SendInputInjector(TextInjector):
    def inject(self, text, target):
        wait_modifiers()
        target.check()
        # UTF-16 units include surrogate pairs for emoji. Chunking avoids input queue overflow.
        raw = text.replace("\r\n", "\n").encode("utf-16-le")
        units = struct.unpack(f"<{len(raw) // 2}H", raw)
        for offset in range(0, len(units), 64):
            target.check()
            events = []
            for unit in units[offset:offset + 64]:
                if unit == 10:
                    events.extend((key(0x0D), key(0x0D, flags=2)))
                else:
                    events.extend((key(scan=unit, flags=4), key(scan=unit, flags=6)))
            send_inputs(events)
            time.sleep(0.005)
        return "sendinput"


class ClipboardInjector(TextInjector):
    def __init__(self, cfg):
        self.cfg = cfg
        self.fallback = SendInputInjector()
        self.pending_restore = None

    def inject(self, text, target):
        if self.pending_restore is not None:
            self.restore_pending()
        wait_modifiers()
        target.check()
        # Capture ALL formats before emptying anything. On unsupported content, use Unicode input.
        mutated = False
        try:
            with clipboard_open():
                snapshot = snapshot_clipboard() if self.cfg.restore_clipboard else []
                target.check()
                cb.EmptyClipboard()
                mutated = True
                self.pending_restore = (snapshot, None) if self.cfg.restore_clipboard else None
                try:
                    private_clipboard_flags()
                    cb.SetClipboardData(win32con.CF_UNICODETEXT, text)
                finally:
                    sequence = cb.GetClipboardSequenceNumber()
                    if self.pending_restore is not None:
                        self.pending_restore = (snapshot, sequence)
        except Exception:
            if mutated:
                self.restore_pending()
                raise
            log.info("Clipboard untouched; using SendInput fallback")
            return self.fallback.inject(text, target)
        try:
            target.check()
            send_inputs([key(0x11), key(0x56), key(0x56, flags=2), key(0x11, flags=2)])
            time.sleep(self.cfg.paste_wait_ms / 1000)
        finally:
            if self.cfg.restore_clipboard:
                self.restore_pending()
        # Ctrl+V dispatch cannot prove an arbitrary app accepted the text: never auto-duplicate it.
        return "clipboard"

    def restore_pending(self):
        if self.pending_restore is None:
            return
        snapshot, sequence = self.pending_restore
        with clipboard_open(timeout=2):
            if sequence is not None and cb.GetClipboardSequenceNumber() != sequence:
                # User/app copied something newer: preserve that new clipboard instead.
                self.pending_restore = None
                return
            cb.EmptyClipboard()
            try:
                for fmt, value in snapshot:
                    cb.SetClipboardData(fmt, value)
            except Exception:
                # Keep backup in memory for a later restore attempt; do not pretend it succeeded.
                self.pending_restore = (snapshot, cb.GetClipboardSequenceNumber())
                raise RuntimeError("剪贴板恢复失败；原内容仍保留在程序内存") from None
            self.pending_restore = None


def create_injector(cfg):
    return ClipboardInjector(cfg) if cfg.paste_method == "clipboard" else SendInputInjector()
