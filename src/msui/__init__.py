"""msui —— 小程序共享 UI 运行时与样式（pywebview + WebView2）。

模块一览（消费者契约与从零跑起来的步骤见仓库 README）：

  - :mod:`msui.webview2` —— WebView2 运行时检测与静默引导安装；
  - :mod:`msui.resources` —— tokens/base 两份共享样式的定位、解析与
    ``copy_assets``（启动时落进页面目录，头部带版本横幅）；
  - :mod:`msui.shell` —— ``run(...)`` 一行开 pywebview 窗口；
  - :mod:`msui.chrome` —— Windows 原生标题栏按 tokens 染深（run 内部已接）；
  - :mod:`msui.single_instance` —— 单实例守卫（``run(single_instance=id)``
    内部已接：连点图标只开一扇窗）；
  - :mod:`msui.bridge` —— js_api 桥的通用件（串行化、忙碌应答、前端日志）；
  - :mod:`msui.testing` —— 样式闸门函数库（对比度校验、防游离色值扫描）。

包自带 PyInstaller hook：下游 spec 对 msui 的资源与元数据零配置。
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
