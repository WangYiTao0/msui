"""pywebview 壳的启动层：建窗、挂钩子、起主循环，业务一概不管。

这一层只做装配，全部输入靠调用方注入：

  - `url`：要加载的页面（调用方自己的 index.html 路径）；
  - `js_api`：调用方组装好的桥对象本身，壳原封不动递给 pywebview；
  - `version`：调用方的版本号字符串，只被陈旧缓存清理消费——本包**不**从
    任何发行版元数据取版本号，宿主是谁、装没装、冻结没冻结都与壳无关；
  - `storage_dir`：显式的持久化目录。**没有默认路径**——共享运行时不许替
    调用方发明数据目录；不传就完全不定制存储，也不做清理。

窗口几何（宽/高/最小尺寸）与标题全是带默认值的关键字参数，默认标题是包名
这种中性占位——品牌由调用方自己传。

`import webview` 放在 `run()` 函数体内：没装 pywebview 的环境 import 本模块
照常成功，只有真要开窗时才炸出「缺 pywebview」。
"""
from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from pathlib import Path

from msui.chrome import apply_dark_chrome

__all__ = [
    "purge_stale_webview_storage",
    "run",
]

# 日志走 "msui.shell"：挂本包自己的名字空间，宿主应用配自己的日志树时经
# propagate 决定收不收，本包不往任何宿主的树里挂。
_log = logging.getLogger(__name__)


def purge_stale_webview_storage(storage: Path, version: str) -> bool:
    """按版本戳清理陈旧的 webview 缓存目录。

    为什么在 Python 侧做：WebView2 以 URL 为键缓存页面，裸文件路径的 URL 在
    版本之间不变，更新后老页面会被继续端出来；而在 URL 上拼版本查询串的写法
    在 Windows/WebView2 上会被 .NET 的 Uri 并进文件名去找文件，报
    ERR_FILE_NOT_FOUND 整页白屏（Mac WKWebView 兼容，开发机上验不出来）。
    所以缓存职责整个收在这里：storage 目录里放一枚版本戳文件，戳跟当前版本
    对不上就把 storage 整个推倒重建。

    行为：
      - 戳存在且内容 == version → 什么都不动，返回 False；
      - 否则（戳缺失/版本不同，含首次开窗的「无戳」态）→
        rmtree(storage)（目录本来就不存在也不算错）→ 重新建目录 →
        写入新戳 → info 日志「webview 缓存已随版本更换清理」→ 返回 True。

    rmtree 只碰得到 storage 这一棵子树：调用方放在旁边的数据文件
    （收藏、设置……）必须原封不动，有测试盯着。

    读戳、rmtree、写戳，任一步失败（权限、文件被占用……）一律 debug 降级、
    绝不让异常冒泡——这是启动前的非核心清理动作，宁可残留一份旧缓存，也不能
    因为它把整个开窗流程炸崩。
    """
    stamp = storage / "page-version.txt"
    try:
        if stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == version:
            return False
    except OSError:
        _log.debug("读 webview 版本戳失败，按「戳不匹配」处理", exc_info=True)

    try:
        if storage.exists():
            shutil.rmtree(storage)
        storage.mkdir(parents=True, exist_ok=True)
        stamp.write_text(version, encoding="utf-8")
    except OSError:
        _log.debug("webview 缓存清理失败，降级不崩", exc_info=True)
        return False

    _log.info("webview 缓存已随版本更换清理")
    return True


def run(
    url: str | Path,
    *,
    js_api: object | None = None,
    title: str = "msui",
    width: int = 560,
    height: int = 520,
    min_size: tuple[int, int] = (460, 360),
    icon: str | Path | None = None,
    storage_dir: str | Path | None = None,
    version: str | None = None,
    hidden: bool = False,
    before_start: Callable[..., object] | None = None,
    on_ready: Callable[..., object] | None = None,
) -> None:
    """开一个 pywebview 窗口跑起来，阻塞到窗口关闭。

    **必须在主线程调用**（webview.start 跑 GUI 主循环）。

    `url`：要加载的页面。收 Path 也行，递给 pywebview 时转成字符串。

    `js_api`：调用方组装好的桥对象本身（方法在 pywebview 的后台线程被并发
    调用，串行化/忙碌应答之类的纪律归桥对象自己）。不传就是纯展示页面。

    `title`/`width`/`height`/`min_size`：窗口标题与几何，全是带默认值的
    关键字参数；默认标题是中性占位「msui」，品牌调用方自己传。
    尺寸是**逻辑像素**（pywebview 在 Windows/WebView2 下不吃物理像素）。

    `storage_dir` 与 `version`——持久化与陈旧缓存清理，全靠显式注入：

      - `storage_dir=None`（默认）：不递 `private_mode` / `storage_path`，
        全按 pywebview 自己的默认走；也不做任何清理。
      - `storage_dir` 给了：落 ``webview.start(private_mode=False,
        storage_path=…)``。pywebview 默认 `private_mode=True` 会在**关窗时
        rmtree 整个用户数据目录**（localStorage 统统清掉）；不显式给
        storage_path 则落到所有 pywebview 应用共享的 ``%APPDATA%\\pywebview``。
        两个参数缺一个，「页面数据在版本更新后仍在」就不成立。目录这里先
        建好——建目录是壳的装配活，不留给 pywebview 的实现细节去猜。
      - `version` 也给了：建目录**之前**先按版本戳调
        `purge_stale_webview_storage`（顺序有测试钉着：先建目录 purge 就
        永远看不到「首次开窗」态）。没给 version 就不清理——没有版本可
        比对，「陈旧」无从谈起。

    `icon`：窗口图标文件路径，经 `webview.start(icon=…)` 递进去；不传就递
    None——Windows 上 pywebview 会退回从 exe 资源段提取（冻结产物里就是打包
    时嵌进去的那份）。

    `hidden`：窗口建起来但**不上屏**（`create_window(hidden=True)`），给
    无人值守验证用的缝；默认 False = 可见。注意隐藏模式下 rAF 停摆、CSS
    transition 不推进（macOS/WKWebView 实测），挂在动画终态上的断言不能指望它。

    `before_start(window)`：窗口**已建、主循环未起**那个空档里的钩子，在
    **主线程**上同步调用。必须先于循环存在的东西（比如托盘）挂这里：早于
    create_window 没有窗口可交给它，晚于 `webview.start()` 则根本轮不到——
    那一句进去就是主循环、不返回。不传就是纯开窗。

    `on_ready(window)`：窗口起来后在 pywebview 的后台线程里被调用的钩子，
    给自动驾驶/无头驱动用；不传就是纯开窗。
    """
    import webview

    storage: Path | None = Path(storage_dir) if storage_dir is not None else None
    if storage is not None:
        if version is not None:
            purge_stale_webview_storage(storage, version)
        storage.mkdir(parents=True, exist_ok=True)

    window = webview.create_window(
        title,
        str(url),
        js_api=js_api,
        width=width,
        height=height,
        min_size=min_size,
        hidden=hidden,
    )

    # 标题栏深色化：挂在 before_show 上——winforms 在 Form.__init__ 里就创建了
    # Handle，before_show 是 should_lock=True 的同步事件，Show() 之前染好，
    # 白标题栏一帧都不闪。平台判断/降级全在 chrome 模块里，这里不设防：
    # 非 Windows 它自己 no-op，失败它自己记 info 日志。
    # 「before_show 已触发」单独记一行：日志里这行缺席 = winforms 某条路径
    # 压根没触发 before_show——标题栏白的第一个可判据断点。
    def _darken_chrome() -> None:
        _log.info("before_show 已触发")
        apply_dark_chrome(window)

    window.events.before_show += _darken_chrome

    # 窗口已建、主循环未起：必须先于循环存在的钩子挂在这个空档里，理由见
    # docstring。同步调用，就在主线程上。
    if before_start is not None:
        before_start(window)

    start_kwargs: dict = {"icon": str(icon) if icon is not None else None}
    if storage is not None:
        start_kwargs["private_mode"] = False
        start_kwargs["storage_path"] = str(storage)
    if on_ready is None:
        webview.start(**start_kwargs)
    else:
        webview.start(func=on_ready, args=(window,), **start_kwargs)
