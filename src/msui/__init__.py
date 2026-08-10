"""msui —— 小程序共享 UI 运行时与样式（pywebview + WebView2）。

本包目前只有骨架与发布链（spec：WangYiTao0/MSToolbox#107 的 T1），
功能代码由后续票迁入。
"""
from __future__ import annotations

import importlib.metadata


def get_version() -> str:
    """从安装元数据报出版本号；单一来源是 pyproject.toml 的 version。

    未安装（源码直接跑、冻结产物缺元数据）时返回带 unknown 标记的兜底值，
    不抛异常，也不冒充一个看起来正常的号。
    """
    try:
        return importlib.metadata.version("msui")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0+unknown"


__version__ = get_version()
