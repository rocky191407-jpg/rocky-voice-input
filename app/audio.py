import math
import threading
import time
import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly
from .devices import default_input_endpoint


class Recorder:
    def __init__(self, cfg):
        self.cfg = cfg
        self.stream = None
        self.lock = threading.Lock()
        self.chunks = []
        self.recording = False
        self.started = 0
        self.rate = 16000
        self.frames = 0
        self.device_name = ""
        self.overflow = False
        self.open_error = None
        self.device_id = None
        self.first_sample_ms = None
        self.endpoint = None

    def open(self):
        self.close()
        try:
            info = sd.query_devices(self.cfg.microphone, "input")
            self.device_name = info["name"]
            self.device_id = sd.default.device[0] if self.cfg.microphone is None else self.cfg.microphone
            # Try 16k directly; use native rate if WASAPI/hardware rejects it.
            self.rate = 16000
            try:
                sd.check_input_settings(device=self.cfg.microphone, channels=1,
                                        dtype="float32", samplerate=self.rate)
            except sd.PortAudioError:
                self.rate = int(info["default_samplerate"])
            self.stream = sd.InputStream(device=self.cfg.microphone, samplerate=self.rate,
                                         channels=1, dtype="float32", blocksize=0,
                                         latency="low", callback=self._callback)
            self.stream.start()
            if self.cfg.microphone is None:
                self.endpoint = default_input_endpoint()
            self.open_error = None
        except Exception as exc:
            self.close()
            self.open_error = type(exc).__name__
            raise RuntimeError("麦克风无法打开；检查默认输入设备、权限和占用情况") from exc

    def _callback(self, data, frames, timing, status):
        with self.lock:
            if self.recording:
                if self.first_sample_ms is None:
                    self.first_sample_ms = (time.perf_counter() - self.started) * 1000
                self.overflow |= bool(status)
                remaining = int(self.rate * self.cfg.max_record_seconds) - self.frames
                if remaining > 0:
                    chunk = data[:remaining, 0].copy()
                    self.chunks.append(chunk)
                    self.frames += len(chunk)

    def begin(self):
        # Re-query default between recordings, including changes after a device unplug.
        default_changed = self.cfg.microphone is None and sd.default.device[0] != self.device_id
        if self.stream is None or not self.stream.active or default_changed:
            self.open()
        with self.lock:
            self.chunks = []
            self.frames = 0
            self.overflow = False
            self.first_sample_ms = None
            self.started = time.perf_counter()
            self.recording = True
        return self.started

    def refresh_default(self):
        if self.cfg.microphone is not None:
            return False
        endpoint = default_input_endpoint()
        if endpoint == self.endpoint:
            return False
        interrupted = self.recording
        self.close()
        # PortAudio caches its enumeration; refresh only after a real endpoint change.
        # These private calls are confined to the pinned sounddevice version and this process.
        sd._terminate()
        sd._initialize()
        self.endpoint = endpoint
        self.open()
        return interrupted

    def stop(self):
        with self.lock:
            self.recording = False
            chunks, self.chunks = self.chunks, []
        audio = np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)
        if self.rate != 16000 and len(audio):
            divisor = math.gcd(self.rate, 16000)
            audio = resample_poly(audio, 16000 // divisor, self.rate // divisor).astype(np.float32)
        return audio

    def cancel(self):
        with self.lock:
            self.recording = False
            self.chunks = []

    def close(self):
        self.cancel()
        if self.stream is not None:
            try:
                self.stream.close()
            except sd.PortAudioError:
                pass
            self.stream = None
