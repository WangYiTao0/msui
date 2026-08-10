"""msui 最小消费者：页面归自己，共享样式由 msui 启动时落进来。

三步：定位页面目录 → copy_assets 落共享样式 → run 开窗。
环境变量 APP_SMOKE=1 时隐藏开窗、就绪即关——给 CI/无人值守冒烟用，
自己的仓不需要这条冒烟缝的话，把 smoke 两行删掉即可。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from msui.resources import copy_assets
from msui.shell import run


def page_dir() -> Path:
    """页面目录：冻结态在 _MEIPASS/pages（app.spec 收进去的），源码态在本文件旁。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "pages"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / "pages"


def main() -> None:
    serve_dir = copy_assets(page_dir())  # 每次启动覆盖落样式，页面永远跟着装的这版 msui 走
    smoke = os.environ.get("APP_SMOKE") == "1"
    run(
        serve_dir / "index.html",
        title="示例小程序",
        hidden=smoke,
        on_ready=(lambda window: window.destroy()) if smoke else None,
    )


if __name__ == "__main__":
    main()
