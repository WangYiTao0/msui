"""msui 最小消费者：页面归自己，共享样式由 msui 启动时落进来。

三步：定位页面目录 → copy_assets 落共享样式 → run 开窗。
页面要调 Python 时把 js_api 对象递给 run（方法包 Serializer：连点丢弃、
不排队），页面那半边的写法见 pages/index.html 尾部的 <script>。
环境变量 APP_SMOKE=1 时隐藏开窗、SmokeDriver 自动驾驶一轮（等桥往返、
核对样式真的生效）后自关——给 CI/无人值守冒烟用；自己的仓不需要冒烟的话，
把 smoke_script 和 driver 相关几行删掉即可。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from msui.bridge import Serializer
from msui.resources import copy_assets
from msui.shell import run
from msui.testing import SmokeDriver


class Api:
    """js_api 桥对象：业务留在 Python，页面只管调用与显示。

    pywebview 对每次前端调用各开一个后台线程（官方文档明说 not
    thread-safe），方法一律包在 Serializer 里：抢不到锁立即回
    {"busy": True, ...}，绝不排队——连点五下不会攒成一队。
    """

    def __init__(self) -> None:
        self._serial = Serializer()

    def ping(self) -> dict:
        """页面调一次拿一句应答：{"busy": False, "data": "pong 来自 Python"}。"""
        return self._serial.run(lambda: "pong 来自 Python")


def page_dir() -> Path:
    """页面目录：冻结态在 _MEIPASS/pages（app.spec 收进去的），源码态在本文件旁。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "pages"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / "pages"


def smoke_script(drive: SmokeDriver, window) -> None:
    """冒烟脚本（跑在 pywebview 后台线程）：桥往返 + 样式生效各一条断言。

    失败收集、finally 销毁窗口、超时兜底都由 SmokeDriver 骨架代办。
    """
    # 桥通：页面在 pywebviewready 后自动 ping 一次，回显来自 Python 的应答
    got = drive.wait_js(
        window, "document.getElementById('pong').textContent", "pong 来自 Python"
    )
    drive.check(got == "pong 来自 Python", f"桥往返回显不对：{got!r}")
    # 样式吃进去了：主按钮实测背景色 == --brand token 解出的 rgb
    drive.check_token_style(window, "button.primary", "backgroundColor", "brand")


def main() -> None:
    serve_dir = copy_assets(page_dir())  # 每次启动覆盖落样式，页面永远跟着装的这版 msui 走
    driver = SmokeDriver(smoke_script) if os.environ.get("APP_SMOKE") == "1" else None
    run(
        serve_dir / "index.html",
        js_api=Api(),
        title="示例小程序",
        hidden=driver is not None,
        on_ready=driver,
    )
    if driver is not None:
        driver.exit()  # 有失败：逐条打印后退出码 1；全绿：打印「冒烟通过」


if __name__ == "__main__":
    main()
