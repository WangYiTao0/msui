"""窗口 chrome 深色化的测试。

pywebview/WinForms 的原生标题栏默认是白色，与深色页面内容撞色。`msui.chrome`
负责在 Windows 上把标题栏染成 tokens.css 的 `--win`：

  - Win11（build 22000+）走 `DWMWA_CAPTION_COLOR`(35) 精确染色；
  - 老系统回退 `DWMWA_USE_IMMERSIVE_DARK_MODE`（20 失败再试 19，1809–1903 是 19）；
  - 非 Windows 完全 no-op；DWM 调用失败只降级不崩。

这里不碰真 dwmapi（Mac 上也没有）：`set_attribute` 可注入桩，测的是分支选择、
参数形状（COLORREF 的字节序！）与降级行为。色值经公共 API `caption_color()`
取——测试不自己拼一遍「读 tokens.css 再解析」的表达式，那只是把实现抄一份、
两边一起错也发现不了。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from msui import chrome, resources


# ---------------------------------------------------------------------------
# COLORREF 转换：0x00BBGGRR，红蓝顺序与 CSS 的 #RRGGBB 相反
# ---------------------------------------------------------------------------


def test_colorref_swaps_red_and_blue():
    """COLORREF 是 0x00BBGGRR：纯红要落在低字节，纯蓝落在高字节。

    这一条是防「把 RGB 顺序搞反」的钉子——反了的话标题栏会染成
    色相镜像的错色，而且只有 Windows 真机才看得出来。
    """
    red = "ff0000"
    blue = "0000ff"
    assert chrome.hex_to_colorref(f"#{red}") == 0x0000FF
    assert chrome.hex_to_colorref(f"#{blue}") == 0xFF0000


def test_colorref_of_a_mixed_color_places_every_channel():
    # R=0x12 G=0x34 B=0x56 → 0x00563412
    assert chrome.hex_to_colorref("#123456") == 0x563412


def test_colorref_rejects_malformed_values():
    for bad in ("141417", "#fff", "#gggggg", "", "#1414171"):
        with pytest.raises(ValueError):
            chrome.hex_to_colorref(bad)


# ---------------------------------------------------------------------------
# 色值单一来源：tokens.css 的 --win，Python 侧不许手写第二份
# ---------------------------------------------------------------------------


def test_caption_color_is_the_win_declaration_in_tokens_css():
    """`caption_color()` 的返回值就是 tokens.css 里 `--win:` 声明的那个字面值。

    断言方式故意不复用 `parse_tokens`（那会把实现原样抄进测试）：直接在
    tokens.css 文本里找 `--win: <返回值>;` 这一行，改了 tokens.css 而
    caption_color 没跟走时这里当场红。
    """
    color = chrome.caption_color()
    assert re.fullmatch(r"#[0-9a-f]{6}", color), color
    css_text = resources.tokens_css_path().read_text(encoding="utf-8")
    assert re.search(rf"--win\s*:\s*{re.escape(color)}\s*;", css_text), (
        f"tokens.css 里找不到 --win: {color}; 声明"
    )


def test_chrome_module_has_no_handwritten_hex_colors():
    """chrome.py 里不出现 `#rrggbb`/`#rgb` 字面量——将来改 tokens.css 的
    `--win` 做双主题时，标题栏必须自动跟走，不能有第二份色值可漂移。
    """
    source = Path(chrome.__file__).read_text(encoding="utf-8")
    offenders = re.findall(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b", source)
    assert not offenders, f"chrome.py 里出现了手写色值：{offenders}"


# ---------------------------------------------------------------------------
# 分支选择与降级：全部经注入的 set_attribute 桩验证
# ---------------------------------------------------------------------------


class RecordingSetter:
    """记录每次 DwmSetWindowAttribute 调用；results 按次序给返回值，耗尽后回 0。"""

    def __init__(self, results: list[int] | None = None) -> None:
        self.calls: list[tuple[int, int, int]] = []
        self._results = list(results or [])

    def __call__(self, hwnd: int, attribute: int, value: int) -> int:
        self.calls.append((hwnd, attribute, value))
        return self._results.pop(0) if self._results else 0


def _fake_window(handle: int = 0x1234) -> SimpleNamespace:
    """长得像 pywebview winforms 窗口的最小对象：window.native.Handle.ToInt32()。"""
    return SimpleNamespace(
        native=SimpleNamespace(Handle=SimpleNamespace(ToInt32=lambda: handle))
    )


def test_win11_paints_caption_with_the_win_token():
    """build 22000+ 走 DWMWA_CAPTION_COLOR(35)，值是 caption_color() 的 COLORREF。"""
    setter = RecordingSetter()
    ok = chrome.apply_dark_chrome(
        _fake_window(0xBEEF), platform="win32", build=22621, set_attribute=setter
    )
    assert ok is True
    assert setter.calls == [
        (0xBEEF, chrome.DWMWA_CAPTION_COLOR, chrome.hex_to_colorref(chrome.caption_color()))
    ]


def test_win10_uses_immersive_dark_mode_20():
    """build < 22000 回退 DWMWA_USE_IMMERSIVE_DARK_MODE=20，值 1；成功就不再试 19。"""
    setter = RecordingSetter()
    ok = chrome.apply_dark_chrome(
        _fake_window(), platform="win32", build=19045, set_attribute=setter
    )
    assert ok is True
    assert setter.calls == [(0x1234, chrome.DWMWA_USE_IMMERSIVE_DARK_MODE, 1)]


def test_win10_1809_falls_back_to_attribute_19():
    """1809–1903 上 20 会被拒（返回非 0），要再试老编号 19。"""
    setter = RecordingSetter(results=[1])  # 第一次（attr 20）失败，第二次成功
    ok = chrome.apply_dark_chrome(
        _fake_window(), platform="win32", build=17763, set_attribute=setter
    )
    assert ok is True
    assert setter.calls == [
        (0x1234, chrome.DWMWA_USE_IMMERSIVE_DARK_MODE, 1),
        (0x1234, chrome.DWMWA_USE_IMMERSIVE_DARK_MODE_1809, 1),
    ]


def test_win10_both_attempts_failing_degrades_quietly():
    setter = RecordingSetter(results=[1, 1])
    ok = chrome.apply_dark_chrome(
        _fake_window(), platform="win32", build=17763, set_attribute=setter
    )
    assert ok is False
    assert len(setter.calls) == 2  # 两个编号都试过了，然后安静放弃


def test_win11_dwm_rejection_degrades_quietly():
    """CAPTION_COLOR 被拒（远程桌面等场景）→ 只降级，不崩、不再乱试别的。"""
    setter = RecordingSetter(results=[1])
    ok = chrome.apply_dark_chrome(
        _fake_window(), platform="win32", build=22621, set_attribute=setter
    )
    assert ok is False


def test_dwm_exception_degrades_quietly():
    def exploding(hwnd: int, attribute: int, value: int) -> int:
        raise OSError("dwmapi 不可用")

    ok = chrome.apply_dark_chrome(
        _fake_window(), platform="win32", build=22621, set_attribute=exploding
    )
    assert ok is False


def test_missing_native_handle_degrades_quietly():
    """窗口还没有 native/Handle（时序意外）→ 降级，绝不把开窗炸掉。"""
    ok = chrome.apply_dark_chrome(
        SimpleNamespace(), platform="win32", build=22621, set_attribute=RecordingSetter()
    )
    assert ok is False


def test_non_windows_is_a_noop():
    """Mac/Linux 上一个 DWM 调用都不发生——平台判断收在 chrome 这一处。"""
    setter = RecordingSetter()
    ok = chrome.apply_dark_chrome(
        _fake_window(), platform="darwin", build=99999, set_attribute=setter
    )
    assert ok is False
    assert setter.calls == []


# ---------------------------------------------------------------------------
# 诊断日志级别：路径选择 / colorref / 每次 DWM 调用的属性号与返回码全部 info。
#
# 理由：宿主产品日志通常配 INFO 级，debug 级在用户机器上等于没记——标题栏
# 回退默认外观时，日志必须能直接回答：选了哪条路径？DWM 的返回码是什么？
# ---------------------------------------------------------------------------


class _ListHandler(logging.Handler):
    """直接挂在 chrome 的 logger 上收 record：不走 propagate 链，免得同进程里
    别的测试动过上游 logger 的 propagate 开关后这里漏记。"""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def chrome_log_records():
    logger = logging.getLogger("msui.chrome")
    handler = _ListHandler()
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.DEBUG)
    yield handler.records
    logger.removeHandler(handler)
    logger.setLevel(old_level)


def test_chrome_logger_lives_in_the_msui_namespace():
    """日志器挂 msui 自己的名字空间——宿主应用配自己的日志树时，这个包的
    记录不会悄悄漏到别的树里。"""
    assert chrome._log.name == "msui.chrome"


def test_non_windows_noop_logs_exactly_one_info_line(chrome_log_records):
    """Mac/Linux no-op 只记一行 info：说明白「为什么什么都没做」，但绝不把
    Windows 分支的细节刷进 Mac 开发机的日志。"""
    chrome.apply_dark_chrome(
        _fake_window(), platform="darwin", build=99999, set_attribute=RecordingSetter()
    )

    assert len(chrome_log_records) == 1
    assert chrome_log_records[0].levelno == logging.INFO
    assert "no-op" in chrome_log_records[0].getMessage()


def test_win11_path_logs_attribute_colorref_and_return_code(chrome_log_records):
    """Win11 路径的三件事全在 info 里：路径选择（build 号）、COLORREF 值、
    DwmSetWindowAttribute 的属性号与返回码。"""
    setter = RecordingSetter()
    chrome.apply_dark_chrome(
        _fake_window(), platform="win32", build=22621, set_attribute=setter
    )

    assert all(r.levelno == logging.INFO for r in chrome_log_records)
    text = "\n".join(r.getMessage() for r in chrome_log_records)
    assert "22621" in text  # 路径选择带 build 号
    colorref = chrome.hex_to_colorref(chrome.caption_color())
    assert f"0x{colorref:06x}" in text  # COLORREF 值
    assert f"属性 {chrome.DWMWA_CAPTION_COLOR}" in text
    assert "返回码 0" in text


def test_win10_fallback_logs_both_attempts_with_return_codes(chrome_log_records):
    """1809 上 20 被拒再试 19：两次调用各自的属性号与返回码都要进日志——
    用户机器的日志靠这两行分辨「20 被拒」与「压根没试 19」。"""
    setter = RecordingSetter(results=[1])
    chrome.apply_dark_chrome(
        _fake_window(), platform="win32", build=17763, set_attribute=setter
    )

    text = "\n".join(r.getMessage() for r in chrome_log_records)
    assert f"属性 {chrome.DWMWA_USE_IMMERSIVE_DARK_MODE}" in text
    assert "返回码 1" in text
    assert f"属性 {chrome.DWMWA_USE_IMMERSIVE_DARK_MODE_1809}" in text
    assert "返回码 0" in text


def test_dwm_rejection_is_visible_at_info(chrome_log_records):
    """DWM 拒绝仍只降级，但「被拒」这件事本身要在 info 可见。"""
    setter = RecordingSetter(results=[1])
    ok = chrome.apply_dark_chrome(
        _fake_window(), platform="win32", build=22621, set_attribute=setter
    )

    assert ok is False
    assert any(
        "拒绝" in r.getMessage() and r.levelno == logging.INFO for r in chrome_log_records
    )


def test_dwm_exception_is_visible_at_info(chrome_log_records):
    """异常路径同样是 info：宿主产品日志常配 INFO 级，debug 记了等于没记。"""

    def exploding(hwnd: int, attribute: int, value: int) -> int:
        raise OSError("dwmapi 不可用")

    ok = chrome.apply_dark_chrome(
        _fake_window(), platform="win32", build=22621, set_attribute=exploding
    )

    assert ok is False
    assert any(
        "失败" in r.getMessage() and r.levelno == logging.INFO for r in chrome_log_records
    )


# ---------------------------------------------------------------------------
# 保险带踩空：native 未就绪不是失败，不许刷 INFO+traceback
# ---------------------------------------------------------------------------
#
# 场景：调用方可能在 pywebview 后台线程里补一次重染，那时 winforms 可能还没把
# window.native 填好。before_show 是主路径，保险带踩空属于预期时序，只配
# debug 一行；INFO+traceback 只留给真失败。


@pytest.mark.parametrize(
    "window",
    [
        pytest.param(SimpleNamespace(native=None), id="native 是 None"),
        pytest.param(SimpleNamespace(), id="native 属性还不存在"),
    ],
)
def test_native_not_ready_skips_with_debug_only(window, chrome_log_records):
    """native 未就绪 → 静默降级：返回 False、不碰 DWM、无 INFO 行、无 traceback。"""
    setter = RecordingSetter()
    ok = chrome.apply_dark_chrome(
        window, platform="win32", build=22621, set_attribute=setter
    )

    assert ok is False
    assert setter.calls == []  # 一次 DWM 调用都不该发生
    assert len(chrome_log_records) == 1  # debug 一行说明为什么跳过，仅此而已
    assert chrome_log_records[0].levelno == logging.DEBUG
    assert chrome_log_records[0].exc_info is None
    assert "before_show" in chrome_log_records[0].getMessage()
