import gc
import logging
import time
import numpy as np
from .config import DATA

log = logging.getLogger(__name__)


class WhisperEngine:
    def __init__(self, cfg):
        self.cfg = cfg
        self.model = None
        self.device = None
        self.compute = None
        self.cuda_available = False
        self.load_seconds = 0
        self.fallback_reason = None

    def load(self):
        from faster_whisper import WhisperModel
        from faster_whisper.utils import download_model
        import ctranslate2
        started = time.perf_counter()
        # Resolve network/cache errors separately; changing device cannot fix a download error.
        from pathlib import Path
        self.model_path = self.cfg.model if Path(self.cfg.model).is_dir() else download_model(
            self.cfg.model, cache_dir=str(DATA / "models"), local_files_only=self.cfg.offline)
        try:
            self.cuda_available = ctranslate2.get_cuda_device_count() > 0
        except Exception:
            self.cuda_available = False
        self.device = ("cuda" if self.cuda_available else "cpu") if self.cfg.device == "auto" else self.cfg.device
        self.compute = self.cfg.compute_type
        if self.compute == "auto":
            self.compute = "float16" if self.device == "cuda" else "int8"
        try:
            self._load_model(WhisperModel)
        except Exception as exc:
            if self.device != "cuda" or not self.cfg.cpu_fallback:
                raise
            self.close()
            self.fallback_reason = type(exc).__name__
            log.warning("CUDA failed (%s), CPU int8 fallback", self.fallback_reason)
            self.device, self.compute = "cpu", "int8"
            self._load_model(WhisperModel)
        self.load_seconds = time.perf_counter() - started
        log.info("model=%s device=%s compute=%s CUDA=%s load=%.3fs",
                 self.cfg.model, self.device, self.compute, self.cuda_available, self.load_seconds)

    def _load_model(self, factory):
        self.model = factory(self.model_path, device=self.device, compute_type=self.compute,
                             download_root=str(DATA / "models"), local_files_only=self.cfg.offline,
                             cpu_threads=4, num_workers=1)
        # Exercise CUDA/cuDNN now; model construction alone does not prove inference works.
        segments, _ = self.model.transcribe(np.zeros(16000, dtype=np.float32),
                                             language="zh", beam_size=1, vad_filter=False)
        list(segments)

    def transcribe(self, audio):
        if len(audio) < int(self.cfg.min_record_seconds * 16000):
            return ""
        if float(np.max(np.abs(audio))) < 0.001:
            return ""
        segments, _ = self.model.transcribe(
            audio, language=None if self.cfg.language == "auto" else self.cfg.language,
            task="transcribe", beam_size=self.cfg.beam_size, vad_filter=self.cfg.vad_filter,
            vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 100},
            initial_prompt=self.cfg.initial_prompt or None, condition_on_previous_text=False,
            temperature=0.0)
        return "".join(segment.text for segment in segments).strip()

    def close(self):
        self.model = None
        gc.collect()
