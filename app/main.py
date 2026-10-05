import argparse
import json
import sys
import time
from .config import Config, DATA, prepare_runtime, prepare_network


def main():
    for output in (sys.stdout, sys.stderr):
        if output is not None and hasattr(output, "reconfigure"):
            output.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Rocky Voice Input — local Windows dictation")
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--warmup", action="store_true")
    parser.add_argument("--download-model", action="store_true")
    parser.add_argument("--transcribe", metavar="AUDIO")
    parser.add_argument("--mic-test", type=float, metavar="SECONDS")
    args = parser.parse_args()
    dll_handles = prepare_runtime()  # Keep these alive until interpreter shutdown.
    cfg = Config.load()
    if args.download_model:
        from dataclasses import replace
        cfg = replace(cfg, offline=False)
    prepare_network(cfg)
    if args.diagnose:
        import sounddevice as sd
        import ctranslate2
        from faster_whisper.utils import available_models
        print(json.dumps({"python": sys.version, "data_directory": str(DATA),
                          "cuda_devices": ctranslate2.get_cuda_device_count(),
                          "models": available_models(), "default_devices": list(sd.default.device),
                          "input_devices": [{**dict(x), "index": i} for i, x in enumerate(sd.query_devices())
                                            if x["max_input_channels"]]}, ensure_ascii=False, indent=2))
    elif args.mic_test:
        from .audio import Recorder
        import numpy as np
        recorder = Recorder(cfg)
        try:
            recorder.open()
            at = time.perf_counter()
            started = recorder.begin()
            time.sleep(max(0.1, min(args.mic_test, 30)))
            audio = recorder.stop()
            print(json.dumps({"device": recorder.device_name, "sample_rate": recorder.rate,
                              "seconds": len(audio) / 16000, "start_ms": (started - at) * 1000,
                              "peak": float(np.max(np.abs(audio))) if len(audio) else 0,
                              "rms": float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0,
                              "first_sample_ms": recorder.first_sample_ms,
                              "overflow": recorder.overflow}, ensure_ascii=False))
        finally:
            recorder.close()
    elif args.warmup or args.download_model or args.transcribe:
        from .stt import WhisperEngine
        engine = WhisperEngine(cfg)
        try:
            engine.load()
            print(json.dumps({"model": cfg.model, "device": engine.device, "compute": engine.compute,
                              "cuda_available": engine.cuda_available, "load_seconds": engine.load_seconds,
                              "fallback_reason": engine.fallback_reason}))
            if args.transcribe:
                from faster_whisper.audio import decode_audio
                audio = decode_audio(args.transcribe)
                began = time.perf_counter()
                text = engine.transcribe(audio)
                print(json.dumps({"text": text, "seconds": len(audio) / 16000,
                                  "transcription_seconds": time.perf_counter() - began}, ensure_ascii=False))
        finally:
            engine.close()
    else:
        from .service import VoiceService, setup_logging
        from .winapi import SingleInstance
        setup_logging(cfg.debug_logging)
        with SingleInstance():
            VoiceService(cfg).run()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # pythonw has no stdout; show actionable startup errors without leaking dictated text.
        message = f"启动失败：{type(exc).__name__}: {exc}"
        if sys.stderr is not None:
            print(message, file=sys.stderr)
        else:
            from ctypes import windll
            windll.user32.MessageBoxW(None, message, "Rocky Voice Input", 0x10)
        sys.exit(1)
