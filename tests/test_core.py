import ctypes
from dataclasses import replace
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import numpy as np
from app.config import Config
from app.hotkeys import KeyState, parse_binding, HotkeyManager
from app.inject import ClipboardInjector, SendInputInjector, snapshot_clipboard
from app.winapi import INPUT, Focus, SingleInstance
from app.audio import Recorder


class HotkeyTests(unittest.TestCase):
    def make(self, **kwargs):
        self.events = []
        state = KeyState(replace(Config(), **kwargs), lambda action, at: self.events.append(action))
        state.enabled = True
        return state

    def test_ptt_repeat_and_release_are_suppressed(self):
        state = self.make()
        for pressed in [True] * 10 + [False]:
            self.assertTrue(state.feed(0x14, pressed))
        self.assertEqual(self.events, ["start", "stop"])

    def test_toggle_two_presses(self):
        state = self.make()
        state.feed(0xA2, True)
        for _ in range(2):
            self.assertTrue(state.feed(0x20, True))
            state.feed(0x20, True)
            self.assertTrue(state.feed(0x20, False))
        state.feed(0xA2, False)
        self.assertEqual(self.events, ["toggle", "toggle"])

    def test_modifier_release_stops_ptt(self):
        state = self.make(hotkey="Ctrl+F8")
        state.feed(0xA2, True)
        self.assertTrue(state.feed(0x77, True))
        self.assertFalse(state.feed(0xA2, False))
        self.assertTrue(state.feed(0x77, False))
        self.assertEqual(self.events, ["start", "stop"])

    def test_paused_does_not_suppress_capslock(self):
        state = self.make()
        state.enabled = False
        self.assertFalse(state.feed(0x14, True))
        self.assertFalse(state.feed(0x14, False))
        self.assertEqual(self.events, [])

    def test_extra_modifiers_do_not_match(self):
        state = self.make()
        state.feed(0xA2, True)
        self.assertFalse(state.feed(0x14, True))

    def test_invalid_keys(self):
        for binding in ("Mouse4", "Ctrl+Ctrl+V", "", "Ctrl", "CapsLock+F8"):
            with self.assertRaises(ValueError):
                parse_binding(binding)

    def test_native_hook_installs_and_releases(self):
        manager = HotkeyManager(Config(), lambda *args: None)
        try:
            manager.start()
            self.assertTrue(manager.hook)
            self.assertTrue(manager.thread.is_alive())
        finally:
            manager.stop()
        self.assertFalse(manager.thread.is_alive())


class ClipboardTests(unittest.TestCase):
    def setUp(self):
        self.data = {13: "original", 49153: b"{\\rtf1 original}"}
        self.sequence = 1
        self.cb = Mock()
        self.cb.GetClipboardSequenceNumber.side_effect = lambda: self.sequence
        self.cb.EnumClipboardFormats.side_effect = self.enum
        self.cb.GetClipboardData.side_effect = lambda fmt: self.data[fmt]
        self.cb.RegisterClipboardFormat.side_effect = lambda name: 50000 + len(name)
        self.cb.EmptyClipboard.side_effect = self.empty
        self.cb.SetClipboardData.side_effect = self.set_data
        self.patcher = patch("app.inject.cb", self.cb)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.target = Mock()

    def enum(self, previous):
        formats = list(self.data)
        if previous == 0:
            return formats[0] if formats else 0
        i = formats.index(previous) + 1
        return formats[i] if i < len(formats) else 0

    def empty(self):
        self.sequence += 1
        self.data = {}

    def set_data(self, fmt, value):
        self.sequence += 1
        self.data[fmt] = value

    @patch("app.inject.wait_modifiers")
    @patch("app.inject.time.sleep")
    @patch("app.inject.send_inputs")
    def test_preserves_all_supported_formats(self, send, sleep, wait):
        old = dict(self.data)
        result = ClipboardInjector(Config()).inject("新文字", self.target)
        self.assertEqual(result, "clipboard")
        self.assertEqual(self.data, old)
        self.assertEqual(send.call_count, 1)

    @patch("app.inject.wait_modifiers")
    @patch("app.inject.time.sleep")
    @patch("app.inject.send_inputs")
    def test_new_clipboard_is_not_overwritten(self, send, sleep, wait):
        def user_copy(_):
            self.empty()
            self.set_data(13, "new copy")
        sleep.side_effect = user_copy
        ClipboardInjector(Config()).inject("新文字", self.target)
        self.assertEqual(self.data, {13: "new copy"})

    @patch("app.inject.wait_modifiers")
    def test_bitmap_falls_back_without_touching_clipboard(self, wait):
        self.data = {2: 123456}
        injector = ClipboardInjector(Config())
        injector.fallback = Mock()
        injector.inject("新文字", self.target)
        self.cb.EmptyClipboard.assert_not_called()
        injector.fallback.inject.assert_called_once()

    @patch("app.inject.wait_modifiers")
    @patch("app.inject.send_inputs", side_effect=RuntimeError("input rejected"))
    def test_injection_failure_still_restores(self, send, wait):
        old = dict(self.data)
        with self.assertRaises(RuntimeError):
            ClipboardInjector(Config()).inject("新文字", self.target)
        self.assertEqual(self.data, old)

    @patch("app.inject.wait_modifiers")
    @patch("app.inject.private_clipboard_flags", side_effect=OSError("failed"))
    def test_clipboard_write_failure_restores(self, flags, wait):
        old = dict(self.data)
        with self.assertRaises(OSError):
            ClipboardInjector(Config()).inject("新文字", self.target)
        self.assertEqual(self.data, old)

    @patch("app.inject.wait_modifiers")
    def test_focus_failure_never_empties(self, wait):
        self.target.check.side_effect = RuntimeError("focus changed")
        with self.assertRaises(RuntimeError):
            ClipboardInjector(Config()).inject("新文字", self.target)
        self.cb.EmptyClipboard.assert_not_called()

    @patch("app.inject.wait_modifiers")
    @patch("app.inject.time.sleep")
    @patch("app.inject.send_inputs")
    def test_empty_clipboard_restores_empty(self, send, sleep, wait):
        self.data = {}
        ClipboardInjector(Config()).inject("新文字", self.target)
        self.assertEqual(self.data, {})


class RuntimeTests(unittest.TestCase):
    @patch("app.service.Tray")
    @patch("app.service.WhisperEngine")
    def test_microphone_failure_keeps_loaded_model(self, engine_factory, tray):
        from app.service import VoiceService
        service = VoiceService(Config())
        service.recorder = Mock()
        service.recorder.open.side_effect = RuntimeError("microphone unavailable")
        try:
            service._load()
            engine_factory.return_value.load.assert_called_once()
            engine_factory.return_value.close.assert_not_called()
            self.assertEqual(service.events.get_nowait()[0], "mic_error")
        finally:
            service.executor.shutdown()

    def test_win32_input_size(self):
        self.assertEqual(ctypes.sizeof(INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    def test_single_instance(self):
        import uuid
        name = "Local\\RockyVoiceInput.test." + str(uuid.uuid4())
        with SingleInstance(name):
            with self.assertRaises(RuntimeError):
                with SingleInstance(name):
                    pass

    def test_focus_mismatch(self):
        with patch.object(Focus, "current", return_value=Focus(4, 5)):
            with self.assertRaises(RuntimeError):
                Focus(4, 6).check()

    @patch("app.inject.wait_modifiers")
    @patch("app.inject.send_inputs")
    def test_unicode_surrogate_pairs(self, send, wait):
        SendInputInjector().inject("中😀", Mock())
        events = send.call_args.args[0]
        self.assertEqual([x.ki.wScan for x in events], [0x4E2D, 0x4E2D, 0xD83D, 0xD83D, 0xDE00, 0xDE00])

    def test_config_rejects_string_boolean_and_duplicate_hotkeys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            for content in ('save_audio: "false"', 'hotkey: Ctrl+Space\ntoggle_hotkey: Ctrl+Space'):
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    Config.load(path)

    def test_audio_cap_and_resampling(self):
        cfg = replace(Config(), max_record_seconds=1)
        recorder = Recorder(cfg)
        recorder.rate = 48000
        recorder.recording = True
        for _ in range(5):
            recorder._callback(np.ones((24000, 1), np.float32), 24000, None, False)
        audio = recorder.stop()
        self.assertEqual(len(audio), 16000)
        self.assertFalse(recorder.recording)
        self.assertEqual(recorder.chunks, [])

    @patch("app.audio.default_input_endpoint", return_value="new-device")
    @patch("app.audio.sd._terminate")
    @patch("app.audio.sd._initialize")
    def test_default_device_switch_cancels_recording_and_refreshes(self, initialize, terminate, endpoint):
        recorder = Recorder(Config())
        recorder.endpoint = "old-device"
        recorder.recording = True
        recorder.chunks = [np.ones(5)]
        recorder.open = Mock()
        self.assertTrue(recorder.refresh_default())
        self.assertFalse(recorder.recording)
        self.assertEqual(recorder.chunks, [])
        terminate.assert_called_once()
        initialize.assert_called_once()
        recorder.open.assert_called_once()

    @patch("app.audio.default_input_endpoint", return_value="same-device")
    @patch("app.audio.sd._terminate")
    def test_unchanged_default_keeps_warm_stream(self, terminate, endpoint):
        recorder = Recorder(Config())
        recorder.endpoint = "same-device"
        self.assertFalse(recorder.refresh_default())
        terminate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
