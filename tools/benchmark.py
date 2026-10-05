"""Resident inference benchmark. Test fixtures only; never records the microphone."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
import json
import time
from dataclasses import replace
from app.config import Config, DATA, prepare_runtime, prepare_network
parser = argparse.ArgumentParser()
parser.add_argument("input")
parser.add_argument("--count", type=int, default=10)
args = parser.parse_args()
sys.stdout.reconfigure(encoding="utf-8")
handles = prepare_runtime()
cfg = Config.load()
prepare_network(cfg)
from app.stt import WhisperEngine
from faster_whisper.audio import decode_audio
import numpy as np
engine = WhisperEngine(cfg)
try:
    engine.load()
    audio = decode_audio(args.input)
    results = []
    for i in range(args.count):
        began = time.perf_counter()
        text = engine.transcribe(audio)
        results.append({"iteration": i + 1, "text": text,
                        "transcription_ms": round((time.perf_counter() - began) * 1000, 2)})
    language_results = []
    for language in ("auto", "zh", "en"):
        engine.cfg = replace(cfg, language=language)
        began = time.perf_counter()
        text = engine.transcribe(audio)
        language_results.append({"language": language, "text": text,
            "transcription_ms": round((time.perf_counter() - began) * 1000, 2)})
    report = {"fixture": "Windows SAPI synthetic Chinese/English mixed speech; NOT live human acceptance",
              "device": engine.device, "compute": engine.compute, "load_seconds": engine.load_seconds,
              "audio_seconds": len(audio) / 16000, "results": results, "languages": language_results,
              "silence_returns_empty": engine.transcribe(np.zeros(16000, np.float32)) == ""}
    (DATA / "benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
finally:
    engine.close()
