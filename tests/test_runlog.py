"""运行日志缓冲（票 #29）：只经公开接口测——记一条、开始 / 结束一次运行、
增量读取的返回形状、上限丢旧、多线程、logging.Handler、按天落文件能读回。

时间用注入的假时钟，返回里的「时间」才是可断言的字面量。
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import threading

import pytest

from msui.runlog import RunLog, RunLogHandler, read_log_file


class FakeClock:
    """每次取时间往后走一秒，起点 2026-11-18 09:00:00。"""

    def __init__(self, start: dt.datetime = dt.datetime(2026, 11, 18, 9, 0, 0)) -> None:
        self.now = start

    def __call__(self) -> dt.datetime:
        current = self.now
        self.now += dt.timedelta(seconds=1)
        return current


# ---------------------------------------------------------------------------
# 记行与增量读取的形状
# ---------------------------------------------------------------------------


def test_a_logged_line_comes_back_with_seq_time_level_text_and_no_run():
    log = RunLog(clock=FakeClock())
    log.info("程序已启动")

    got = log.since(0)

    assert got == {
        "lines": [
            {"seq": 1, "time": "09:00:00", "level": "info", "text": "程序已启动", "run": None},
        ],
        "runs": [],
        "last": 1,
    }
    json.dumps(got)  # 桥直接转发：必须 JSON 可序列化


def test_three_levels_and_unknown_level_is_rejected():
    log = RunLog(clock=FakeClock())
    log.log("info", "甲")
    log.warn("乙")
    log.error("丙")
    assert [line["level"] for line in log.since(0)["lines"]] == ["info", "warn", "error"]
    with pytest.raises(ValueError):
        log.log("debug", "不认识的等级")


def test_since_returns_only_what_came_after_the_given_seq():
    log = RunLog(clock=FakeClock())
    log.info("一")
    first = log.since(0)
    log.info("二")
    log.info("三")

    later = log.since(first["last"])

    assert [line["text"] for line in later["lines"]] == ["二", "三"]
    assert later["last"] == 3
    assert log.since(later["last"]) == {"lines": [], "runs": [], "last": 3}


# ---------------------------------------------------------------------------
# 运行：开始 / 结束，期间的行挂进这一组
# ---------------------------------------------------------------------------


def test_lines_logged_during_a_run_carry_its_id_and_the_run_is_reported():
    log = RunLog(clock=FakeClock())
    log.info("运行之外的散行")
    run_id = log.start_run("读取数据")
    log.info("读到 6 张表")

    got = log.since(0)

    assert [line["run"] for line in got["lines"]] == [None, run_id]
    assert got["runs"] == [
        {"id": run_id, "name": "读取数据", "start": "09:00:01", "status": "running", "result": ""},
    ]


def test_ending_a_run_reports_its_status_and_result_as_a_change():
    log = RunLog(clock=FakeClock())
    run_id = log.start_run("导出")
    log.error("目标文件被占用")
    seen = log.since(0)["last"]

    log.end_run("error", "导出失败：目标文件被占用")
    log.info("之后的散行")

    got = log.since(seen)
    # 结束本身也推进序号：只轮询「上次之后」的页面也收得到这次变化
    assert got["runs"] == [
        {"id": run_id, "name": "导出", "start": "09:00:00", "status": "error",
         "result": "导出失败：目标文件被占用"},
    ]
    assert [line["run"] for line in got["lines"]] == [None]  # 结束之后的行不再挂进去
    assert got["last"] > seen


def test_unchanged_runs_are_not_repeated():
    log = RunLog(clock=FakeClock())
    log.start_run("甲")
    log.end_run("ok", "完成")
    seen = log.since(0)["last"]
    log.info("散行")
    assert log.since(seen)["runs"] == []


@pytest.mark.parametrize("status", ["ok", "error", "stopped"])
def test_three_end_statuses_are_accepted(status: str):
    log = RunLog(clock=FakeClock())
    log.start_run("甲")
    log.end_run(status, "一句结果")
    assert log.since(0)["runs"][0]["status"] == status


def test_bad_end_status_and_ending_with_no_open_run_are_errors():
    log = RunLog(clock=FakeClock())
    with pytest.raises(RuntimeError):
        log.end_run("ok", "没开始就结束")
    log.start_run("甲")
    with pytest.raises(ValueError):
        log.end_run("done", "不认识的状态")


def test_starting_a_new_run_stops_the_one_still_open():
    """上一次运行没结束（比如中途抛异常没走到 end_run）就开始下一次：上一次记成
    stopped，免得页面上永远挂着一个「运行中」。"""
    log = RunLog(clock=FakeClock())
    first = log.start_run("甲")
    second = log.start_run("乙")
    runs = {run["id"]: run for run in log.since(0)["runs"]}
    assert runs[first]["status"] == "stopped"
    assert runs[second]["status"] == "running"
    assert second != first


# ---------------------------------------------------------------------------
# 上限：超了丢最旧的，序号不回退
# ---------------------------------------------------------------------------


def test_memory_cap_drops_the_oldest_lines_and_seq_never_goes_back():
    log = RunLog(max_lines=3, clock=FakeClock())
    for n in range(5):
        log.info(f"第 {n} 行")

    got = log.since(0)

    assert [line["text"] for line in got["lines"]] == ["第 2 行", "第 3 行", "第 4 行"]
    assert [line["seq"] for line in got["lines"]] == [3, 4, 5]
    assert got["last"] == 5
    log.info("第 5 行")
    assert log.since(5)["lines"][0]["seq"] == 6


# ---------------------------------------------------------------------------
# 线程安全
# ---------------------------------------------------------------------------


def test_concurrent_writers_lose_nothing_and_seqs_are_unique_and_ordered():
    log = RunLog(max_lines=10_000, clock=lambda: dt.datetime(2026, 11, 18, 9, 0, 0))
    threads, per_thread = 8, 250
    start = threading.Barrier(threads)

    def write(tag: int) -> None:
        start.wait()
        for n in range(per_thread):
            log.info(f"{tag}-{n}")

    workers = [threading.Thread(target=write, args=(t,)) for t in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)

    lines = log.since(0)["lines"]
    seqs = [line["seq"] for line in lines]
    assert len(lines) == threads * per_thread
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    for tag in range(threads):  # 同一线程写的行，先后不乱
        mine = [line["text"] for line in lines if line["text"].startswith(f"{tag}-")]
        assert mine == [f"{tag}-{n}" for n in range(per_thread)]


# ---------------------------------------------------------------------------
# logging.Handler：标准 logging 的等级映射进来
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("std_level", "expected"),
    [
        (logging.DEBUG, "info"),
        (logging.INFO, "info"),
        (logging.WARNING, "warn"),
        (logging.ERROR, "error"),
        (logging.CRITICAL, "error"),
    ],
)
def test_handler_maps_standard_levels(std_level: int, expected: str):
    log = RunLog(clock=FakeClock())
    logger = logging.getLogger(f"test_runlog.handler.{std_level}")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handler = RunLogHandler(log)
    logger.addHandler(handler)
    try:
        logger.log(std_level, "第 %d 张表读不到", 3)
    finally:
        logger.removeHandler(handler)

    assert log.since(0)["lines"] == [
        {"seq": 1, "time": "09:00:00", "level": expected, "text": "第 3 张表读不到", "run": None},
    ]


# ---------------------------------------------------------------------------
# 按天落文件：一行页眉 + 原话每行缩进四格，能读回
# ---------------------------------------------------------------------------


def test_no_log_dir_means_no_file(tmp_path):
    log = RunLog(clock=FakeClock())
    log.info("只在内存里")
    assert log.log_dir is None
    assert list(tmp_path.iterdir()) == []


def test_daily_file_has_a_header_line_and_four_space_indented_text(tmp_path):
    log = RunLog(log_dir=tmp_path / "日志", clock=FakeClock())
    log.info("程序已启动")
    log.start_run("导出")
    log.error("目标文件被占用：\nD:/数据/结果.xlsx")

    path = tmp_path / "日志" / "2026-11-18.log"
    assert path.read_text(encoding="utf-8") == (
        "2026-11-18 09:00:00 [信息]\n"
        "    程序已启动\n"
        "2026-11-18 09:00:02 [失败] 导出\n"
        "    目标文件被占用：\n"
        "    D:/数据/结果.xlsx\n"
    )


def test_a_new_day_goes_into_a_new_file(tmp_path):
    clock = FakeClock(dt.datetime(2026, 11, 18, 23, 59, 59))
    log = RunLog(log_dir=tmp_path, clock=clock)
    log.info("前一天")
    log.warn("后一天")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-11-18.log", "2026-11-19.log"]


def test_the_file_reads_back_into_entries(tmp_path):
    log = RunLog(log_dir=tmp_path, clock=FakeClock())
    log.info("散行")
    log.start_run("导出")
    log.warn("第一行\n  第二行带缩进")

    entries = read_log_file(tmp_path / "2026-11-18.log")

    assert entries == [
        {"date": "2026-11-18", "time": "09:00:00", "level": "info", "run": "", "text": "散行"},
        {"date": "2026-11-18", "time": "09:00:02", "level": "warn", "run": "导出",
         "text": "第一行\n  第二行带缩进"},
    ]


def test_reading_a_hand_broken_file_says_which_line(tmp_path):
    path = tmp_path / "2026-11-18.log"
    path.write_text("2026-11-18 09:00:00 [信息]\n    好的\n这行没缩进\n", encoding="utf-8")
    with pytest.raises(ValueError, match="这行没缩进"):
        read_log_file(path)


def test_log_file_path_points_at_todays_file(tmp_path):
    log = RunLog(log_dir=tmp_path, clock=FakeClock())
    assert log.log_file_path(dt.date(2026, 11, 18)) == tmp_path / "2026-11-18.log"


# ---------------------------------------------------------------------------
# 审查修复（#29）：怪字符读得回、文件写不进只提示一次、并发落文件不乱序
# ---------------------------------------------------------------------------


def test_carriage_returns_form_feeds_and_newlines_in_run_names_still_read_back(tmp_path):
    """splitlines 会在 \\r、\\x0c 这类字符上断行，整份读不回。写入前 \\r\\n / \\r 统一成
    \\n、运行名里的换行换成空格，读回按 \\n 切。"""
    log = RunLog(log_dir=tmp_path, clock=FakeClock())
    log.start_run("导出\n第二段")
    log.info("甲\r\n乙\r丙\x0c丁\x0b戊")

    entries = read_log_file(tmp_path / "2026-11-18.log")

    assert entries == [
        {"date": "2026-11-18", "time": "09:00:01", "level": "info", "run": "导出 第二段",
         "text": "甲\n乙\n丙\x0c丁\x0b戊"},
    ]


def test_unwritable_log_dir_warns_once_in_memory_and_keeps_logging(tmp_path):
    blocker = tmp_path / "不是目录"
    blocker.write_text("占位", encoding="utf-8")
    log = RunLog(log_dir=blocker / "日志", clock=FakeClock())

    log.info("一")
    log.info("二")

    got = [(line["level"], line["text"]) for line in log.since(0)["lines"]]
    assert got[0] == ("info", "一")
    assert got[1][0] == "warn" and got[1][1].startswith("日志文件写不进：")
    assert got[2:] == [("info", "二")]  # 只提示一次


def test_concurrent_writers_land_in_the_file_in_seq_order(tmp_path):
    log = RunLog(log_dir=tmp_path, clock=lambda: dt.datetime(2026, 11, 18, 9, 0, 0))
    threads, per_thread = 6, 100
    start = threading.Barrier(threads)

    def write(tag: int) -> None:
        start.wait()
        for n in range(per_thread):
            log.info(f"{tag}-{n}")

    workers = [threading.Thread(target=write, args=(t,)) for t in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)

    in_memory = [line["text"] for line in log.since(0)["lines"]]
    in_file = [entry["text"] for entry in read_log_file(tmp_path / "2026-11-18.log")]
    assert in_file == in_memory


def test_reading_a_file_saved_with_crlf_line_ends(tmp_path):
    # Windows 上手动打开改过再存，行尾会变成 CRLF；读回结果不变。
    path = tmp_path / "2026-11-18.log"
    path.write_bytes("2026-11-18 09:00:00 [信息]\r\n    好的\r\n".encode("utf-8"))
    assert read_log_file(path) == [
        {"date": "2026-11-18", "time": "09:00:00", "level": "info", "run": "", "text": "好的"},
    ]
