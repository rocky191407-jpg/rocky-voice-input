from concurrent.futures import ThreadPoolExecutor
import json
import logging
import logging.handlers
import queue
import threading
import time
import wave
import winsound
import numpy as np
from .config import Config, ROOT, DATA, prepare_network
from .audio import Recorder
from .stt import WhisperEngine
from .hotkeys import HotkeyManager
from .inject import create_injector, ClipboardInjector
from .winapi import Focus
from .tray import Tray

log = logging.getLogger(__name__)


def setup_logging(debug=False):
    handler = logging.handlers.RotatingFileHandler(DATA / "service.log", maxBytes=1_000_000,
                                                   backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().setLevel(logging.DEBUG if debug else logging.INFO)
    logging.getLogger().addHandler(handler)
    # Dependencies should not log requests, utterances, or segments even in debug mode.
    for name in ("faster_whisper", "huggingface_hub", "httpx", "httpcore", "filelock"):
        logging.getLogger(name).setLevel(logging.ERROR)


class VoiceService:
    def __init__(self, cfg):
        self.cfg = cfg
        self.events = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper")
        self.recorder = Recorder(cfg)
        self.engine = None
        self.injector = create_injector(cfg)
        self.hotkeys = HotkeyManager(cfg, self._hotkey_event)
        self.state = "Loading"
        self.paused = False
        self.busy = True
        self.closing = False
        self.pending = None
        self.target = None
        self.session = 0
        self.metrics = None
        self.last_device_check = 0
        self.tray = Tray(self)

    def _hotkey_event(self, action, at):
        # Hooks must never perform recording, model inference, paste, or blocking I/O.
        try:
            target = Focus.current() if action in ("start", "toggle", "retry") else None
            self.events.put((action, at, target))
        except Exception:
            self.events.put(("focus_error", at, None))

    def command(self, action):
        self.events.put((action, time.perf_counter(), None))

    def status(self, state, detail=""):
        self.state = state
        self.tray.update(state, detail)
        report = {"state": state, "detail": detail, "model": self.cfg.model,
                  "device": self.engine.device if self.engine else None,
                  "compute_type": self.engine.compute if self.engine else None,
                  "cuda_available": self.engine.cuda_available if self.engine else None,
                  "load_seconds": self.engine.load_seconds if self.engine else None,
                  "microphone": self.recorder.device_name, "metrics": self.metrics,
                  "pending_result": self.pending is not None, "updated_at": time.time()}
        try:
            temp = DATA / "status.tmp"
            temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(DATA / "status.json")
        except OSError:
            log.warning("Status file could not be written")

    def error(self, message, exc=None):
        log.error("%s (%s)", message, type(exc).__name__ if exc else "state")
        self.status("Error", message)

    def run(self):
        self.hotkeys.start()
        self.controller = threading.Thread(target=self._control_loop, name="controller", daemon=True)
        self.controller.start()
        self.executor.submit(self._load)
        try:
            self.tray.run()
        finally:
            self.command("exit")
            self.controller.join(timeout=5)
            # Do not abandon a worker mid-paste, mid-restore, or while recording.
            self.executor.shutdown(wait=True, cancel_futures=True)
            self.recorder.close()
            if isinstance(self.injector, ClipboardInjector):
                self.injector.restore_pending()
            if self.engine:
                self.engine.close()

    def _load(self):
        try:
            if self.engine:
                self.engine.close()
            self.engine = WhisperEngine(self.cfg)
            self.engine.load()
            if not self.closing and not self.paused:
                try:
                    self.recorder.open()
                except Exception as exc:
                    log.error("Microphone unavailable (%s); model stays resident", type(exc).__name__)
                    self.events.put(("mic_error", time.perf_counter(), None))
                    return
            self.events.put(("loaded", time.perf_counter(), None))
        except Exception as exc:
            if self.engine:
                self.engine.close()
            log.error("Load failed (%s)", type(exc).__name__)
            self.events.put(("load_error", time.perf_counter(), None))

    def _control_loop(self):
        while not self.closing:
            try:
                action, at, target = self.events.get(timeout=0.1)
            except queue.Empty:
                if self.recorder.recording and time.perf_counter() - self.recorder.started >= self.cfg.max_record_seconds:
                    self._stop(time.perf_counter())
                if not self.paused and not self.busy and time.monotonic() - self.last_device_check > 2:
                    self.last_device_check = time.monotonic()
                    try:
                        if self.recorder.refresh_default():
                            self.error("默认麦克风已变化，本次录音取消，请重说")
                    except Exception as exc:
                        self.error("默认麦克风暂不可用；检查设备后按开始", exc)
                continue
            try:
                if action == "exit":
                    self.closing = True
                    self.session += 1
                    self.recorder.close()
                    self.hotkeys.stop()
                    self.tray.stop()
                elif action == "loaded":
                    self.busy = False
                    self.hotkeys.state.enabled = not self.paused
                    self.status("Paused" if self.paused else "Idle",
                                f"{self.engine.device} · {self.cfg.hotkey}")
                elif action == "load_error":
                    self.busy = False
                    self.error("加载失败；查看诊断，修正后重新加载")
                elif action == "mic_error":
                    self.busy = False
                    self.hotkeys.state.enabled = not self.paused
                    self.error("模型已就绪，麦克风不可用；检查设备后按开始/录音键")
                elif action == "focus_error":
                    self.error("无法读取当前输入焦点")
                elif action == "pause":
                    self.paused = True
                    self.session += 1
                    self.hotkeys.state.enabled = False
                    self.recorder.close()
                    self.status("Paused")
                elif action == "resume":
                    if not self.busy:
                        if self.engine is None or self.engine.model is None:
                            self._reload()
                        else:
                            self.recorder.open()
                            self.paused = False
                            self.hotkeys.state.enabled = True
                            self.status("Idle")
                elif action == "reload":
                    if self.busy or self.recorder.recording:
                        self.error("请先结束录音/转录，再重新加载")
                    else:
                        self._reload()
                elif action == "start":
                    self._start(at, target)
                elif action == "stop":
                    self._stop(at)
                elif action == "toggle":
                    self._stop(at) if self.recorder.recording else self._start(at, target)
                elif action == "retry" and self.pending and not self.busy and not self.paused:
                    self.busy = True
                    self.executor.submit(self._retry, target, self.session)
                elif action == "done":
                    self.busy = False
                    if self.paused:
                        self.status("Paused")
                    else:
                        self.status("Idle", "无语音" if target == "empty" else "")
                elif action == "transcribe_error":
                    self.busy = False
                    self.error("转录/输入失败；若有结果，按 Ctrl+Alt+V 重试")
            except Exception as exc:
                self.error("操作失败；检查设备或配置后重试", exc)

    def _reload(self):
        cfg = Config.load()
        self.session += 1
        self.recorder.close()
        self.hotkeys.stop()
        if isinstance(self.injector, ClipboardInjector):
            self.injector.restore_pending()
        self.cfg = cfg
        prepare_network(cfg)
        self.recorder = Recorder(cfg)
        self.injector = create_injector(cfg)
        self.hotkeys = HotkeyManager(cfg, self._hotkey_event)
        self.hotkeys.start()
        self.paused = False
        self.busy = True
        self.status("Loading")
        self.executor.submit(self._load)

    def _start(self, at, target):
        if self.paused or self.busy or self.recorder.recording:
            return
        if self.engine is None or self.engine.model is None:
            self.error("模型未就绪，请重新加载")
            return
        self.target = target
        self.start_latency = (self.recorder.begin() - at) * 1000
        log.info("record_start_ms=%.1f", self.start_latency)
        self.status("Listening")
        if self.cfg.audio_feedback:
            winsound.MessageBeep(winsound.MB_OK)

    def _stop(self, at):
        if not self.recorder.recording:
            return
        audio = self.recorder.stop()
        if self.recorder.overflow:
            self.error("录音发生丢帧；请重说或调整麦克风")
            return
        self.busy = True
        self.status("Transcribing")
        self.executor.submit(self._process, audio, self.target, at, self.session, self.start_latency)

    def on_transcription(self, text):
        """Extension point. V1 has no network, Personal AI, MCP, or capture database."""
        return text

    def _process(self, audio, target, released_at, session, start_ms):
        try:
            duration = len(audio) / 16000
            if self.cfg.save_audio:
                directory = DATA / "audio"
                directory.mkdir(exist_ok=True)
                with wave.open(str(directory / f"{time.time_ns()}.wav"), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(16000)
                    output.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
            began = time.perf_counter()
            text = self.engine.transcribe(audio)
            transcribe_ms = (time.perf_counter() - began) * 1000
            if not text:
                self.events.put(("done", time.perf_counter(), "empty"))
                return
            text = self.on_transcription(text)
            self.pending = text
            if self.cfg.save_transcripts:
                with (DATA / "transcripts.jsonl").open("a", encoding="utf-8") as output:
                    output.write(json.dumps({"time": time.time(), "text": text}, ensure_ascii=False) + "\n")
            if self.closing or self.paused or session != self.session:
                self.events.put(("done", time.perf_counter(), None))
                return
            began = time.perf_counter()
            method = self.injector.inject(text, target)
            paste_ms = (time.perf_counter() - began) * 1000
            self.pending = None
            self.metrics = {"audio_seconds": round(duration, 3), "record_start_ms": round(start_ms, 2),
                            "transcription_ms": round(transcribe_ms, 2), "paste_ms": round(paste_ms, 2),
                            "total_after_release_ms": round((time.perf_counter() - released_at) * 1000, 2),
                            "method": method}
            log.info("metrics=%s", json.dumps(self.metrics))
            self.events.put(("done", time.perf_counter(), None))
        except Exception as exc:
            log.error("Transcription/injection failed (%s)", type(exc).__name__)
            self.events.put(("transcribe_error", time.perf_counter(), None))

    def _retry(self, target, session):
        try:
            if not self.closing and not self.paused and session == self.session:
                self.injector.inject(self.pending, target)
                self.pending = None
            self.events.put(("done", time.perf_counter(), None))
        except Exception as exc:
            log.error("Retry failed (%s)", type(exc).__name__)
            self.events.put(("transcribe_error", time.perf_counter(), None))
