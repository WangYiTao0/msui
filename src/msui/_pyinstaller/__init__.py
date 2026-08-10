"""msui 自带的 PyInstaller hook 目录入口。

PyInstaller 通过 pyproject 里登记的 `pyinstaller40` entry point 找到这里
（<https://pyinstaller.org/en/stable/hooks.html#providing-pyinstaller-hooks-with-your-package>），
于是**下游 spec 一行资源配置都不写**也能收齐本包的静态资产与版本元数据——
资源清单只写在包这一处，不散落到每个消费者的 spec 里。
"""
from __future__ import annotations

from pathlib import Path


def get_hook_dirs() -> list[str]:
    """PyInstaller 要的 hook 目录列表：就是本包目录（里面有 hook-msui.py）。"""
    return [str(Path(__file__).resolve().parent)]
