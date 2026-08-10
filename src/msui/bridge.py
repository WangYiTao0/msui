"""桥层通用件：串行化器（忙碌信封）、前端日志口、进度百分比纯函数。

背景是 pywebview 的 js_api：每次前端调用各占一个后台线程（官方文档明说
not thread-safe），用户连点两下就是两个并发调用打进后端。这里只提供
「怎么串行化、怎么应答」的通用机制，不含任何业务语义——消费者按需
实例化 N 把 :class:`Serializer`，各成一条独立的忙碌线。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from threading import Lock
from typing import Any

_log = logging.getLogger(__name__)

BUSY_MESSAGE = "上一个操作还没完成，请稍候再点。"


def busy_reply() -> dict:
    """忙碌中的结构化应答：立即返回、不排队、不抛异常。

    JSON 可序列化，message 是直接给用户看的人话——前端拿到就地显示，
    不需要再翻译错误码。
    """
    return {"busy": True, "message": BUSY_MESSAGE}


def progress_percent(downloaded: int, total: int | None) -> int | None:
    """字节数 → 0-100 的百分比；算不出来（没给总长/总长为 0）就 None。

    None 是前端「退化为不定态动画条」的信号——服务器不给 Content-Length
    时总长未知，这里不编造它没有的数字。上限钳在 100：个别服务器
    Content-Length 报小了，也不至于画出 150% 的条。
    """
    if total is None or total <= 0:
        return None
    return max(0, min(100, round(downloaded * 100 / total)))


class Serializer:
    """一把可实例化的串行化锁：抢不到就**立即**回忙碌信封，绝不排队。

    排队是错的：秒级动作上「连点五下」会变成「排队执行五次」。所以
    `Lock.acquire(blocking=False)`，抢不到的调用当场拿 :func:`busy_reply`。

    应答统一是 JSON 可序列化的信封：
      `{"busy": False, "data": <调用返回值>}` 或 :func:`busy_reply`。

    被包调用抛出的异常**不在这里吞**：锁在 finally 里释放后照常冒泡，
    pywebview 会把它变成 JS 侧 Promise 的 reject，由前端兜底显示。

    需要几条互不影响的忙碌线（比如「业务动作」与「本体自更新」各一条，
    下载工具时照样能点掉更新提示），就建几个实例。
    """

    def __init__(self) -> None:
        self._lock = Lock()

    def run(self, call: Callable[[], Any]) -> dict:
        if not self._lock.acquire(blocking=False):
            return busy_reply()
        try:
            return {"busy": False, "data": call()}
        finally:
            self._lock.release()


class FrontendLog:
    """前端检查点上报口：页面把 boot/ready/JS 错误逐点写进后端日志。

    价值在排障：页面渲染断在 WebView 运行时内部时，Python 侧日志无法
    收窄断点，让页面自己逐点上报才能回答「断到哪一步」。info 级落日志、
    前缀「前端:」——grep 这个前缀就是页面侧的全部时间线。

    三条纪律：

    - **不进任何业务锁**——诊断通道要是被业务锁堵死，最需要日志的那段
      时间恰好没有日志。
    - 每实例限 ``max_lines`` 条（默认 100）：轮询心跳失控不许刷屏。超限
      **静默丢、不抛**——抛出去会变成 JS 侧 promise 的 reject，日志口
      自己成了新故障源。
    - 单条截断 ``max_chars`` 字符（默认 500）：onerror 可能带整段堆栈，
      不许撑爆日志文件。

    计数不上锁：并发多写最坏超限一两条，无害；为精确计数上锁反而给
    日志口引入新的阻塞点。
    """

    def __init__(
        self,
        max_lines: int = 100,
        max_chars: int = 500,
        logger: logging.Logger | None = None,
    ) -> None:
        self._max_lines = max_lines
        self._max_chars = max_chars
        self._logger = logger if logger is not None else _log
        self._count = 0

    def __call__(self, msg: object = "") -> None:
        if self._count >= self._max_lines:
            return
        self._count += 1
        self._logger.info("前端: %s", str(msg)[: self._max_chars])
