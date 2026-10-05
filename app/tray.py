import pystray
from PIL import Image, ImageDraw
from .config import ROOT, DATA
import os

COLORS = {"Idle": "#4bb87b", "Listening": "#e14f5a", "Transcribing": "#f6b844",
          "Loading": "#5d92d8", "Error": "#d53ed2", "Paused": "#8b9098"}


def icon_image(state):
    image = Image.new("RGBA", (64, 64))
    draw = ImageDraw.Draw(image)
    draw.ellipse((3, 3, 61, 61), fill=COLORS.get(state, "gray"))
    draw.rounded_rectangle((25, 13, 39, 37), radius=7, fill="white")
    draw.arc((19, 22, 45, 46), 0, 180, fill="white", width=3)
    draw.line((32, 45, 32, 53), fill="white", width=3)
    draw.line((24, 53, 40, 53), fill="white", width=3)
    return image


class Tray:
    def __init__(self, service):
        self.service = service
        self.icon = pystray.Icon("RockyVoiceInput", icon_image("Loading"), "Rocky Voice Input — Loading",
            menu=pystray.Menu(
                pystray.MenuItem(lambda item: "状态：" + service.state, lambda: None, enabled=False),
                pystray.MenuItem("开始 / Start", lambda: service.command("resume")),
                pystray.MenuItem("暂停 / Pause", lambda: service.command("pause")),
                pystray.MenuItem("设置 / Settings", lambda: os.startfile(str(ROOT / "config.yaml"))),
                pystray.MenuItem("重新加载配置和模型", lambda: service.command("reload")),
                pystray.MenuItem("打开本机日志", lambda: os.startfile(str(DATA))),
                pystray.MenuItem("开机启动说明", lambda: os.startfile(str(ROOT / "README.md"))),
                pystray.MenuItem("退出 / Exit", lambda: service.command("exit"))))

    def update(self, state, detail=""):
        self.icon.icon = icon_image(state)
        self.icon.title = (f"Rocky Voice Input — {state} {detail}")[:127]
        self.icon.update_menu()

    def run(self):
        self.icon.run(setup=lambda icon: setattr(icon, "visible", True))

    def stop(self):
        self.icon.stop()
