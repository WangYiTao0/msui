"""调用桥骨架：串行化器（忙碌信封）、前端日志口、进度百分比纯函数。

这里只有「桥」的通用机制，不含任何业务语义——测试也只用假的可调用对象，
不出现任何具体业务类型。
"""

from __future__ import annotations

import json
import logging
import threading

import pytest

from msui import bridge


class BlockingCall:
    """卡在临界区里的假调用：进入后阻塞，直到测试主动放行。

    用来在测试里制造「锁正被占着」的窗口。
    """

    def __init__(self, result: dict | None = None) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self._result = result if result is not None else {"ok": True}

    def __call__(self) -> dict:
        self.calls += 1
        self.entered.set()
        assert self.release.wait(timeout=5), "测试没放行 BlockingCall"
        return self._result


# ---------------------------------------------------------------------------
# 忙碌信封
# ---------------------------------------------------------------------------


def test_busy_reply_is_a_structured_json_serializable_envelope():
    """忙碌应答是结构化信封：busy=True 且带一句人话，前端拿到直接显示。"""
    reply = bridge.busy_reply()
    assert reply["busy"] is True
    assert isinstance(reply["message"], str)
    assert reply["message"]
    json.dumps(reply)


# ---------------------------------------------------------------------------
# 串行化器：非阻塞 acquire，抢不到立即回忙碌信封（不排队、不抛异常）
# ---------------------------------------------------------------------------


def test_concurrent_calls_only_one_enters_other_gets_busy_reply_immediately():
    """双线程竞争同一把串行化器：只有一个进入临界区，另一个立即拿忙碌信封。"""
    serializer = bridge.Serializer()
    blocking = BlockingCall()
    results: dict[str, dict] = {}

    worker = threading.Thread(target=lambda: results.update(first=serializer.run(blocking)))
    worker.start()
    try:
        assert blocking.entered.wait(timeout=5), "第一个调用没进临界区"
        # 第一个还卡在临界区里，这时候的并发调用必须立即被拒，不排队
        second = serializer.run(lambda: {"ok": False})
        assert second["busy"] is True
        assert second["message"]
        assert blocking.calls == 1  # 临界区只被进入一次
    finally:
        blocking.release.set()
        worker.join(timeout=5)

    assert results["first"] == {"busy": False, "data": {"ok": True}}


def test_serializer_wraps_result_in_data_envelope():
    """成功应答统一是 {"busy": False, "data": <调用返回值>} 信封，可 json.dumps。"""
    serializer = bridge.Serializer()
    reply = serializer.run(lambda: {"items": [1, 2]})
    assert reply == {"busy": False, "data": {"items": [1, 2]}}
    json.dumps(reply)


def test_lock_is_released_after_each_call():
    """串行化不是一次性的：上一个调用结束后，下一个照常进来。"""
    serializer = bridge.Serializer()
    assert serializer.run(lambda: 1)["busy"] is False
    assert serializer.run(lambda: 2)["busy"] is False
    assert serializer.run(lambda: 3)["busy"] is False


def test_lock_is_released_even_when_call_raises():
    """被包的调用抛异常：异常照常冒泡（不在这里吞），锁必须释放。"""
    serializer = bridge.Serializer()

    def explode() -> dict:
        raise RuntimeError("临界区内部炸了")

    with pytest.raises(RuntimeError):
        serializer.run(explode)
    # 锁没被卡死：下一个调用照常
    assert serializer.run(lambda: {"ok": True})["busy"] is False


def test_two_serializers_are_independent_busy_lines():
    """消费者按需建 N 把锁：一把被占着，另一把照常放行（两条独立的忙碌线）。"""
    line_a = bridge.Serializer()
    line_b = bridge.Serializer()
    blocking = BlockingCall()

    worker = threading.Thread(target=lambda: line_a.run(blocking))
    worker.start()
    try:
        assert blocking.entered.wait(timeout=5)
        assert line_a.run(lambda: 1)["busy"] is True  # 自己这条线忙
        assert line_b.run(lambda: 2) == {"busy": False, "data": 2}  # 别的线不受影响
    finally:
        blocking.release.set()
        worker.join(timeout=5)


# ---------------------------------------------------------------------------
# 前端日志口：不进任何业务锁、条数与单条长度上限可配、超限静默丢
# ---------------------------------------------------------------------------


@pytest.fixture
def bridge_log(caplog):
    # 返回 caplog 本体而不是 records 列表：caplog 按测试阶段分桶，
    # setup 阶段拿到的列表收不到 call 阶段的记录。
    caplog.set_level(logging.INFO, logger="msui.bridge")
    return caplog


def test_frontend_log_lands_at_info_with_the_frontend_prefix(bridge_log):
    """检查点落 info 级日志、前缀「前端:」——grep 这个前缀就是页面侧的全部时间线。"""
    log = bridge.FrontendLog()

    log("boot")

    hits = [r for r in bridge_log.records if r.getMessage() == "前端: boot"]
    assert len(hits) == 1
    assert hits[0].levelno == logging.INFO


def test_frontend_log_truncates_to_500_chars_by_default(bridge_log):
    """默认单条截断 500 字符：页面 onerror 可能带整段堆栈，不许撑爆日志文件。"""
    log = bridge.FrontendLog()

    log("x" * 600)

    assert bridge_log.records[0].getMessage() == "前端: " + "x" * 500


def test_frontend_log_caps_at_100_lines_by_default(bridge_log):
    """默认每会话限 100 条：轮询心跳失控不许刷屏。超限静默丢、绝不抛——
    抛出去会变成页面侧 promise 的 reject，日志口自己成了新故障源。
    """
    log = bridge.FrontendLog()

    for i in range(150):
        log(f"msg {i}")

    assert len(bridge_log.records) == 100
    assert bridge_log.records[-1].getMessage() == "前端: msg 99"


def test_frontend_log_limits_are_configurable(bridge_log):
    """条数与单条长度上限都是构造参数，消费者按自己的日志预算配。"""
    log = bridge.FrontendLog(max_lines=3, max_chars=5)

    for i in range(10):
        log(f"abcdefgh {i}")

    assert len(bridge_log.records) == 3
    assert all(r.getMessage() == "前端: abcde" for r in bridge_log.records)


def test_frontend_log_coerces_non_string_payloads(bridge_log):
    """页面侧什么都可能递过来（null / 对象），str() 兜住，不抛。"""
    log = bridge.FrontendLog()

    log(None)
    log({"status": "idle"})

    assert len(bridge_log.records) == 2
    assert bridge_log.records[0].getMessage() == "前端: None"


def test_frontend_log_works_while_business_lock_is_held(bridge_log):
    """不变量：日志口不进任何业务锁。业务锁被占住时，检查点照常落日志——
    诊断通道要是被业务锁堵死，最需要日志的那段时间恰好没有日志。
    """
    serializer = bridge.Serializer()
    log = bridge.FrontendLog()
    blocking = BlockingCall()

    worker = threading.Thread(target=lambda: serializer.run(blocking))
    worker.start()
    try:
        assert blocking.entered.wait(timeout=5), "占锁的调用没进临界区"
        # 此刻业务锁确实被占着（动作口全被拒）……
        assert serializer.run(lambda: 1)["busy"] is True
        # ……而日志口照常工作
        log("忙碌期间的检查点")
        hits = [r for r in bridge_log.records if "忙碌期间的检查点" in r.getMessage()]
        assert len(hits) == 1
    finally:
        blocking.release.set()
        worker.join(timeout=5)


# ---------------------------------------------------------------------------
# 进度百分比纯函数
# ---------------------------------------------------------------------------


def test_progress_percent_is_a_pure_clamped_percentage():
    """纯函数：字节数 → 0-100 或 None（不知道总长就是不定态，不编造数字）。"""
    assert bridge.progress_percent(0, 100) == 0
    assert bridge.progress_percent(50, 200) == 25
    assert bridge.progress_percent(100, 100) == 100
    assert bridge.progress_percent(10, None) is None  # 服务器没给总长 → 不定态
    assert bridge.progress_percent(10, 0) is None  # 总长 0 没法算百分比，同不定态
    assert bridge.progress_percent(300, 200) == 100  # 上限钳住，不出现 150%
