"""冻结产物冒烟探针——最小消费者，走全链路：

装包 → `copy_assets` 把共享样式落到自己的页面目录 → 页面同目录相对路径
引用 → `msui.shell.run(hidden=True)` 真开窗（dogfooding，全程不上屏）→
`evaluate_js` 读 getComputedStyle 核对共享样式生效 → 销毁窗口退出。

同时钉死三条待验条款（在 Windows CI 的冻结产物里跑出答案）：

  ① 页面目录可写性——含窗口开着（css 已被 WebView2 加载）时的覆盖写；
  ② 冻结产物里 msui 版本元数据正确——不许是 0.0.0+unknown（macOS 曾观察到
     不写 copy-metadata 也拿到版本，那是未解之谜，不许依赖；这里以环境变量
     MSUI_EXPECTED_VERSION 给出的期望值硬性核对）；
  ③ 单实例守卫在**冻结产物**里真的管用（票 12）——命名 mutex 走的是 ctypes
     直调 kernel32，PyInstaller 冻结后 ctypes/api-ms-* 那套依赖是否齐全只有
     真产物答得出。做法是真双开：窗口开着（锁持有中）时 spawn 一份自己，
     副本必须打出 BLOCKED 并自己退出。
  ④ 票 #27 的部件与开关在真窗口里成立：第二页（widgets.html）上步骤卡、读数卡
     的 computedStyle 取到 token 色；没存偏好时开窗即浅色；点主题按钮后
     data-theme 翻转、图标切换、localStorage 写入；正文 user-select 不是 none、
     按钮是 none；另起一份 `run(text_select=False)` 的副本，正文必须是 none；
     再起两份共用临时 storage_dir 的副本：第一份点成深色，第二份开窗仍是深色。
  ⑤ 票 #29 的运行日志区在真窗口里成立（同在 widgets.html）：记了散行、一次成功
     运行、一次失败运行、最新一次成功运行之后，最早的组收起、失败组浅红底且展开、
     最新组展开；长行真的换行、不横滚；正文可选；点折叠后 Python 再记一条 error，
     日志区自动展开且偏好仍是折叠；再折叠、一次运行以失败结束（期间没有 error
     行）也自动展开；灌 2100 行后页面只留最近 2000 行、删空的组整组删、计数写
     「N 行，显示最近 2000 行」；再起两份共用 storage_dir 的副本：第一份点折叠，
     第二份开窗前预先记好 warn 与失败运行——开窗读到这些历史仍折叠（只有开窗之后
     新到的才算）。

输出约定：最后一行 ``SMOKE-RESULT {json}``（全部读数），失败清单非空则
退出码 1；watchdog 超时直接 os._exit(2)。所有 print 均 flush——冻结产物
stdout 重定向到 CI 日志时是块缓冲，不 flush 顺序会乱。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

import msui
from msui import resources
from msui.runlog import RunLog
from msui.shell import run

TIMEOUT_SECONDS = 120
EXPECTED_VERSION_ENV = "MSUI_EXPECTED_VERSION"

# 单实例守卫的 id（消费者侧就是 miniprog.toml 的 id）与「我是副本」的开关。
# 副本模式靠环境变量而不是命令行参数：冻结产物的 argv 要经 bootloader，
# 环境变量这条路两种形态（源码/onedir）完全一致。
SINGLE_INSTANCE_ID = "msui-smoke-probe"
SECOND_INSTANCE_ENV = "MSUI_SECOND_INSTANCE"
SECOND_INSTANCE_TIMEOUT = 60
# 票 #27：「text_select=False 时正文不可选」要另开一扇窗验——同一进程里 run()
# 只能起一次主循环。副本走环境变量开关，单例守卫关掉（主窗口正持有锁）。
TEXT_SELECT_OFF_ENV = "MSUI_TEXT_SELECT_OFF"

# spec #26 测试④「重开后保持」：主题偏好跨次开窗还在。两趟副本共用一个临时
# storage_dir（run 给了它才不走隐私模式、localStorage 才落盘）：第一趟点成深色
# 退出，第二趟开窗读 data-theme——没设 = 深色保持住了。环境变量的值是这一趟的
# 角色（click / check），目录由 THEME_STORAGE_ENV 递过去。
THEME_PERSIST_ENV = "MSUI_THEME_PERSIST"
THEME_STORAGE_ENV = "MSUI_THEME_STORAGE"

# 票 #29「点折叠后重开仍折叠」：同上的两趟副本模式，角色 click / check。
RUNLOG_PERSIST_ENV = "MSUI_RUNLOG_PERSIST"
RUNLOG_STORAGE_ENV = "MSUI_RUNLOG_STORAGE"

# 页面里读 user-select：WebKit 只认带前缀的那个属性，两个都读。
_USER_SELECT_JS = (
    "(() => { const us = el => { const cs = getComputedStyle(el);"
    " return cs.userSelect || cs.webkitUserSelect; };"
    " const p = document.getElementById('{text_id}'); const b = document.querySelector('button');"
    " if (!p || !b) return 'missing'; return us(p) + ' ' + us(b); })()"
)

# Windows 控制台默认 cp1252，本探针输出带中文——自己把 stdout/stderr 掰成
# UTF-8，不指望调用方记得设 PYTHONUTF8（errors="replace" 保底：宁可读数里
# 出问号，不许探针因为打印这一步炸掉）。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# 期望读数——来源见注释；getComputedStyle 的色值序列化按 CSSOM 规范是
# "rgb(r, g, b)"，这里同时容忍 "rgba(r, g, b, 1)" 写法（去空白后比较）。
EXPECTED_BODY_BG = "#141417"  # tokens.css --win，经 base.css `body { background: var(--win) }`
EXPECTED_LINK_COLOR = "#60a5fa"  # tokens.css --info，经 base.css `a { color: var(--info) }`
EXPECTED_CONTROL_COLOR = "rgb(7, 130, 89)"  # 对照组 same.css 直写

results: dict[str, object] = {
    "frozen": bool(getattr(sys, "frozen", False)),
    "platform": sys.platform,
}
failures: list[str] = []


# 运行日志缓冲：widgets.html 的日志区按 data-runlog="get_log" 轮询它。
RUNLOG = RunLog()
LONG_LINE = (
    "目标文件被占用，写不进去："
    "//fileserver/share/归档/2024/01/导出结果_最终版_请勿改名_条目一与条目二合并_sample-0001_20240131.xlsx"
)


def fill_runlog(log: RunLog) -> None:
    """散行 + 成功运行 + 失败运行 + 最新一次成功运行：三组的默认开合各不相同。"""
    log.info("程序已启动")
    log.start_run("读取数据")
    log.info("读到 6 张表。")
    log.end_run("ok", "6 张表全部识别成功")
    log.start_run("导出")
    log.warn("数量与上一轮相差超过一成。")
    log.error(LONG_LINE)
    log.end_run("error", "导出失败：目标文件被占用")
    log.start_run("重新读取")
    log.info("读到 6 张表。")
    log.end_run("ok", "完成")


class ProbeApi:
    """探针的 js_api：只有日志区要的那个方法。"""

    def get_log(self, since: int = 0) -> dict:
        return RUNLOG.since(since)


# 页面日志区最多留的行数（runlog.js 的 MAX_LINES）。
PAGE_MAX_LINES = 2000


def settle_storage() -> None:
    """localStorage 写完留一口气再关窗：本机实测过一次「点完立刻销毁、下一趟读不到」
    的偶发红（复跑不复现），疑似存储还没落盘。主题与日志区两个持久化副本共用。"""
    time.sleep(0.5)


def check(name: str, ok: bool, detail: object) -> None:
    results[name] = detail
    if not ok:
        failures.append(f"{name}: {detail}")


def page_dir() -> Path:
    """探针自己的页面目录（消费者持有页面——出路二的前提）。

    冻结态在 `sys._MEIPASS/pages`（spec 里 `("pages", "pages")` 收进去的），
    源码态就是本文件旁边的 pages/。
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "pages"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / "pages"


def _norm_color(value: object) -> str:
    """把 getComputedStyle 色值归一成 'r,g,b' 便于比较。"""
    text = str(value).strip().lower().replace(" ", "")
    for prefix in ("rgba(", "rgb("):
        if text.startswith(prefix):
            channels = text[len(prefix):].rstrip(")").split(",")
            return ",".join(channels[:3])
    return text


def _hex_to_channels(hex_color: str) -> str:
    raw = hex_color.lstrip("#")
    return ",".join(str(int(raw[i : i + 2], 16)) for i in (0, 2, 4))


def token_check(window, name: str, selector: str, prop: str, token: str) -> None:  # noqa: ANN001
    """元素实测 computedStyle[prop] == 页面此刻把 var(--token) 解出来的颜色。

    跟页面自己解出来的值比（同 msui.testing.SmokeDriver.check_token_style），
    深浅主题都成立，不写死十六进制。"""
    js = (
        "(() => {"
        f" const el = document.querySelector({json.dumps(selector)});"
        " if (!el) return 'missing|';"
        " const v = getComputedStyle(document.documentElement)"
        f"   .getPropertyValue({json.dumps('--' + token)}).trim();"
        " const probe = document.createElement('div'); probe.style.color = v || 'transparent';"
        " document.body.appendChild(probe); const want = getComputedStyle(probe).color; probe.remove();"
        f" return getComputedStyle(el)[{json.dumps(prop)}] + '|' + want; }})()"
    )
    actual, _, want = str(window.evaluate_js(js)).partition("|")
    check(name, bool(want) and actual == want, f"{selector} {prop}={actual} want --{token}={want}")


def text_select_off_main() -> int:
    """副本模式：`run(text_select=False)` 开一扇隐藏窗，打一行正文的 user-select。"""
    seen: list[str] = []

    def on_ready_off(window) -> None:  # noqa: ANN001
        try:
            for _ in range(200):
                if window.evaluate_js("document.readyState") == "complete":
                    break
                time.sleep(0.1)
            seen.append(str(window.evaluate_js(_USER_SELECT_JS.replace("{text_id}", "probe-text"))))
        finally:
            window.destroy()

    run(
        page_dir() / "widgets.html",
        title="msui-smoke-probe-text-select-off",
        hidden=True,
        text_select=False,
        single_instance=False,
        on_ready=on_ready_off,
    )
    print("TEXT-SELECT-OFF " + (seen[0] if seen else "never-ran"), flush=True)
    return 0


def theme_persist_main(role: str) -> int:
    """副本模式：带 storage_dir 开窗。click 趟点一下主题按钮（浅 → 深）并核对
    localStorage 已写 ''；check 趟只读开窗时的主题。各打一行 THEME-PERSIST。"""
    seen: list[str] = []

    def on_ready_persist(window) -> None:  # noqa: ANN001
        try:
            for _ in range(200):
                if window.evaluate_js(
                    "document.readyState === 'complete' && !!document.querySelector('.kpis')"
                ):
                    break
                time.sleep(0.1)
            if role == "click":
                seen.append(str(window.evaluate_js(
                    "(() => { const b = document.querySelector('[data-theme-toggle]');"
                    " if (!b) return 'missing'; b.click();"
                    " return (document.documentElement.dataset.theme || 'dark') + ' '"
                    "   + JSON.stringify(localStorage.getItem('theme')); })()"
                )))
                settle_storage()
            else:
                seen.append(str(window.evaluate_js(
                    "document.documentElement.dataset.theme || 'dark'"
                )))
        finally:
            window.destroy()

    run(
        page_dir() / "widgets.html",
        title=f"msui-smoke-probe-theme-{role}",
        hidden=True,
        storage_dir=os.environ[THEME_STORAGE_ENV],
        single_instance=False,
        on_ready=on_ready_persist,
    )
    print(f"THEME-PERSIST {role} " + (seen[0] if seen else "never-ran"), flush=True)
    return 0


def runlog_persist_main(role: str) -> int:
    """副本模式：带 storage_dir 开窗。click 趟点一下日志区的折叠按钮并读回
    localStorage；check 趟只读开窗时日志区是不是折叠着。各打一行 RUNLOG-PERSIST。"""
    seen: list[str] = []

    def on_ready_persist(window) -> None:  # noqa: ANN001
        try:
            for _ in range(200):
                if window.evaluate_js(
                    "document.readyState === 'complete' && !!document.querySelector('[data-runlog]')"
                ):
                    break
                time.sleep(0.1)
            if role == "click":
                seen.append(str(window.evaluate_js(
                    "(() => { const b = document.querySelector('[data-runlog-toggle]');"
                    " if (!b) return 'missing'; b.click();"
                    " return (document.querySelector('[data-runlog-list]').hidden ? 'folded' : 'open')"
                    "   + ' ' + JSON.stringify(localStorage.getItem('runlog-collapsed')); })()"
                )))
                settle_storage()
            else:
                # 等首轮 since(0) 落到页面上（行数出现了），再读折叠态：历史里的
                # warn / error 不该把用户选的「折叠」展开。
                for _ in range(100):
                    if window.evaluate_js(
                        "(document.querySelector('[data-runlog-count]') || {}).textContent"
                    ):
                        break
                    time.sleep(0.1)
                seen.append(str(window.evaluate_js(
                    "(() => { const s = document.querySelector('[data-runlog]');"
                    " if (!s) return 'missing';"
                    " const n = s.querySelector('[data-runlog-count]').textContent;"
                    " return ((s.querySelector('[data-runlog-list]').hidden"
                    "   && s.classList.contains('collapsed')) ? 'folded' : 'open') + ' ' + n; })()"
                )))
        finally:
            window.destroy()

    if role == "check":
        RUNLOG.warn("开窗之前就有的告警")
        RUNLOG.start_run("开窗之前的运行")
        RUNLOG.error("开窗之前就有的失败")
        RUNLOG.end_run("error", "开窗之前就失败了")
    run(
        page_dir() / "widgets.html",
        js_api=ProbeApi(),
        title=f"msui-smoke-probe-runlog-{role}",
        hidden=True,
        storage_dir=os.environ[RUNLOG_STORAGE_ENV],
        single_instance=False,
        on_ready=on_ready_persist,
    )
    print(f"RUNLOG-PERSIST {role} " + (seen[0] if seen else "never-ran"), flush=True)
    return 0


def _runlog_persist_round(role: str, storage: str) -> str:
    """跑一趟日志区折叠持久化副本，取回它那行读数。"""
    done = _spawn_self(RUNLOG_PERSIST_ENV, value=role, extra={RUNLOG_STORAGE_ENV: storage})
    prefix = f"RUNLOG-PERSIST {role} "
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith(prefix)), "")
    return line.removeprefix(prefix) or (
        f"no-line rc={done.returncode} err={done.stderr.strip()[-200:]!r}"
    )


def _theme_persist_round(role: str, storage: str) -> str:
    """跑一趟主题持久化副本，取回它那行读数（取不到回空串）。"""
    done = _spawn_self(THEME_PERSIST_ENV, value=role, extra={THEME_STORAGE_ENV: storage})
    prefix = f"THEME-PERSIST {role} "
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith(prefix)), "")
    return line.removeprefix(prefix) or (
        f"no-line rc={done.returncode} err={done.stderr.strip()[-200:]!r}"
    )


def _spawn_self(
    env_name: str, *, value: str = "1", extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    """起一份自己（副本模式由环境变量选）。冻结态 sys.executable 就是 probe.exe 本身。"""
    argv = [sys.executable]
    if not getattr(sys, "frozen", False):
        argv.append(str(Path(__file__).resolve()))
    env = {**os.environ, env_name: value, **(extra or {})}
    return subprocess.run(
        argv,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=SECOND_INSTANCE_TIMEOUT,
    )


def check_widgets_page(window) -> None:  # noqa: ANN001
    """票 #27：第二页上的步骤卡、读数卡、主题切换、文字可选。"""
    window.load_url(str(page_dir() / "widgets.html"))
    for _ in range(200):
        if window.evaluate_js(
            "document.readyState === 'complete' && !!document.querySelector('.kpis')"
        ):
            break
        time.sleep(0.1)
    else:
        failures.append("widgets_page_load: widgets.html 一直没加载出来")
        return

    theme = window.evaluate_js("document.documentElement.dataset.theme || 'dark'")
    check("theme_default_light", theme == "light", theme)

    # 切主题之前读：步骤卡底色带 transition，隐藏窗里 transition 不推进。
    token_check(window, "step_cur_bg", ".step.cur", "backgroundColor", "card")
    token_check(window, "step_done_num_bg", ".step.done .num i", "backgroundColor", "brand")
    token_check(window, "step_done_num_color", ".step.done .num i", "color", "on-brand")
    token_check(window, "step_wait_title_color", ".step.wait .title", "color", "muted")
    token_check(window, "kpi_val_color", ".kpi .val", "color", "text")
    token_check(window, "kpi_warn_val_color", ".kpi.warn .val", "color", "warn")

    selectable = str(window.evaluate_js(_USER_SELECT_JS.replace("{text_id}", "probe-text")))
    text_us, _, button_us = selectable.partition(" ")
    check("user_select_text", text_us not in ("none", "missing"), text_us)
    check("user_select_button", button_us == "none", button_us)

    flips = window.evaluate_js(
        "(() => { const b = document.querySelector('[data-theme-toggle]');"
        " if (!b) return 'missing';"
        " const shown = () => ['sun', 'moon'].filter(c =>"
        "   getComputedStyle(b.querySelector('.' + c)).display !== 'none').join('+');"
        " const state = () => { let saved; try { saved = localStorage.getItem('theme'); }"
        "   catch (e) { saved = 'unavailable'; }"
        "   return [document.documentElement.dataset.theme || 'dark', shown(),"
        "     JSON.stringify(saved)].join(' '); };"
        " b.click(); const once = state(); b.click();"
        " return once + ' / ' + state(); })()"
    )
    check("theme_toggle", flips == 'dark sun "" / light moon "light"', flips)


def check_runlog(window) -> None:  # noqa: ANN001
    """票 #29：widgets.html 上的运行日志区（页面已由 check_widgets_page 载入）。"""
    groups_js = (
        "(() => { const gs = [...document.querySelectorAll('.runlog-run')];"
        " return gs.map(g => (g.querySelector('.runlog-lines').hidden ? 'closed' : 'open')"
        "   + ':' + g.querySelector('.st').textContent).join(' '); })()"
    )
    groups = ""
    for _ in range(200):
        groups = str(window.evaluate_js(groups_js))
        if groups.count(":") == 3:
            break
        time.sleep(0.1)
    # 最早的成功组收起；失败组默认展开；最新组展开
    check("runlog_groups", groups == "closed:成功 open:失败 open:成功", groups)
    token_check(window, "runlog_error_run_bg", ".runlog-run.error", "backgroundColor", "error-bg")
    token_check(window, "runlog_error_line_bg", ".runlog-line.error", "backgroundColor", "error-bg")
    token_check(window, "runlog_error_level_color", ".runlog-line.error .lv", "color", "error")
    head = window.evaluate_js(
        "(() => { const h = document.querySelector('.runlog-run.error .runlog-head');"
        " return h ? [...h.children].map(c => c.textContent).slice(1).join(' · ') : 'missing'; })()"
    )
    check("runlog_error_head", head == "失败 · 导出 · 导出失败：目标文件被占用", head)
    wrapped = window.evaluate_js(
        "(() => { const tx = [...document.querySelectorAll('.runlog-line .tx')]"
        f"   .find(e => e.textContent === {json.dumps(LONG_LINE)});"
        " const list = document.querySelector('[data-runlog-list]');"
        " if (!tx || !list) return 'missing';"
        " const cs = getComputedStyle(tx);"
        " if (cs.whiteSpace !== 'pre-wrap') return 'white-space ' + cs.whiteSpace;"
        " if (tx.getBoundingClientRect().height < parseFloat(cs.lineHeight) * 1.5) return 'one-line';"
        " if (list.scrollWidth > list.clientWidth) return 'hscroll';"
        " return 'wraps'; })()"
    )
    check("runlog_long_line_wraps", wrapped == "wraps", wrapped)
    selectable = window.evaluate_js(
        "(() => { const tx = document.querySelector('.runlog-line .tx');"
        " if (!tx) return 'missing'; const cs = getComputedStyle(tx);"
        " return cs.userSelect || cs.webkitUserSelect; })()"
    )
    check("runlog_text_selectable", selectable not in ("none", "missing"), selectable)
    # 折叠后 Python 再记一条 error：日志区自动展开，偏好仍是折叠
    folded = window.evaluate_js(
        "(() => { const b = document.querySelector('[data-runlog-toggle]');"
        " if (!b) return 'missing'; b.click();"
        " return document.querySelector('[data-runlog-list]').hidden ? 'folded' : 'open'; })()"
    )
    check("runlog_fold", folded == "folded", folded)
    RUNLOG.error("折叠着来了一条失败")
    reopened = ""
    for _ in range(100):
        reopened = str(window.evaluate_js(
            "(() => { const s = document.querySelector('[data-runlog]');"
            " if (!s) return 'missing';"
            " return (s.querySelector('[data-runlog-list]').hidden ? 'folded' : 'open') + ' '"
            "   + JSON.stringify(localStorage.getItem('runlog-collapsed')); })()"
        ))
        if reopened.startswith("open"):
            break
        time.sleep(0.1)
    check("runlog_error_unfolds_without_saving", reopened == 'open "1"', reopened)

    # 再折叠：一次运行以失败结束、期间没有 error 行，也算告警，自动展开
    window.evaluate_js("document.querySelector('[data-runlog-toggle]').click()")
    RUNLOG.start_run("静默失败")
    RUNLOG.info("这一趟没有 error 行")
    RUNLOG.end_run("error", "结局是失败")
    run_alarm = ""
    for _ in range(100):
        run_alarm = str(window.evaluate_js(
            "(() => { const l = document.querySelector('[data-runlog-list]');"
            " return l ? (l.hidden ? 'folded' : 'open') : 'missing'; })()"
        ))
        if run_alarm == "open":
            break
        time.sleep(0.1)
    check("runlog_error_run_unfolds", run_alarm == "open", run_alarm)

    # 页面上限：灌 2100 行散行，只留最近 2000 行；之前的组全被挤空、整组删掉
    for n in range(2100):
        RUNLOG.info(f"灌行 {n}")
    capped = ""
    for _ in range(150):
        capped = str(window.evaluate_js(
            "(() => { const s = document.querySelector('[data-runlog]');"
            " if (!s) return 'missing';"
            " return [s.querySelectorAll('.runlog-line').length,"
            "   s.querySelectorAll('.runlog-run').length,"
            "   s.querySelector('[data-runlog-count]').textContent].join(' | '); })()"
        ))
        if "灌行" in str(window.evaluate_js(
            "(() => { const t = [...document.querySelectorAll('.runlog-line .tx')].pop();"
            " return t ? t.textContent : ''; })()"
        )) and capped.startswith(f"{PAGE_MAX_LINES} "):
            break
        time.sleep(0.1)
    total = len(RUNLOG.since(0)["lines"])
    check(
        "runlog_page_cap",
        capped == f"{PAGE_MAX_LINES} | 0 | {total} 行，显示最近 {PAGE_MAX_LINES} 行",
        capped,
    )


def second_instance_main() -> int:
    """副本模式：同 id 再 run 一次，把守卫的判定打成一行标记。

    - 守卫拦住 → `run` 直接返回，on_ready 从没被触发 → 打 `BLOCKED`；
    - 守卫没拦住 → 窗口真开起来了，立刻销毁并打 `OPENED`（= 双开实测失败）。

    退出码一律 0：副本的结论靠输出标记传递，主探针据此判定。副本自己崩掉
    才会是非零——那也是主探针要报出来的信息。
    """
    opened: list[bool] = []

    def on_ready_second(window) -> None:  # noqa: ANN001
        opened.append(True)
        window.destroy()

    run(
        page_dir() / "index.html",
        title="msui-smoke-probe",
        hidden=True,
        single_instance=SINGLE_INSTANCE_ID,
        on_ready=on_ready_second,
    )
    print("SECOND-INSTANCE " + ("OPENED" if opened else "BLOCKED"), flush=True)
    return 0


def _spawn_second_instance() -> subprocess.CompletedProcess:
    """起一份自己当第二实例。"""
    return _spawn_self(SECOND_INSTANCE_ENV)


def on_ready(window) -> None:  # noqa: ANN001 - pywebview Window，探针不引类型
    results["on_ready_ran"] = True
    try:
        for _ in range(200):
            if window.evaluate_js("document.readyState") == "complete":
                break
            time.sleep(0.1)
        else:
            failures.append("page_load: readyState 一直没到 complete")

        body_bg = window.evaluate_js(
            "getComputedStyle(document.body).backgroundColor"
        )
        link_color = window.evaluate_js(
            "getComputedStyle(document.getElementById('probe-link')).color"
        )
        control_color = window.evaluate_js(
            "getComputedStyle(document.getElementById('control')).color"
        )
        check(
            "computed_body_bg",
            _norm_color(body_bg) == _hex_to_channels(EXPECTED_BODY_BG),
            body_bg,
        )
        check(
            "computed_link_color",
            _norm_color(link_color) == _hex_to_channels(EXPECTED_LINK_COLOR),
            link_color,
        )
        # 对照组：读不到它 = 探针自己坏了，与共享样式无关
        check(
            "computed_control_color",
            _norm_color(control_color) == _norm_color(EXPECTED_CONTROL_COLOR),
            control_color,
        )

        # 待验条款①的硬核部分：窗口开着、css 已被 WebView2 加载的状态下覆盖写。
        # 先写坏再 copy_assets，读回内容 == 版本横幅 + 包内原件，证明覆盖真的
        # 发生了（不然「覆盖同样内容」分辨不出写没写进去）。
        target = page_dir() / resources.TOKENS_CSS_NAME
        try:
            target.write_text("/* stale-while-open */", encoding="utf-8")
            resources.copy_assets(page_dir())
            expected = resources.version_banner() + resources.tokens_css_path().read_text(
                encoding="utf-8"
            )
            overwritten = target.read_text(encoding="utf-8") == expected
            check("overwrite_while_open", overwritten, "ok" if overwritten else "内容没换过来")
        except OSError as exc:
            check("overwrite_while_open", False, f"OSError: {exc}")

        # 待验条款③：双开实测。此刻窗口开着、锁在本进程手里，起一份自己——
        # 副本必须被守卫拦下（BLOCKED）。放在 on_ready 里就是为了「锁确实
        # 正被持有」这个前提成立；跑在窗口销毁之后的话，测的就成了空气。
        try:
            second = _spawn_second_instance()
            blocked = "SECOND-INSTANCE BLOCKED" in second.stdout
            check(
                "second_instance_blocked",
                blocked,
                f"rc={second.returncode} out={second.stdout.strip()[-200:]!r}"
                f" err={second.stderr.strip()[-200:]!r}",
            )
        except subprocess.TimeoutExpired:
            # 副本没在预算内退出 = 守卫没拦住又卡在主循环里，这本身就是失败。
            check("second_instance_blocked", False, "副本超时未退出")

        # 待验条款④：票 #27 的部件、主题切换、文字可选（第二页）。
        check_widgets_page(window)
        # 待验条款⑤：票 #29 的运行日志区（同一页）。
        check_runlog(window)

        # text_select=False 的副本：正文必须不可选（pywebview 注入的那条生效）。
        try:
            off = _spawn_self(TEXT_SELECT_OFF_ENV)
            line = next(
                (ln for ln in off.stdout.splitlines() if ln.startswith("TEXT-SELECT-OFF ")), ""
            )
            text_us = line.removeprefix("TEXT-SELECT-OFF ").partition(" ")[0]
            check(
                "text_select_off_locks_text",
                text_us == "none",
                f"rc={off.returncode} out={off.stdout.strip()[-200:]!r}"
                f" err={off.stderr.strip()[-200:]!r}",
            )
        except subprocess.TimeoutExpired:
            check("text_select_off_locks_text", False, "副本超时未退出")

        # 重开后保持：第一趟点成深色、第二趟开窗仍是深色。
        try:
            with tempfile.TemporaryDirectory(prefix="msui-theme-") as storage:
                first = _theme_persist_round("click", storage)
                second = _theme_persist_round("check", storage)
            check("theme_persists_click", first == 'dark ""', first)
            check("theme_persists_reopen", second == "dark", second)
        except subprocess.TimeoutExpired:
            check("theme_persists_reopen", False, "副本超时未退出")

        # 日志区折叠重开后保持：第一趟点折叠、第二趟开窗仍折叠。
        try:
            with tempfile.TemporaryDirectory(prefix="msui-runlog-") as storage:
                first = _runlog_persist_round("click", storage)
                second = _runlog_persist_round("check", storage)
            check("runlog_fold_persists_click", first == 'folded "1"', first)
            check("runlog_fold_persists_reopen", second == "folded 2 行", second)
        except subprocess.TimeoutExpired:
            check("runlog_fold_persists_reopen", False, "副本超时未退出")
    except Exception:  # noqa: BLE001 - 探针要把任何炸法都带出窗口报出来
        failures.append("on_ready 崩了：\n" + traceback.format_exc())
    finally:
        window.destroy()


def main() -> int:
    if os.environ.get(SECOND_INSTANCE_ENV) == "1":
        return second_instance_main()
    if os.environ.get(TEXT_SELECT_OFF_ENV) == "1":
        return text_select_off_main()
    if os.environ.get(THEME_PERSIST_ENV) in ("click", "check"):
        return theme_persist_main(os.environ[THEME_PERSIST_ENV])
    if os.environ.get(RUNLOG_PERSIST_ENV) in ("click", "check"):
        return runlog_persist_main(os.environ[RUNLOG_PERSIST_ENV])

    watchdog = threading.Timer(
        TIMEOUT_SECONDS,
        lambda: (print("SMOKE-FAIL: watchdog 超时", flush=True), os._exit(2)),
    )
    watchdog.daemon = True
    watchdog.start()

    # 待验条款②：版本元数据。冻结产物里不许是 0.0.0+unknown——那说明
    # hook 的 copy_metadata 没生效，下游按版本戳的缓存清理会全部失灵。
    version = msui.get_version()
    check("version", "unknown" not in version, version)
    expected_version = os.environ.get(EXPECTED_VERSION_ENV)
    if expected_version:
        check("version_matches_expected", version == expected_version, version)

    # Windows 上先确保 WebView2 就绪（dogfooding；runner 镜像通常自带，缺了就引导装）
    if sys.platform == "win32":
        from msui.webview2 import ensure_webview2

        ensure = ensure_webview2()
        check(
            "webview2_ready",
            ensure.ok,
            f"ok={ensure.ok} installed_now={ensure.installed_now} error={ensure.error}",
        )
        if not ensure.ok:
            print("SMOKE-RESULT " + json.dumps({"failures": failures, **results}, ensure_ascii=False), flush=True)
            return 1

    # 待验条款①（静态半）：把共享样式落进页面目录——冻结产物的页面目录必须可写
    pd = page_dir()
    served = resources.copy_assets(pd)
    check("copy_assets_returned_page_dir", served == pd, str(served))
    for name in resources.ASSET_NAMES:
        check(f"copied_{name}", (pd / name).is_file(), str(pd / name))

    # 版本标记：落出去的 css 第一行就是 `/* msui X.Y.Z */`——冻结产物的
    # 文件系统里直接可读，值必须与元数据版本一致（单一来源）。
    banner_line = (pd / resources.TOKENS_CSS_NAME).read_text(encoding="utf-8").splitlines()[0]
    check("version_banner", banner_line == f"/* msui {version} */", banner_line)

    # 复制不动原件——Python 侧资源读取在冻结产物里仍正常
    tokens_path = resources.tokens_css_path()
    check(
        "python_side_tokens_readable",
        tokens_path.is_file() and tokens_path.parent != pd,
        str(tokens_path),
    )
    tokens = resources.parse_tokens(tokens_path.read_text(encoding="utf-8"))
    check("python_side_brand_token", tokens.get("brand") == "#db021d", tokens.get("brand"))

    # 真开窗（隐藏，全程不上屏），后台线程里读数并销毁。守卫开着——本进程
    # 是第一实例，必须照常开窗；副本由 on_ready 里的双开实测负责。
    fill_runlog(RUNLOG)
    run(
        pd / "index.html",
        js_api=ProbeApi(),
        title="msui-smoke-probe",
        hidden=True,
        single_instance=SINGLE_INSTANCE_ID,
        on_ready=on_ready,
    )

    # 「窗口根本没开起来」与「开了、读数全绿」在 failures 上是同一个形状
    # （空清单）。不单独判这一条，守卫误拦、开窗直接失败都会静静地报绿。
    check("on_ready_ran", bool(results.get("on_ready_ran")), results.get("on_ready_ran"))

    print(
        "SMOKE-RESULT " + json.dumps({"failures": failures, **results}, ensure_ascii=False),
        flush=True,
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
