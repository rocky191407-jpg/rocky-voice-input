# Rocky Voice Input 开发与配置

这是 Windows 全局语音输入 Alpha，使用 Python、faster-whisper 和原生 Win32。源码按 MIT 开源；NVIDIA 驱动和运行库是专有组件。实测范围见 [QA.md](QA.md)，不能把自动化检查当成所有应用都兼容的证明。

## 安装与配置

当前实测 Python 3.13 x64。在项目根目录运行 `install.bat`；脚本复制示例配置、创建独立 `.venv`、安装固定依赖并下载模型。环境创建和首次下载需要网络，源码不包含虚拟环境、GPU DLL 或模型。

`config.example.yaml` 是公开默认配置，`config.yaml` 是本机实际配置，不纳入 Git。修改后从托盘重新加载配置和模型；改 Python 源码需正常退出并重启程序。不要覆盖使用者已有配置。

模型缓存完整后可设 `offline: true`。切换到未缓存的模型，先运行 `.venv\Scripts\python.exe -m app.main --download-model`，该命令临时允许下载；转录本身在本机进行。默认下载代理沿用现有 Windows 简单 HTTP 代理，不修改系统设置，不完整支持 PAC 或复杂分协议代理。

## CPU 安装

在项目根目录使用 PowerShell：

```powershell
python -m venv .venv
if (-not (Test-Path -LiteralPath config.yaml)) {
    Copy-Item -LiteralPath config.example.yaml -Destination config.yaml
}
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

编辑 `config.yaml`，设 `device: cpu`、`compute_type: int8`，按机器性能选择 `model: small` 等模型，然后下载：

```powershell
.\.venv\Scripts\python.exe -m app.main --download-model
```

CPU 速度和准确率需要在目标机器实测；当前公开 QA 的主要推理结果来自 NVIDIA GPU。

## 架构

热键线程捕获焦点并提交事件 → 控制线程开始/停止录音 → 单个工作线程转录 → `on_transcription(text)` → 输入器 → 更新状态与耗时。不要在键盘钩子回调中下载、推理或阻塞粘贴。

| 文件 | 职责 |
|---|---|
| `app/main.py` | 入口、诊断、环境准备、单实例 |
| `app/config.py` | YAML 验证、AppData 路径、私有 DLL 和下载代理 |
| `app/service.py` | 队列、状态、单推理工作线程、错误恢复 |
| `app/audio.py` / `app/devices.py` | 麦克风常驻流、重采样、默认设备变化 |
| `app/stt.py` | 常驻模型、设备选择、CUDA 失败回退 CPU |
| `app/hotkeys.py` / `app/winapi.py` | Win32 钩子、键盘事件、焦点、单实例 |
| `app/inject.py` | 剪贴板与 Unicode SendInput、恢复和焦点保护 |
| `app/tray.py` | 托盘状态和菜单 |
| `tools/startup.py` | 明确确认后设置当前用户登录启动项 |
| `tests/test_core.py` | 快捷键、配置、注入和错误恢复检查 |

`on_transcription` 目前原样返回识别结果，没有连接云端整理、聊天助手或长期数据库。

## 检查命令

在 Windows 项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q app tools launch.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m app.main --diagnose
```

`--mic-test 2` 会临时打开麦克风但不保存音频；`--warmup` 会另加载一份模型，避免在用户录音期间并行执行。`--transcribe AUDIO.wav` 在控制台输出转录文字，仅用于已获允许的测试素材。`tools/inject_check.py` 会对显式指定的测试窗口输入文字，应先确认光标位置。

## 数据与隐私

模型、日志、状态和可选保存数据都放在 `%LOCALAPPDATA%\RockyVoiceInput`。`save_audio` / `save_transcripts` 默认 false；Idle 音频被丢弃，暂停释放麦克风。日志不包含转录原文。

恢复剪贴板前检查是否出现新的复制操作；特殊格式使用 SendInput。Windows 禁止剪贴板历史/云同步标记不能约束所有第三方剪贴板工具。输入目标应用后，该应用自行决定联网与保存行为。

公开提交前检查 `git diff --cached`：不上传私人配置、原始语音、转录、模型、凭据、本机路径或 AI 私人交接材料。

## 已知问题与待办

- 首次实际录音曾出现约 8.33 秒的松键后完成延迟。静音暖机关闭 VAD，正式转录开启 VAD；尚未预热 VAD，但没有证据证明它解释全部延迟。优化前先增加分段计时，验证首次、连续及长时间空闲后的表现。
- 微信、Word、浏览器及其他应用尚未逐项完成真人端到端验收；默认设备物理插拔、登录启动和全新机器安装尚未实际验收。
- Win32 焦点令牌无法完全捕获浏览器同一窗口内 DOM 焦点变化；普通权限输入受 UIPI 限制。
- 粘贴等待默认 350ms，没有任意应用的统一接收确认。不能仅为耗时数字降低等待或自动重复注入。
- PyAV 固定 16.1.0：初始环境的 PyAV 19 与 faster-whisper 1.2.1 的 `metadata_errors` 调用不兼容。不要无故升级已固定依赖。
- 可选文字整理、鼠标侧键、图形配置和打包安装程序尚未实现。
