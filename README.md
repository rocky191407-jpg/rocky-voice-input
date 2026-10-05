# Rocky Voice Input

独立 Windows 全局语音输入 MVP。按住 CapsLock 说话，松开后本地转录，再输入当前光标位置。不会自动按发送或回车发送消息。无聊天机器人、无付费 STT API、无 Personal AI 项目依赖。

Local, hotkey-driven voice input for Windows. Built with faster-whisper and native Win32 input handling.

维护者：[rocky191407-jpg](https://github.com/rocky191407-jpg) · MIT License

**Alpha / 源码测试版。** 当前主要在一台 Windows NVIDIA 笔记本验证；尚无打包安装程序，也未完成逐应用、跨机器兼容验收。已知首段延迟和其他限制见下文及 [QA.md](QA.md)。

首次使用先看“安装和一键启动”。开发者与后续 AI 请先看 [AGENTS.md](AGENTS.md) 与 [DEVELOPMENT.md](DEVELOPMENT.md)。私人配置和本机交接资料不随仓库发布。

## 立即使用

1. 双击 `start.bat`，等待系统托盘麦克风图标变绿（Idle）。模型加载只在启动/手动重载时进行，加载期间快捷键不被拦截。
2. 将光标放入可编辑输入框。
3. 按住 **CapsLock**，说话，然后松开。
4. 托盘变黄表示转录中，完成后变绿。自行检查文字并发送。

托盘红色：Listening；黄色：Transcribing；蓝色：Loading；紫色：Error；灰色：Paused。它不创建抢焦点的录音窗口。托盘菜单有开始、暂停、设置、重新加载配置和模型、日志、退出。

默认使用 Windows 默认输入设备。双击 `diagnose.bat` 检查选中的麦克风；如果设备不对，在 `config.yaml` 的 `microphone` 指定设备名称，再从托盘重载。不要仅凭设备“能打开”就认为收到了你的声音。

其他操作：

- **Ctrl+Space**：按一次开始录音，再按一次停止；与输入法/编辑器的原快捷键会冲突，可修改或设为 `null`。
- **Ctrl+Alt+V**：输入上次因焦点变化/输入失败而保留的结果。先把光标放回目标，再按下并松开组合键。结果仅保留在内存；退出会丢弃。
- 暂停后快捷键恢复正常，麦克风释放。CapsLock 在程序就绪时被消费，原本的大写开关状态不会切换；暂停/退出后恢复正常。
- 转录忙碌时不接收第二段录音，避免并发粘贴和录音队列积压。

## 配置

直接编辑 `config.yaml`，不需要改 Python。修改后在托盘选择“重新加载配置和模型”。非法配置会显示错误，可修正后再重载。

| 配置项 | 说明 |
|---|---|
| `hotkey` | 单键/组合键，例如 CapsLock、F8、Ctrl+F8、Alt+Space |
| `toggle_hotkey` / `retry_hotkey` | 切换录音/结果重试；可设 null 禁用 |
| `model` | small、medium、large-v3、turbo（large-v3-turbo 别名），也可给本地 CTranslate2 模型目录 |
| `device` | auto 优先 CUDA，或 cuda/cpu |
| `compute_type` | auto 在 GPU 用 float16，在 CPU 用 int8；也支持引擎实际支持的计算类型 |
| `language` | zh、auto、en；默认 zh，以减少短中文句子的语言误判 |
| `initial_prompt` | 简体中文及技术词提示；只是识别提示，不能保证术语拼写 |
| `microphone` | null 用默认麦克风，或输入设备索引/名称查询字符串 |
| `paste_method` | clipboard 或 sendinput |
| `restore_clipboard` | 默认 true；false 会主动留下转录文本，谨慎修改 |
| `paste_wait_ms` | Ctrl+V 后等待时间，默认 350；较慢应用可提高 |
| `save_audio` / `save_transcripts` | 默认 false；开启后保存在本机 AppData |
| `audio_feedback` | 默认 false，可开启系统提示音 |
| `debug_logging` | 默认 false；日志不记录语音文本 |
| `offline` | 示例默认 false，允许首次下载；模型缓存完整后可设 true，离线启动/转录 |
| `download_proxy` | system 沿用当前 Windows HTTP 代理用于模型下载；也可指定 URL 或空字符串 |
| `cpu_fallback` | CUDA 加载/暖机失败时回退 CPU；托盘/状态文件显示真实设备 |
| `max_record_seconds` | 最长 120 秒；超时自动停止，避免无限增长内存 |
| `beam_size` / `vad_filter` | 默认 1/true，偏重延迟；可调整做个人实测 |

查看麦克风索引：双击 `diagnose.bat`。设备索引可能因插拔而改变；名称可附主机 API 区分重复设备，例如 `麦克风阵列 (Realtek(R) Audio), Windows WASAPI`。V1 支持键盘快捷键；鼠标侧键尚未实现。

Windows 默认麦克风每约两秒检查一次。默认设备改变时，在程序内刷新 PortAudio 设备列表并重新打开；发生在录音期间则取消该段并显示错误。指定固定麦克风时，设备失效后可点击“开始”重开，或修改设备后重载。该恢复逻辑有自动化检查，尚未进行物理插拔验收。

## 安装和一键启动

1. 安装 Python 3.13 x64，确认 `python` 可运行。此版本是当前实测环境。
2. 下载仓库 ZIP 并解压，或克隆仓库；不要直接在 ZIP 内运行。
3. 双击 `install.bat`。它会在缺少 `config.yaml` 时复制 `config.example.yaml`，创建项目专属 `.venv`、安装固定依赖并下载 turbo。首次下载需要网络及数 GB 可用空间；依网络而定可能需要较长时间。
4. 双击 `start.bat`，等待托盘绿色 Idle 后使用。需要看启动错误时用 `start-console.bat`。

安装脚本默认包含 NVIDIA 运行库，只放入该环境，不安装驱动/CUDA Toolkit、不修改系统 PATH；使用 GPU 仍需要兼容的 NVIDIA 驱动。下载沿用现有 Windows 代理。无 NVIDIA GPU 的机器可按 [开发说明中的 CPU 安装步骤](DEVELOPMENT.md#cpu-安装) 只安装基础依赖，并配置 cpu/int8；较小模型更适合 CPU。全新机器安装流程尚未独立验收。

切换到尚未下载的模型时，先设 `offline: false` 重载，或运行 `.venv\Scripts\python.exe -m app.main --download-model`。完成后设回 true。`requirements-lock.txt` 记录本次全部已安装版本。

## 开机启动

**默认关闭。** 双击 `enable-autostart.bat`，在弹出的明确确认框同意后，添加当前用户的 Windows 登录启动项。无需管理员权限。取消使用 `disable-autostart.bat`。脚本会同步 `auto_start` 配置；仅编辑该布尔值不会擅自修改注册表。

这里是“登录后常驻的桌面程序”，不是 Windows Session 0 服务。全局键盘与桌面输入需要运行在你的交互登录会话。不能在登录界面/UAC 安全桌面语音输入。

## 隐私与剪贴板

**运行数据全部默认放到 `%LOCALAPPDATA%\RockyVoiceInput`**，不放入源码目录。模型缓存和虚拟环境不随源码分发。

- 原始语音默认只留在进程内存，处理后释放；转录历史默认不保存。
- `service.log` 保存设备/模型、耗时和错误类型；`status.json` 保存状态和最近耗时，不含转录文本。
- 麦克风流在 Idle 时保持打开以缩短延迟，音频回调丢弃未按键的音频，不做缓存/转录。Windows 可能持续显示麦克风正在使用；“暂停”会释放麦克风。
- clipboard 模式先保存全部可安全复制的剪贴板格式，粘贴后恢复。图片、文件、句柄或不支持的格式会直接走 SendInput，保留原剪贴板。
- 如果粘贴期间另一个程序/用户复制了新内容，不覆盖这份新剪贴板。暂时无法恢复时，原备份仍在内存中并报错，后续输入/退出会尝试恢复。
- 临时转录使用 Windows 的禁止剪贴板历史/云同步标记；第三方剪贴板工具可能不遵循该标记。需要完全避免剪贴板时选 sendinput。
- 本程序不上传语音和转录。文字输入到 ChatGPT、微信等目标后，目标应用自己的联网/保存行为仍由该应用决定。
- 基准测试合成音频和合成句结果保存在 AppData 的 `test-fixtures/` 与 `benchmark.json`；它们是明确生成的测试资料。

## 验证范围

详见 `QA.md`。已验证 CUDA 实际推理、麦克风短录、原生钩子安装，以及记事本和 VS Code 连续输入/剪贴板/焦点保护。最初识别测试使用本机 Windows SAPI 合成语音；后续用户反馈已实际使用，后台日志也记录了多段录音处理耗时。**这仍不等同于口音/噪声准确率评估或连续10次、逐应用端到端验收。** Chrome 验收受电脑控制工具的浏览器 URL 安全检查阻止，尚未完成。微信、Word、ChatGPT、Claude、Codex 输入框也尚未逐项实测。

手工验收：依次在上述应用中说“帮我检查一下这个 Python API 有没有 bug”，检查准确率、松键后耗时、焦点、原剪贴板，连续 10 次。测试期间不要发送无意消息。先从记事本测试真人录音。

## 兼容性边界

本机用户试用记录出现首段松键后约 8.33 秒才处理完成，后续多数不足一秒。这些是程序完成时间，不是文字首次出现的屏幕计时，也不保证其他硬件表现。首段延迟尚未定位解决。

全局输入不等于任何窗口都必然可用。受保护输入框、游戏、远程桌面、管理员程序和安全桌面可能拒绝输入。Windows UIPI 限制普通程序向更高权限程序注入，默认不要求管理员权限。

焦点保护比较活动窗口及 Win32 输入控件；浏览器同一窗口内 DOM 输入框切换不一定能由 Win32 检测。转录期间请保持光标位置。系统不提供任意应用“已完成粘贴”的统一确认，350ms 是可调等待值；某些应用不接受 Ctrl+V 时，改为 sendinput 再测试。程序不会自动第二次注入，以免产生重复文本。

窗口焦点检查和实际输入之间存在很短的系统竞态，无法对任意第三方窗口给出绝对保证。长文本 SendInput 分块检查焦点；中途焦点变化可能已经输入部分文字，重试前检查内容。

## 方案选择依据

| 方案 | 优势 | 成本/限制 | V1 决策 |
|---|---|---|---|
| faster-whisper | Python 接口直接、模型常驻、CUDA/int8、内置 VAD、PyAV 带解码库 | Windows 需匹配 cuBLAS/cuDNN；精度和延迟仍需个人语音实测 | 采用 |
| whisper.cpp | C/C++、Windows、CPU/GPU 后端、适合二进制分发 | 当前 Python 集成需额外绑定或常驻进程/模型格式转换 | 备选 |
| OpenAI Whisper 本地版 | 官方参考实现、多语言、PyTorch 生态 | 引入 PyTorch 和系统 FFmpeg，当前项目依赖更大 | 不作为 V1 默认 |
| 纯 Python + Win32 | 一个后台进程；原生钩子、SendInput、剪贴板都可实现 | 钩子要独立消息循环，不能在回调跑推理 | 采用 |
| AutoHotkey + Python | 热键和 Windows 脚本能力成熟 | 多一套安装、启动与进程通信；不能直接提高识别准确率 | 当前无需加入 |

不声称三种引擎在中文上有已实测的准确率排名。中文/中英混合主要取决于模型、语言设置、提示、录音和解码参数。zh 模式仍可输出英文技术词；auto 对全英文更灵活，但短句可能误判语言。`initial_prompt` 不做字符串硬替换，不把听错的词强行改成术语。

模型默认 turbo，使用大模型体系中较快的解码器；small 可用于较弱设备，medium/large-v3 可按个人录音比较准确率、显存和延迟。官方长音频基准不等于本机短句交互延迟。

参考一手资料：[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[实际模型别名](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/utils.py)、[whisper.cpp](https://github.com/ggml-org/whisper.cpp)、[Whisper 本地版](https://github.com/openai/whisper)、[sounddevice](https://python-sounddevice.readthedocs.io/)、[SendInput 权限限制](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)、[Windows 剪贴板格式与云标记](https://learn.microsoft.com/en-us/windows/win32/dataxchg/clipboard-formats)。

本项目源码为 MIT。Whisper/faster-whisper/whisper.cpp 项目采用 MIT；随用依赖各自许可证保留。NVIDIA 驱动、cuBLAS、cuDNN 属于免费可用的专有运行库，**GPU 依赖栈并非每一层都是开源**。无需持续付费账号或 API。

## 开发与后续扩展

`app/audio.py` 录音；`devices.py` 默认设备检查；`stt.py` 常驻识别；`hotkeys.py` 全局热键；`inject.py` 的 TextInjector/ClipboardInjector/SendInputInjector；`tray.py` 托盘；`service.py` 状态协调。

`VoiceService.on_transcription(text)` 是未来处理/事件扩展点。当前只返回文本给输入器，不连接 Personal AI、不创建数据库、不运行命令解析器或网络服务。普通 Dictation 与未来明确触发的 Capture 应分别处理。

运行自动化检查：`.venv\Scripts\python.exe -m unittest discover -s tests -v`。诊断：`-m app.main --diagnose`；麦克风短测：`-m app.main --mic-test 2`；文件转录：`-m app.main --transcribe 路径.wav`。`tools/inject_check.py` 是明确选择测试窗口后运行的真实注入诊断，不是后台 API。
