from dataclasses import dataclass, fields
from pathlib import Path
import os
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "RockyVoiceInput"


@dataclass(frozen=True)
class Config:
    hotkey: str = "CapsLock"
    toggle_hotkey: str | None = "Ctrl+Space"
    retry_hotkey: str | None = "Ctrl+Alt+V"
    model: str = "turbo"
    device: str = "auto"
    compute_type: str = "auto"
    language: str = "zh"
    initial_prompt: str = ""
    microphone: str | int | None = None
    paste_method: str = "clipboard"
    restore_clipboard: bool = True
    paste_wait_ms: int = 350
    auto_start: bool = False
    audio_feedback: bool = False
    debug_logging: bool = False
    save_audio: bool = False
    save_transcripts: bool = False
    max_record_seconds: float = 120
    min_record_seconds: float = 0.25
    beam_size: int = 1
    vad_filter: bool = True
    cpu_fallback: bool = True
    offline: bool = False
    download_proxy: str = "system"

    @classmethod
    def load(cls, path=ROOT / "config.yaml"):
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("配置必须是 YAML 映射")
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"未知配置项：{sorted(unknown)}")
        cfg = cls(**raw)
        for name in ("restore_clipboard", "auto_start", "audio_feedback", "debug_logging",
                     "save_audio", "save_transcripts", "vad_filter", "cpu_fallback", "offline"):
            if type(getattr(cfg, name)) is not bool:
                raise ValueError(f"{name} 必须是 true/false")
        if cfg.device not in {"auto", "cuda", "cpu"}:
            raise ValueError("device 只能是 auto/cuda/cpu")
        if cfg.language not in {"auto", "zh", "en"}:
            raise ValueError("language 只能是 auto/zh/en")
        if cfg.paste_method not in {"clipboard", "sendinput"}:
            raise ValueError("paste_method 只能是 clipboard/sendinput")
        if not isinstance(cfg.model, str) or not cfg.model:
            raise ValueError("model 不能为空")
        if not isinstance(cfg.initial_prompt, str):
            raise ValueError("initial_prompt 必须为文本")
        if not 100 <= cfg.paste_wait_ms <= 5000:
            raise ValueError("paste_wait_ms 必须在 100～5000 内")
        if not 0.1 <= cfg.min_record_seconds < cfg.max_record_seconds <= 600:
            raise ValueError("录音时间配置不合法")
        if type(cfg.beam_size) is not int or not 1 <= cfg.beam_size <= 10:
            raise ValueError("beam_size 必须是 1～10 整数")
        # Validate bindings before changing a running service.
        from .hotkeys import parse_binding
        bindings = [parse_binding(x) for x in (cfg.hotkey, cfg.toggle_hotkey, cfg.retry_hotkey) if x]
        if not cfg.hotkey or len(set(bindings)) != len(bindings):
            raise ValueError("快捷键不能为空或重复")
        return cfg


def prepare_runtime():
    DATA.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(DATA / "models")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    # Windows GPU wheels now include private DLLs: do not change system PATH.
    import site
    handles = []
    directories = []
    for base in site.getsitepackages():
        for directory in (Path(base) / "nvidia").glob("**/bin"):
            handles.append(os.add_dll_directory(str(directory)))
            directories.append(str(directory))
        for directory in (Path(base) / "nvidia").glob("**/lib"):
            if any(directory.glob("*.dll")):
                handles.append(os.add_dll_directory(str(directory)))
                directories.append(str(directory))
    # CTranslate2 also uses native LoadLibrary, which does not use Python's DLL directory list.
    # This PATH belongs only to this process; it does not edit Windows/user environment settings.
    os.environ["PATH"] = os.pathsep.join(directories + [os.environ.get("PATH", "")])
    return handles


def prepare_network(cfg):
    """Use existing Windows HTTP proxy only for dependency/model downloads, never audio."""
    if cfg.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
    else:
        os.environ.pop("HF_HUB_OFFLINE", None)
    if cfg.download_proxy == "system":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
                enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
                server = winreg.QueryValueEx(key, "ProxyServer")[0] if enabled else ""
            if server and ";" not in server and "=" not in server:
                server = server if "://" in server else "http://" + server
                os.environ.setdefault("HTTPS_PROXY", server)
                os.environ.setdefault("HTTP_PROXY", server)
        except OSError:
            pass
    elif cfg.download_proxy:
        os.environ["HTTPS_PROXY"] = cfg.download_proxy
        os.environ["HTTP_PROXY"] = cfg.download_proxy
