"""运行日志缓冲：Python 侧一行记日志、按「一次运行」分组，页面按序号增量取。

页面那半边是同包落地的 ``runlog.js``（标准标记与用法见 README §3「运行日志区」）。
这里只管数据：

- 记一条：:meth:`RunLog.log`（或 ``info`` / ``warn`` / ``error``），等级固定三档
  ``info`` / ``warn`` / ``error``，页面显示为「信息 / 告警 / 失败」。等级是字段，
  页面不去正文里认字样。
- 一次运行：:meth:`RunLog.start_run` 开始（名称），:meth:`RunLog.end_run` 结束
  （``ok`` / ``error`` / ``stopped`` + 一句结果——这句就是页面组头上的结论，
  页面不从原话里截）。期间记的行带上这次运行的 id；运行之外的行是散行
  （``run`` 为 ``None``）。同一时刻只有一次运行开着：上一次没结束就开始下一次，
  上一次记成 ``stopped``。
- 增量读取：:meth:`RunLog.since` 收上次看到的序号，返回之后的新行、有变化的
  运行和最新序号，形状见该方法。行与运行的变化共用一条序号，运行结束也推进
  序号——只取「上次之后」的页面也收得到组头从「运行中」变成结论。
- 线程安全：一把锁管内存里的状态，后台线程跑业务时照样记。落文件另有一把文件锁，
  在内存锁之外写（拿到文件锁再放内存锁，文件里的先后与序号一致），慢盘不挡取日志。
- 内存有上限：行数超过 ``max_lines`` 丢最旧的；运行条目超过 ``max_runs`` 丢最旧
  的已结束运行。序号从不回退。
- 可选按天落文件：给了 ``log_dir`` 才写，``<log_dir>/<YYYY-MM-DD>.log`` 一天一份；
  一条 = 一行页眉 ``2026-11-18 09:12:05 [失败] 运行名`` + 原话每行缩进四格。人能
  直接读，:func:`read_log_file` 能读回。只写行，不写运行的开始 / 结束。正文里的
  ``\r\n`` / ``\r`` 统一成 ``\n``，运行名里的换行换成空格。写不进（权限、目录是个
  文件……）不抛：内存里追加一条 warn「日志文件写不进：…」，只提示一次。
- :class:`RunLogHandler`：标准 ``logging`` 的 WARNING → warn、ERROR 及以上 → error、
  其余 → info，接进缓冲。
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import threading
from collections import OrderedDict, deque
from collections.abc import Callable
from pathlib import Path

__all__ = [
    "LEVELS",
    "LEVEL_LABELS",
    "RUN_STATUSES",
    "RunLog",
    "RunLogHandler",
    "read_log_file",
]

LEVELS = ("info", "warn", "error")
# 页面与日志文件里显示的字（与包装排产的日志同一套叫法）。
LEVEL_LABELS = {"info": "信息", "warn": "告警", "error": "失败"}
# end_run 收的三种结局；开着的运行是 running（只由 start_run 设）。
RUN_STATUSES = ("ok", "error", "stopped")

_INDENT = "    "
_HEADER_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) \[(.+?)\](?: (.*))?$")
_LEVEL_BY_LABEL = {label: level for level, label in LEVEL_LABELS.items()}


class RunLog:
    """一份运行日志缓冲。一个程序建一个，js_api 的取日志方法里调 :meth:`since`。

    ``clock`` 只给测试注入假时间用；``log_dir`` 不给就只在内存里。
    """

    def __init__(
        self,
        *,
        max_lines: int = 5000,
        max_runs: int = 500,
        log_dir: str | Path | None = None,
        clock: Callable[[], dt.datetime] = dt.datetime.now,
    ) -> None:
        self._lock = threading.Lock()
        self._file_lock = threading.Lock()
        self._file_warned = False
        self._lines: deque[dict] = deque(maxlen=max_lines)
        self._runs: OrderedDict[int, dict] = OrderedDict()  # id → {..., "rev": 最后变化的序号}
        self._max_runs = max_runs
        self._seq = 0
        self._current: int | None = None
        self._clock = clock
        self.log_dir = Path(log_dir) if log_dir is not None else None

    # ---- 记行 ----

    def log(self, level: str, text: str) -> None:
        """记一条。``level`` 只认 ``info`` / ``warn`` / ``error``，别的当场 ValueError。"""
        if level not in LEVELS:
            raise ValueError(f"运行日志的等级只认 {LEVELS}，收到 {level!r}")
        text = _one_newline(str(text))
        self._lock.acquire()
        try:
            now = self._clock()
            run_name = self._runs[self._current]["name"] if self._current is not None else ""
            self._append_line(now, level, text)
            if self.log_dir is None:
                return
            # 先拿文件锁再放内存锁：文件里的先后与序号一致，而写盘时内存锁已经放开
            self._file_lock.acquire()
        finally:
            self._lock.release()
        try:
            error = self._append_file(now, level, run_name, text)
        finally:
            self._file_lock.release()
        if error is not None:
            self._warn_file_once(error)

    def _append_line(self, now: dt.datetime, level: str, text: str) -> None:
        """内存里追加一行（调用方持有内存锁）。"""
        self._seq += 1
        self._lines.append({
            "seq": self._seq,
            "time": now.strftime("%H:%M:%S"),
            "level": level,
            "text": text,
            "run": self._current,
        })

    def _warn_file_once(self, error: OSError) -> None:
        """文件写不进：只在内存里提示一次（不再落文件、不走 logging——Handler 挂在
        根 logger 上时会绕回自己）。"""
        with self._lock:
            if self._file_warned:
                return
            self._file_warned = True
            self._append_line(
                self._clock(), "warn", f"日志文件写不进：{self.log_dir}（{error}）"
            )

    def info(self, text: str) -> None:
        self.log("info", text)

    def warn(self, text: str) -> None:
        self.log("warn", text)

    def error(self, text: str) -> None:
        self.log("error", text)

    # ---- 运行 ----

    def start_run(self, name: str) -> int:
        """开始一次运行，返回它的 id（整数）。上一次还开着就先把它记成 stopped。"""
        with self._lock:
            now = self._clock()
            if self._current is not None:
                self._finish(self._current, "stopped", self._runs[self._current]["result"])
            self._seq += 1
            run_id = self._seq
            self._runs[run_id] = {
                "id": run_id,
                "name": _one_newline(str(name)).replace("\n", " "),
                "start": now.strftime("%H:%M:%S"),
                "status": "running",
                "result": "",
                "rev": self._seq,
            }
            self._current = run_id
            self._trim_runs()
            return run_id

    def end_run(self, status: str, result: str = "") -> None:
        """结束开着的那次运行。``status`` 只认 ``ok`` / ``error`` / ``stopped``；
        ``result`` 是页面组头上的那一句结论。没有开着的运行时 RuntimeError。"""
        if status not in RUN_STATUSES:
            raise ValueError(f"运行的结局只认 {RUN_STATUSES}，收到 {status!r}")
        with self._lock:
            if self._current is None:
                raise RuntimeError("没有开着的运行：end_run 之前要先 start_run")
            self._finish(self._current, status, str(result))

    def _finish(self, run_id: int, status: str, result: str) -> None:
        self._seq += 1
        self._runs[run_id].update(status=status, result=result, rev=self._seq)
        self._current = None

    def _trim_runs(self) -> None:
        while len(self._runs) > self._max_runs:
            oldest = next((rid for rid in self._runs if rid != self._current), None)
            if oldest is None:
                return
            del self._runs[oldest]

    # ---- 增量读取 ----

    def since(self, seq: int = 0) -> dict:
        """序号 ``seq`` 之后的变化（JSON 可序列化，桥直接转发）::

            {
              "lines": [{"seq", "time", "level", "text", "run"}, ...],   # 新行，按先后
              "runs":  [{"id", "name", "start", "status", "result"}, ...],  # 有变化的运行
              "last":  最新序号,                                          # 下次带回来
            }

        ``time`` / ``start`` 是 ``HH:MM:SS``；``run`` 是所属运行的 id，散行为 None；
        ``status`` 是 ``running`` / ``ok`` / ``error`` / ``stopped``。
        """
        seq = int(seq or 0)
        with self._lock:
            lines = [dict(line) for line in self._lines if line["seq"] > seq]
            runs = [
                {k: v for k, v in run.items() if k != "rev"}
                for run in self._runs.values()
                if run["rev"] > seq
            ]
            return {"lines": lines, "runs": runs, "last": self._seq}

    # ---- 落文件 ----

    def log_file_path(self, day: dt.date | None = None) -> Path | None:
        """那一天的日志文件路径（默认今天）；没给 ``log_dir`` 时 None。"""
        if self.log_dir is None:
            return None
        day = day or self._clock().date()
        return self.log_dir / f"{day.isoformat()}.log"

    def _append_file(
        self, now: dt.datetime, level: str, run_name: str, text: str
    ) -> OSError | None:
        """追加一条进当天的文件（调用方持有文件锁）；写不进返回那个 OSError，不抛。"""
        path = self.log_file_path(now.date())
        assert path is not None
        header = f"{now:%Y-%m-%d %H:%M:%S} [{LEVEL_LABELS[level]}]"
        if run_name:
            header += f" {run_name}"
        block = header + "\n" + "".join(f"{_INDENT}{part}\n" for part in text.split("\n"))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # newline=""：写进去的就是 \n，不在 Windows 上被换成 \r\n
            with path.open("a", encoding="utf-8", newline="") as f:
                f.write(block)
        except OSError as error:
            return error
        return None


def read_log_file(path: str | Path) -> list[dict]:
    """把一份日志文件读回来：``[{"date", "time", "level", "run", "text"}, ...]``，按先后。

    ``level`` 还原成 ``info`` / ``warn`` / ``error``；散行的 ``run`` 是空串。
    认不出的行（手改坏了）ValueError，信息里带着那一行。
    """
    entries: list[dict] = []
    # 按 \n 切、不用 splitlines：正文里的 \x0c、\x0b 这类字符不是行尾。
    # newline=""：不让读取把 \r 当行尾翻译掉（写入时已统一成 \n）。
    # 正文里的 \r 写入时已统一成 \n，所以行尾剩下的 \r 只会是 CRLF（Windows 上手改过再存）留下的，去掉。
    with Path(path).open(encoding="utf-8", newline="") as f:
        lines = [line.removesuffix("\r") for line in f.read().split("\n")]
    if lines and lines[-1] == "":
        lines.pop()
    for line in lines:
        match = _HEADER_RE.match(line)
        if match and match[3] in _LEVEL_BY_LABEL:
            entries.append({
                "date": match[1],
                "time": match[2],
                "level": _LEVEL_BY_LABEL[match[3]],
                "run": match[4] or "",
                "text": [],
            })
        elif entries and line.startswith(_INDENT):
            entries[-1]["text"].append(line[len(_INDENT):])
        else:
            raise ValueError(
                f"日志文件 {path} 里有一行认不出来：{line!r}——这份文件只该由程序写。"
            )
    for entry in entries:
        entry["text"] = "\n".join(entry["text"])
    return entries


def _one_newline(text: str) -> str:
    """\r\n 与单独的 \r 统一成 \n。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


class RunLogHandler(logging.Handler):
    """把标准 ``logging`` 接进运行日志：``logger.addHandler(RunLogHandler(runlog))``。

    WARNING → warn，ERROR 及以上 → error，其余 → info。正文是 ``self.format(record)``
    （默认就是消息本身；要带 logger 名之类的自己 ``setFormatter``）。
    """

    def __init__(self, runlog: RunLog, level: int = logging.NOTSET) -> None:
        super().__init__(level)
        self.runlog = runlog

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.levelno >= logging.ERROR:
                level = "error"
            elif record.levelno >= logging.WARNING:
                level = "warn"
            else:
                level = "info"
            self.runlog.log(level, self.format(record))
        except Exception:  # noqa: BLE001 - logging 的约定：交给 handleError，不往业务抛
            self.handleError(record)
