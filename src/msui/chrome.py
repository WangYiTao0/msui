"""窗口 chrome 深色化：原生标题栏染成 tokens.css 的 `--win`。

pywebview/WinForms 的原生标题栏默认是白色，与深色页面内容撞色。网页只能管到
客户区，标题栏归 DWM（Desktop Window Manager，Windows 负责画窗口边框/标题栏
的部件），要用 `dwmapi.DwmSetWindowAttribute` 对着 HWND 说话：

  - Win11（build 22000+）：`DWMWA_CAPTION_COLOR`(35) 精确染色，值是 COLORREF；
  - 老系统回退 `DWMWA_USE_IMMERSIVE_DARK_MODE`：正式编号 20，Win10 1809–1903
    时代是未公开的 19 —— 先试 20，被拒再试 19（网上通行做法，微软没文档）。

三条纪律：

  1. **色值单一来源**：染色用的 `--win` 从 tokens.css 解析取
     （`resources.parse_tokens`），本模块不写任何 `#rrggbb` 字面量 ——
     将来 dark/light 双主题改 tokens.css，标题栏自动跟走（有测试盯着）。
  2. **平台判断收在这一处**：非 Windows 直接 no-op；调用方（shell.run）不必
     自己判断平台。ctypes 面经 `set_attribute` 可注入，Mac 上照样测分支。
  3. **失败只降级**：DWM 拒绝（远程桌面、精简系统）或任何异常，只记日志、
     保持默认外观 —— 标题栏白一点绝不能成为开不了窗的理由。诊断日志全部
     **info 级**：宿主产品日志通常配 INFO 级，debug 在用户机器上等于没记，
     标题栏回退默认外观时日志必须答得出「走到了哪一步」。

COLORREF 的字节序是 `0x00BBGGRR`（Windows 老 GDI 约定），与 CSS 的
`#RRGGBB` 红蓝相反 —— 转换收在 `hex_to_colorref` 纯函数里，单测钉死。
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Callable

from msui.resources import parse_tokens, tokens_css_path

__all__ = [
    "DWMWA_CAPTION_COLOR",
    "DWMWA_USE_IMMERSIVE_DARK_MODE",
    "DWMWA_USE_IMMERSIVE_DARK_MODE_1809",
    "WIN11_FIRST_BUILD",
    "apply_dark_chrome",
    "caption_color",
    "hex_to_colorref",
]

_log = logging.getLogger(__name__)

# DwmSetWindowAttribute 的属性编号（dwmapi.h / DWMWINDOWATTRIBUTE）。
DWMWA_USE_IMMERSIVE_DARK_MODE_1809 = 19  # Win10 1809–1903 的未公开编号
DWMWA_USE_IMMERSIVE_DARK_MODE = 20  # Win10 1909+ 的正式编号
DWMWA_CAPTION_COLOR = 35  # Win11 22000+ 才认，COLORREF 精确染色

# Win11 的第一个 build 号：sys.getwindowsversion().build 从这里起认 35 号属性。
WIN11_FIRST_BUILD = 22000

# tokens.css 里标题栏要染的那个变量名（窗口本体底色）。
_WIN_VAR = "win"

# 注入缝的形状：(hwnd, attribute, value) -> HRESULT（0 = S_OK）。
SetAttribute = Callable[[int, int, int], int]


def hex_to_colorref(color: str) -> int:
    """CSS 的 `#RRGGBB` → Windows 的 COLORREF（`0x00BBGGRR`，红蓝互换）。

    纯函数，专门用单测钉住字节序：搞反了标题栏会染成色相镜像的错色，
    而且只有 Windows 真机看得出来 —— 不能靠肉眼验，只能靠这条测试。
    只认带 `#` 前缀的六位形态（tokens.css 的 `--win` 就是这个形态），
    其余一律 ValueError，绝不猜。
    """
    if not color.startswith("#") or len(color) != 7:
        raise ValueError(f"颜色要写成 #rrggbb 六位十六进制，收到的是 {color!r}")
    try:
        red = int(color[1:3], 16)
        green = int(color[3:5], 16)
        blue = int(color[5:7], 16)
    except ValueError as exc:
        raise ValueError(f"颜色要写成 #rrggbb 六位十六进制，收到的是 {color!r}") from exc
    return (blue << 16) | (green << 8) | red


def caption_color() -> str:
    """标题栏要染的色值：tokens.css 解析出的 `--win`，别处没有第二份。"""
    return parse_tokens(tokens_css_path().read_text(encoding="utf-8"))[_WIN_VAR]


def _dwm_set_window_attribute(hwnd: int, attribute: int, value: int) -> int:
    """真家伙：ctypes 直调 dwmapi。只会在 Windows 分支里被走到。

    值统一按 4 字节 DWORD 递（BOOL 与 COLORREF 在这两个属性下都是 4 字节）。
    """
    import ctypes

    data = ctypes.c_uint32(value)
    return int(
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), attribute, ctypes.byref(data), ctypes.sizeof(data)
        )
    )


def apply_dark_chrome(
    window: object,
    *,
    platform: str | None = None,
    build: int | None = None,
    set_attribute: SetAttribute | None = None,
) -> bool:
    """把这扇 pywebview 窗口的原生标题栏染深。成功返回 True，其余一律降级 False。

    挂载时机归调用方：shell.run 把它挂在 `window.events.before_show` 上 ——
    winforms 的 `BrowserForm.__init__` 里就访问了 `self.Handle`（句柄随之创建），
    before_show 又是 `should_lock=True` 的同步事件，在 `Show()` 之前染好，
    白标题栏一帧都不闪（pywebview 6.2.1 源码核对：platforms/winforms.py
    的 create() 先 `events.before_show.set()` 再 `browser.Show()`）。

    platform/build/set_attribute 全部可注入，纯粹为了在 Mac 上测出 Windows
    的分支选择与降级路径；真实运行一个都不传。
    """
    resolved_platform = platform if platform is not None else sys.platform
    if resolved_platform != "win32":
        # 平台判断收在这一处：Mac/Linux 上连 HWND 都不碰。只记一行：
        # 说明白「为什么什么都没做」，但不把 Windows 分支细节刷进 Mac 日志。
        _log.info("标题栏深色化：非 Windows（%s），no-op", resolved_platform)
        return False

    if getattr(window, "native", None) is None:
        # 保险带踩空：调用方可能在 pywebview 后台线程里补一次重染，那时
        # winforms 可能还没把 window.native 填好。这是预期时序不是失败——
        # before_show 是主路径，这里 debug 一行静默返回；INFO+traceback
        # 只留给真失败（下面的 except）。
        _log.debug("窗口 native 未就绪，跳过（before_show 是主路径）")
        return False

    setter = set_attribute if set_attribute is not None else _dwm_set_window_attribute
    try:
        hwnd = int(window.native.Handle.ToInt32())  # type: ignore[attr-defined]
        resolved_build = build if build is not None else sys.getwindowsversion().build
        if resolved_build >= WIN11_FIRST_BUILD:
            colorref = hex_to_colorref(caption_color())
            _log.info(
                "标题栏深色化：Win11 路径（build %d），caption-color COLORREF=0x%06x",
                resolved_build,
                colorref,
            )
            code = setter(hwnd, DWMWA_CAPTION_COLOR, colorref)
            _log.info(
                "DwmSetWindowAttribute（属性 %d）返回码 %d", DWMWA_CAPTION_COLOR, code
            )
            ok = code == 0
        else:
            # 老系统只有「深色开关」，染不了精确色；20 被拒（1809–1903）再试 19。
            _log.info("标题栏深色化：Win10 路径（build %d），immersive 深色开关", resolved_build)
            code = setter(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
            _log.info(
                "DwmSetWindowAttribute（属性 %d）返回码 %d",
                DWMWA_USE_IMMERSIVE_DARK_MODE,
                code,
            )
            ok = code == 0
            if not ok:
                code = setter(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_1809, 1)
                _log.info(
                    "DwmSetWindowAttribute（属性 %d）返回码 %d",
                    DWMWA_USE_IMMERSIVE_DARK_MODE_1809,
                    code,
                )
                ok = code == 0
        if not ok:
            _log.info("标题栏深色化被 DWM 拒绝（HRESULT 非 0），保持默认外观")
        return ok
    except Exception:  # noqa: BLE001 - 装饰性功能，任何失败都不许波及开窗
        _log.info("标题栏深色化失败，保持默认外观", exc_info=True)
        return False
