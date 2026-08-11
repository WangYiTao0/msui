"""`msui.testing.SmokeDriver`（自动驾驶冒烟骨架）的单元测试。

全部用假 window 对象跑：evaluate_js 回放预设结果、destroy 记录调用——
不开任何真实窗口。骨架的四条承诺各自有测试钉着：

  1. 冒烟脚本抛异常 → 收进 failures（后台线程异常不会自己变成非零退出码）；
  2. 窗口销毁在 finally 里，脚本怎么炸都要销毁；
  3. run() 返回后 exit() 统一判定：有失败打印清单并 SystemExit(1)，
     全绿打印「冒烟通过」正常返回；
  4. watchdog 超时兜底：到点 os._exit(2)，exit() 解除它。
"""
from __future__ import annotations

import os
import time

import pytest

from msui.testing import SmokeDriver


class JavascriptException(Exception):
    """与 pywebview 的 webview.errors.JavascriptException **同名**的本地替身。

    wait_js 按异常类名字符串识别（msui.testing 不 import webview），所以
    测试用同名本地类就能命中匹配分支，不用真装 pywebview。"""


class FakeWindow:
    """假 window：evaluate_js 依次回放 replies（弹到只剩一个就重复它），
    reply 是异常实例时改为抛出它；destroy 记录调用。"""

    def __init__(self, replies: tuple = ()) -> None:
        self.replies = list(replies)
        self.evaluated: list[str] = []
        self.destroyed = False

    def evaluate_js(self, script: str):
        self.evaluated.append(script)
        if not self.replies:
            return None
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply

    def destroy(self) -> None:
        self.destroyed = True


def _noop_script(drive: SmokeDriver, window) -> None:
    pass


# ---------------------------------------------------------------------------
# __call__ 骨架：脚本执行、异常收集、finally destroy
# ---------------------------------------------------------------------------


def test_script_runs_and_window_is_destroyed():
    seen = []
    driver = SmokeDriver(lambda drive, window: seen.append(window))
    window = FakeWindow()

    driver(window)

    assert seen == [window]
    assert window.destroyed
    assert driver.failures == []
    driver.exit()  # 全绿：正常返回、不抛


def test_script_exception_is_collected_and_window_still_destroyed():
    def _boom(drive, window):
        raise RuntimeError("桥没通")

    driver = SmokeDriver(_boom)
    window = FakeWindow()

    driver(window)

    assert window.destroyed, "脚本炸了窗口也必须销毁，否则进程挂死"
    assert len(driver.failures) == 1
    assert "桥没通" in driver.failures[0]
    driver._watchdog.cancel()


# ---------------------------------------------------------------------------
# check / fail
# ---------------------------------------------------------------------------


def test_check_records_failure_only_when_not_ok():
    driver = SmokeDriver(_noop_script)
    assert driver.check(True, "不该出现") is True
    assert driver.failures == []
    assert driver.check(False, "该出现") is False
    assert driver.failures == ["该出现"]
    driver._watchdog.cancel()


# ---------------------------------------------------------------------------
# wait_js：轮询等到位，超时返回最后一次结果
# ---------------------------------------------------------------------------


def test_wait_js_polls_until_expected():
    driver = SmokeDriver(_noop_script, timeout=5)
    window = FakeWindow(replies=("加载中", "加载中", "就绪"))

    got = driver.wait_js(window, "document.title", "就绪", interval=0.01)

    assert got == "就绪"
    assert len(window.evaluated) == 3
    driver._watchdog.cancel()


def test_wait_js_gives_up_at_deadline_and_returns_last_result():
    driver = SmokeDriver(_noop_script, timeout=0.05)
    window = FakeWindow(replies=("永远不对",))

    started = time.monotonic()
    got = driver.wait_js(window, "document.title", "就绪", interval=0.01)

    assert got == "永远不对"
    assert time.monotonic() - started < 2, "超时后必须放弃，不许一直轮询"
    driver._watchdog.cancel()


# ---------------------------------------------------------------------------
# wait_js：JavascriptException 归因——异常文本当结果值返回，不中断整场
# ---------------------------------------------------------------------------


def test_wait_js_returns_javascript_exception_text_as_result():
    """页面探针抛 JavascriptException 时不穿透：异常文本当结果值返回，
    让调用方 check 正常报「实测=<异常文本>」。"""
    driver = SmokeDriver(_noop_script, timeout=0.05)
    boom = JavascriptException("TypeError: null is not an Element")
    window = FakeWindow(replies=(boom,))

    got = driver.wait_js(window, "getComputedStyle(missing)", "24px", interval=0.01)

    assert "JavascriptException" in got, "结果值里要看得出这是异常，不是真实探针读数"
    assert "null is not an Element" in got
    driver._watchdog.cancel()


def test_wait_js_keeps_polling_after_exception_until_expected():
    """异常只是「这一拍没等到」：继续轮询，元素晚些出现照样能等到位。"""
    driver = SmokeDriver(_noop_script, timeout=5)
    boom = JavascriptException("null 探针")
    window = FakeWindow(replies=(boom, boom, "就绪"))

    got = driver.wait_js(window, "document.title", "就绪", interval=0.01)

    assert got == "就绪"
    assert len(window.evaluated) == 3
    driver._watchdog.cancel()


def test_wait_js_reraises_non_javascript_exceptions():
    """只按类名放行 JavascriptException；别的异常（真 bug）照旧穿透，
    由 __call__ 收进 failures 当「冒烟脚本异常」。"""
    driver = SmokeDriver(_noop_script, timeout=0.05)
    window = FakeWindow(replies=(RuntimeError("桥断了"),))

    with pytest.raises(RuntimeError):
        driver.wait_js(window, "document.title", "就绪", interval=0.01)
    driver._watchdog.cancel()


def test_script_continues_past_throwing_probe_and_keeps_remaining_checks():
    """整场归因：抛异常的那条 check 正常记失败，剩余断言照跑不丢。"""
    boom = JavascriptException("TypeError: probe blew up")

    def _script(drive: SmokeDriver, window) -> None:
        got = drive.wait_js(window, "getComputedStyle(missing)", "24px", interval=0.01)
        drive.check(got == "24px", f"padding 实测 {got!r}")
        drive.check(False, "后续断言也执行了")

    driver = SmokeDriver(_script, timeout=0.05)
    window = FakeWindow(replies=(boom,))

    driver(window)

    assert window.destroyed
    assert len(driver.failures) == 2, "抛异常不许中断整场：两条失败都要在"
    assert "probe blew up" in driver.failures[0]
    assert driver.failures[1] == "后续断言也执行了"
    driver._watchdog.cancel()


# ---------------------------------------------------------------------------
# check_token_style：token 解成 rgb 与元素实测 computedStyle 比对
# ---------------------------------------------------------------------------


def test_check_token_style_passes_when_actual_matches_resolved_token():
    driver = SmokeDriver(_noop_script)
    window = FakeWindow(replies=("rgb(219, 2, 29)|rgb(219, 2, 29)",))

    ok = driver.check_token_style(window, "button.primary", "backgroundColor", "brand")

    assert ok is True
    assert driver.failures == []
    driver._watchdog.cancel()


def test_check_token_style_fails_on_mismatch_with_readable_message():
    driver = SmokeDriver(_noop_script)
    window = FakeWindow(replies=("rgb(0, 0, 0)|rgb(219, 2, 29)",))

    ok = driver.check_token_style(window, "button.primary", "backgroundColor", "brand")

    assert ok is False
    assert len(driver.failures) == 1
    message = driver.failures[0]
    assert "button.primary" in message
    assert "brand" in message
    assert "rgb(0, 0, 0)" in message
    driver._watchdog.cancel()


def test_check_token_style_fails_when_element_is_missing():
    driver = SmokeDriver(_noop_script)
    window = FakeWindow(replies=("|missing",))

    ok = driver.check_token_style(window, "#nope", "color", "text")

    assert ok is False
    assert driver.failures and "#nope" in driver.failures[0]
    driver._watchdog.cancel()


def test_check_token_style_js_embeds_selector_property_and_token():
    """探针 JS 必须真的带上入参——防「写死某个选择器」的实现。"""
    driver = SmokeDriver(_noop_script)
    window = FakeWindow(replies=("a|a",))

    driver.check_token_style(window, "output.display", "color", "text-dim")

    js = window.evaluated[-1]
    assert "output.display" in js
    assert "--text-dim" in js
    assert "color" in js
    driver._watchdog.cancel()


# ---------------------------------------------------------------------------
# exit()：统一判定退出码
# ---------------------------------------------------------------------------


def test_exit_prints_all_failures_and_raises_system_exit_1(capsys):
    driver = SmokeDriver(_noop_script)
    driver.fail("第一条")
    driver.fail("第二条")

    with pytest.raises(SystemExit) as excinfo:
        driver.exit()

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "第一条" in out
    assert "第二条" in out


def test_exit_prints_pass_marker_when_green(capsys):
    driver = SmokeDriver(_noop_script)
    driver(FakeWindow())
    driver.exit()
    assert "冒烟通过" in capsys.readouterr().out


def test_exit_fails_when_the_script_never_ran(capsys):
    """`on_ready` 从没被触发过 → 不算通过，退出码 1。

    「没跑」与「跑了全绿」在 failures 上是同一个形状（空清单），骨架必须
    自己分得清，否则任何让 run() 提前返回的情况都会静静地报「冒烟通过」——
    单实例守卫拦下第二实例（票 12）正是这样一条路径，开窗失败、页面根本
    没加载也是。冒烟的价值全在「没验成时看得出来」。
    """
    driver = SmokeDriver(_noop_script)

    with pytest.raises(SystemExit) as excinfo:
        driver.exit()

    assert excinfo.value.code == 1
    assert "冒烟脚本从未跑过" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# watchdog：硬闹钟兜底
# ---------------------------------------------------------------------------


def test_watchdog_fires_os_exit_2_when_process_hangs(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(os, "_exit", lambda code: calls.append(code))

    SmokeDriver(_noop_script, watchdog=0.02)
    time.sleep(0.2)

    assert calls == [2]


def test_exit_disarms_the_watchdog(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(os, "_exit", lambda code: calls.append(code))

    driver = SmokeDriver(_noop_script, watchdog=0.05)
    driver(FakeWindow())
    driver.exit()
    time.sleep(0.2)

    assert calls == []
