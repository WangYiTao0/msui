# msui

小程序共享 UI 运行时与样式（pywebview + WebView2）：WebView2 检测引导、一行开窗、
共享 tokens/base 样式与样式闸门、js_api 桥通用件、自带 PyInstaller hook。

设计与切票见 spec：[WangYiTao0/MSLaunchpad#107](https://github.com/WangYiTao0/MSLaunchpad/issues/107)。

本 README 就是消费者契约：下面五件事按顺序做，一个新的小程序仓从零到跑起来。
所有代码块与 `examples/minimal/` 里的完整示例一字一致（有测试盯着不许漂移），
放心整段照抄；标了「片段」的块是从示例文件里摘出的连续几行，同样有测试盯着。

## 1. 装

requirements 里写一行钉版本的 wheel URL，无需任何凭据；**升级 = 只改这一行里的
两处版本号**：

```
msui @ https://github.com/WangYiTao0/msui/releases/download/v0.11.0/msui-0.11.0-py3-none-any.whl
```

另外两个工具的去处按宿主平台的接入契约分工：**`pyinstaller` 也进
`requirements.txt`**（平台 CI 的 Install deps 步只装 requirements.txt，
打包就要用它——这是接入契约的要求，不是本仓的偏好）；`pytest` 不进
requirements——平台 CI 在测试步内现装，本机开发时装一次：

```
pip install pytest
```

## 2. 最小启动

页面（HTML/CSS/JS）放自己仓的 `pages/` 目录；启动三步——定位页面目录、
`copy_assets` 落共享样式、`run` 开窗：

```python
# examples/minimal/app.py
"""msui 最小消费者：页面归自己，共享样式由 msui 启动时落进来。

三步：定位页面目录 → copy_assets 落共享样式 → run 开窗。
页面要调 Python 时把 js_api 对象递给 run（方法包 Serializer：连点丢弃、
不排队），页面那半边的写法见 pages/index.html 尾部的 <script>。
运行日志：建一个 RunLog，业务里 info / warn / error 记行、start_run / end_run
分组；js_api 上放一个 get_log 把 since() 原样转给页面的日志区（app-layout.html）。
`single_instance` 必填——只开一扇窗是默认模式，值用小程序自己的 id（全局
唯一）：用户连点图标时第二个进程把已开的窗带到前台、自己静默退出。真要
多开得显式写 `single_instance=False`，漏传当场 TypeError。
环境变量 APP_SMOKE=1 时隐藏开窗、SmokeDriver 自动驾驶一轮（等桥往返、
核对样式真的生效、横幅钉住版本）后自关——给 CI/无人值守冒烟用；自己的仓
不需要冒烟的话，把 make_smoke_script 和 driver 相关几行删掉即可。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from msui.bridge import Serializer
from msui.resources import copy_assets
from msui.runlog import RunLog
from msui.shell import run
from msui.testing import SmokeDriver

# 本仓钉死的 msui 版本，与 requirements 里 wheel URL 的版本号一致，升级
# msui 时两处一起改。冒烟据此断言横幅——钉死常量证明「产物带的确实是钉的
# 这一版」；改读 importlib.metadata 只是回显装了哪版、永远绿，证明不了钉住。
MSUI_PINNED = "0.11.0"


class Api:
    """js_api 桥对象：业务留在 Python，页面只管调用与显示。

    pywebview 对每次前端调用各开一个后台线程（官方文档明说 not
    thread-safe），方法一律包在 Serializer 里：抢不到锁立即回
    {"busy": True, ...}，绝不排队——连点五下不会攒成一队。
    """

    def __init__(self, runlog: RunLog) -> None:
        self._serial = Serializer()
        self._runlog = runlog

    def ping(self) -> dict:
        """页面调一次拿一句应答：{"busy": False, "data": "pong 来自 Python"}。"""
        return self._serial.run(lambda: "pong 来自 Python")

    def get_log(self, since: int = 0) -> dict:
        """日志区每半秒调一次：since 之后的新行与运行变化。不包 Serializer——
        RunLog 自己线程安全，取日志不该被正在跑的业务动作挡成「忙」。"""
        return self._runlog.since(since)


def demo_log(runlog: RunLog) -> None:
    """示例先记几条，打开 app-layout.html 就看得到日志区的样子；自己的程序在
    真的业务动作里记（后台线程里记也行）。"""
    runlog.info("程序已启动")
    runlog.start_run("读取数据")
    runlog.info("读到 6 张表。")
    runlog.end_run("ok", "6 张表全部识别成功")
    runlog.start_run("导出")
    runlog.warn("数量与上一轮相差超过一成。")
    runlog.error(
        "目标文件被占用，写不进去："
        "D:/数据/2024/01/导出结果_最终版_请勿改名_条目一与条目二合并_sample-0001_20240131.xlsx"
    )
    runlog.end_run("error", "导出失败：目标文件被占用")
    runlog.start_run("重新读取")
    runlog.info("读到 6 张表。")
    runlog.end_run("ok", "完成")


def page_dir() -> Path:
    """页面目录：冻结态在 _MEIPASS/pages（app.spec 收进去的），源码态在本文件旁。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "pages"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / "pages"


def make_smoke_script(serve_dir: Path, runlog: RunLog):
    """造冒烟脚本（跑在 pywebview 后台线程）：桥往返、样式生效、版式地基、
    操作行/表单行/进度条/提示条/日志区/模态对话框的实测长相、横幅钉版。

    失败收集、finally 销毁窗口、超时兜底都由 SmokeDriver 骨架代办。页面探针
    一律写成 null-safe（先判 querySelector 结果再取样式）：元素缺席时报出的
    是「missing」而不是烧满轮询预算后的一串异常文本。
    """

    def scrollbar_thickness() -> int | None:
        """滚动条粗细档：从**落地的** base.css 里那条 `::-webkit-scrollbar` 取。

        探针里不写死数字——档位只有一个来源（那条 css 规则），页面改档时冒烟
        跟着走，不用记得同步改两处。取不到回 None（而不是一个默认值）：调用
        方据此报「css 里没有这一档」，绝不拿兜底数把断言悄悄放宽。
        """
        css = (serve_dir / "base.css").read_text(encoding="utf-8")
        block = re.search(r"(?m)^::-webkit-scrollbar\s*\{([^}]*)\}", css)
        if block is None:
            return None
        match = re.search(r"height:\s*(\d+)px", block.group(1))
        return int(match.group(1)) if match else None

    def smoke_script(drive: SmokeDriver, window) -> None:
        # 桥通：页面在 pywebviewready 后自动 ping 一次，回显来自 Python 的应答
        got = drive.wait_js(
            window, "document.getElementById('pong').textContent", "pong 来自 Python"
        )
        drive.check(got == "pong 来自 Python", f"桥往返回显不对：{got!r}")
        # 样式吃进去了：主按钮实测背景色 == --brand token 解出的 rgb
        drive.check_token_style(window, "button.primary", "backgroundColor", "brand")
        # 版式地基生效：内容不贴窗框（body 非零内边距）、大读数居中吃 48px 档
        pad = drive.wait_js(window, "getComputedStyle(document.body).paddingLeft", "24px")
        drive.check(pad == "24px", f"body 左内边距该是 24px（--space-5），实测 {pad!r}")
        readout = drive.wait_js(
            window,
            "(() => { const el = document.querySelector('.display');"
            " if (!el) return 'missing'; const d = getComputedStyle(el);"
            " return d.textAlign + ' ' + d.fontSize; })()",
            "center 48px",
        )
        drive.check(readout == "center 48px", f".display 该居中吃 48px 档，实测 {readout!r}")
        # 操作行：两个按钮横排、顶边齐平。齐平这半边验的是 `.actions > * + *`
        # 的归零真压过了 `.card > * + *` 的竖向节奏——两者特异性同为 (0,1,1)，
        # 靠源码顺序决胜，规则写反时第二个按钮会掉下去半行。CSS 文本层的顺序
        # 由 tests/test_layout.py 盯着，这里盯的是渲染出来真是那样。
        row = drive.wait_js(
            window,
            "(() => { const bs = document.querySelectorAll('#ops button');"
            " if (bs.length !== 2) return 'missing';"
            " const [a, b] = [...bs].map(el => el.getBoundingClientRect());"
            " if (Math.abs(a.top - b.top) > 1) return 'stacked';"
            " return b.left >= a.right ? 'row' : 'overlap'; })()",
            "row",
        )
        drive.check(row == "row", f"操作行里两个按钮该横排且顶边齐平，实测 {row!r}")
        # 表单行：一行三件真的排开了。五条实测全走 getBoundingClientRect——
        # 每行的输入框与尾部按钮顶边齐平（其中 `<div class="card field">` 那行
        # 验的是 `.field > * + *` 的归零真压过了卡片竖向节奏，与 .actions
        # 同一个先例，规则写反时输入框起会掉下去半行）、三行的输入框左边缘
        # 彼此对齐（标签定宽 --field-label 的效果）、输入框不与标签重叠、
        # 输入框比按钮宽出一截（flex:1 吃掉了剩余宽度，不是三件平分）、
        # 整页不横向溢出。
        field = drive.wait_js(
            window,
            "(() => { const rows = [...document.querySelectorAll('.field')];"
            " if (rows.length < 3) return 'missing';"
            " const p = rows.map(r => ({"
            "   label: r.querySelector('label').getBoundingClientRect(),"
            "   input: r.querySelector('input').getBoundingClientRect(),"
            "   btn: r.querySelector('button').getBoundingClientRect() }));"
            " if (p.some(x => Math.abs(x.input.top - x.btn.top) > 1)) return 'uneven-top';"
            " if (p.some(x => Math.abs((x.input.top + x.input.height / 2)"
            "   - (x.label.top + x.label.height / 2)) > 1)) return 'label-off-center';"
            " if (p.some(x => Math.abs(x.input.left - p[0].input.left) > 1))"
            "   return 'ragged-left';"
            " if (p.some(x => x.input.left < x.label.right)) return 'label-overlap';"
            " if (p.some(x => x.input.width < x.btn.width * 2)) return 'squeezed';"
            " if (document.documentElement.scrollWidth > window.innerWidth) return 'overflow';"
            " return 'aligned'; })()",
            "aligned",
        )
        drive.check(field == "aligned", f"表单行该一行排开且左边缘对齐，实测 {field!r}")
        # 输入框吃掉剩余宽度：把窗缩窄，输入框跟着变窄且整行不横向溢出。
        # 写死宽度、或漏了 min-width: 0 时这条会红（前者不跟着变，后者顶破容器）。
        wide = window.evaluate_js(
            "(() => { const el = document.querySelector('.field > input');"
            " return el ? Math.round(el.getBoundingClientRect().width) : 0; })()"
        ) or 0  # 探针出岔子时回 0，下面那条 check 报「量不到」而不是抛 TypeError
        drive.check(wide > 0, f"量不到表单行输入框的宽度：{wide!r}")
        window.resize(360, 520)
        narrowed = drive.wait_js(
            window,
            "(() => { const el = document.querySelector('.field > input');"
            " if (!el) return 'missing';"
            f" const w = Math.round(el.getBoundingClientRect().width); if (w >= {wide})"
            "   return 'still ' + w;"
            " return document.documentElement.scrollWidth > window.innerWidth"
            "   ? 'overflow' : 'narrowed'; })()",
            "narrowed",
        )
        drive.check(
            narrowed == "narrowed",
            f"窄窗时输入框该跟着变窄且不横向溢出（宽窗 {wide}px），实测 {narrowed!r}",
        )
        window.resize(560, 520)
        # 进度条：轨道底实测就是 --track（砍掉 progress 规则时这条当场红），
        # 两种态在渲染上真的不同——不定态多一层来回移动的品牌色渐变，
        # determinate 没有（背景图 none），填充由 ::-webkit-progress-value 画。
        # 说明一句：填充本身量不到。原生控件的填充在 WebKit 与 Chromium 里都
        # 是引擎内部的伪元素，getComputedStyle(el, '::-webkit-progress-value')
        # 在两个引擎里都退回宿主元素的样式（实测过），页面脚本拿不到它的几何。
        # 所以这里断言的是「两种态各自的渲染确实不同 + 轨道与几何对」；填充
        # 宽度随 value 变化只能靠截图逐像素核，那一步在 msui 包侧做过，不进
        # 消费者的冒烟。
        drive.check_token_style(window, "progress#job", "backgroundColor", "track")
        # 描边也实测：凹陷式轨道自己陷进卡片底里（对 card 只有 1.13:1），槽的
        # 边界全靠这一圈 --border 画。描边一去，页面上就只剩一条飘着的红填充。
        drive.check_token_style(window, "progress#job", "borderTopColor", "border")
        bars = drive.wait_js(
            window,
            "(() => { const det = document.querySelector('progress#job');"
            " const ind = document.querySelector('progress#waiting');"
            " if (!det || !ind) return 'missing';"
            " const r = det.getBoundingClientRect();"
            " if (Math.round(r.height) !== 8) return 'height ' + r.height;"
            " if (r.width < 100) return 'width ' + r.width;"
            " if (Math.abs(det.position - 0.42) > 0.001) return 'position ' + det.position;"
            " if (getComputedStyle(det).appearance !== 'none') return 'native-look';"
            " if (getComputedStyle(det).backgroundImage !== 'none') return 'det-animated';"
            " if (!getComputedStyle(ind).backgroundImage.startsWith('linear-gradient'))"
            "   return 'ind-flat';"
            " return 'both'; })()",
            "both",
        )
        drive.check(bars == "both", f"进度条 determinate 与不定态该各自成立，实测 {bars!r}")
        # 提示条：四个状态的底色**实测**都等于对应 token 解出来的值（不是「css
        # 文本里写着这个变量名」——check_token_style 比的是渲染后的 computedStyle）。
        # error 那条连边框一起验：--error-strip-border 是它专属的一档。
        drive.check_token_style(window, ".notice.error", "backgroundColor", "error-bg")
        drive.check_token_style(window, ".notice.error", "borderTopColor", "error-strip-border")
        drive.check_token_style(window, "#retry", "borderTopColor", "error-strip-border")
        drive.check_token_style(window, ".notice.warn", "backgroundColor", "warn-bg")
        drive.check_token_style(window, ".notice.info", "backgroundColor", "info-bg")
        # 显示/隐藏的开关就是 hidden 属性。这条盯着一个具体的坑：`.notice` 自己
        # 一旦写了 display（作者层），UA 的 `[hidden] { display: none }` 就被盖掉，
        # 「收起来的提示条」会照样显示在页面上。先验它藏着时真的 display:none，
        # 再打开、验它真的显示出来且底色对。
        toggled = window.evaluate_js(
            "(() => { const el = document.getElementById('tip-ok');"
            " if (!el) return 'missing';"
            " if (getComputedStyle(el).display !== 'none') return 'visible-while-hidden';"
            " el.hidden = false;"
            " return getComputedStyle(el).display === 'none' ? 'stuck-hidden' : 'toggles'; })()"
        )
        drive.check(toggled == "toggles", f"提示条该靠 hidden 属性收放，实测 {toggled!r}")
        drive.check_token_style(window, "#tip-ok", "backgroundColor", "ok-bg")
        # 日志区：等宽字体真是 --font-mono 那一串（拿 token 解出的值比，不写死
        # 字体名）、长行不折、超长内容**真的横向滚得动**（改 scrollLeft 看它真
        # 的动了，比 scrollWidth > clientWidth 更硬），横滚条占掉的那几像素就是
        # 共用的那套 ::-webkit-scrollbar —— 只给它写 width 不写 height 时这条会
        # 红（滚得动，但那条横滚条是看不见的）。
        #
        # 粗细档从落地的 base.css 那条规则里取，不在探针里写死一个 10：本仓的
        # 口径是「档位从规则里取，两边不各写各的数」（进度条圆角、对话框圆角
        # 都是这么比的，见 tests/test_layout.py）。滚条上下的边框也一样，走
        # computedStyle 的 borderTopWidth/borderBottomWidth，不硬编那个 2。
        bar_step = scrollbar_thickness()
        drive.check(
            bar_step is not None,
            "落地的 base.css 里取不到 ::-webkit-scrollbar 的 height 档——"
            "横滚条会退回引擎默认粗细（本机 WebKit 17px），与竖条一粗一细",
        )
        drive.check_token_style(window, ".log", "backgroundColor", "win")
        logbox = drive.wait_js(
            window,
            "(() => { const el = document.getElementById('run-log');"
            " if (!el) return 'missing';"
            " const cs = getComputedStyle(el);"
            " const norm = s => s.replace(/[\"']/g, '').replace(/\\s+/g, '');"
            " const want = getComputedStyle(document.documentElement)"
            "   .getPropertyValue('--font-mono');"
            " if (norm(cs.fontFamily) !== norm(want)) return 'font ' + cs.fontFamily;"
            " if (cs.whiteSpace !== 'pre') return 'wraps ' + cs.whiteSpace;"
            " if (cs.maxHeight === 'none') return 'unbounded';"
            " if (el.scrollHeight <= el.clientHeight) return 'no-vscroll';"
            " if (el.scrollWidth <= el.clientWidth) return 'no-hscroll';"
            " el.scrollLeft = 999; const moved = el.scrollLeft; el.scrollLeft = 0;"
            " if (moved <= 0) return 'stuck';"
            " const borders = parseFloat(cs.borderTopWidth)"
            "   + parseFloat(cs.borderBottomWidth);"
            " const bar = el.offsetHeight - el.clientHeight - borders;"
            f" if (bar !== {bar_step if bar_step is not None else -1})"
            "   return 'hbar ' + bar;"
            " return 'scrolls'; })()",
            "scrolls",
        )
        drive.check(logbox == "scrolls", f"日志区该等宽、不折行、横向滚得动，实测 {logbox!r}")
        # 模态对话框：整段实测，不看 css 文本。
        # 1. 关着时 display:none（这条规则里写了任何 display 都会盖掉 UA 那条）；
        # 2. 开着时在视口里居中、宽度不超过 --content-max 且两侧留边；
        # 3. **遮罩真的挡住了底层**：底层挑一个按钮，滚到对话框上边缘之上（那块
        #    只有遮罩），命中测试在弹出前打得到它、弹出后打不到、关掉又打得到
        #    ——前后两次打得到是这条断言的自证，不然「打不到」可能只是探针点选错了；
        # 4. 遮罩底色实测 == --scrim；
        # 5. 里面的按钮行吃的是现成的 .actions —— 验的是「.actions 那套真的作用
        #    在它身上」：display 是 flex、两个按钮之间的实测间距等于它自己的
        #    computed gap。只验「两个按钮并排」是抓不住的：按钮默认就是
        #    inline-block，不挂 .actions 也会并排（差别只在那点空白字符宽度）。
        drive.check_token_style(window, "dialog", "backgroundColor", "card")
        modal = drive.wait_js(
            window,
            "(() => { const dlg = document.getElementById('confirm');"
            " const victim = document.querySelector('.field > button');"
            " if (!dlg || !victim) return 'missing';"
            " if (getComputedStyle(dlg).display !== 'none') return 'open-while-closed';"
            " dlg.showModal();"
            " const band = dlg.getBoundingClientRect();"
            " const norm = s => s.replace(/\\s+/g, '');"
            " const scrim = getComputedStyle(dlg, '::backdrop').backgroundColor;"
            " const want = getComputedStyle(document.documentElement)"
            "   .getPropertyValue('--scrim');"
            " const row = dlg.querySelector('.actions');"
            " const bs = row ? [...row.querySelectorAll('button')]"
            "   .map(e => e.getBoundingClientRect()) : [];"
            " const rowStyle = row ? getComputedStyle(row) : null;"
            " const gap = row ? parseFloat(rowStyle.columnGap) : NaN;"
            " dlg.close();"
            " if (norm(scrim) !== norm(want)) return 'backdrop ' + scrim;"
            " const vw = document.documentElement.clientWidth;"
            " const vh = document.documentElement.clientHeight;"
            " const cap = parseFloat(getComputedStyle(document.documentElement)"
            "   .getPropertyValue('--content-max'));"
            " if (band.width > cap) return 'too-wide ' + band.width;"
            " if (band.width >= vw) return 'edge-to-edge';"
            " if (Math.abs((band.left + band.right) / 2 - vw / 2) > 1) return 'off-center-x';"
            " if (Math.abs((band.top + band.bottom) / 2 - vh / 2) > 1) return 'off-center-y';"
            " if (bs.length !== 2) return 'no-actions-row';"
            " if (rowStyle.display !== 'flex') return 'actions-not-a-row';"
            " if (!(gap > 0)) return 'actions-no-gap';"
            " if (Math.abs(bs[0].top - bs[1].top) > 1) return 'actions-stacked';"
            " if (Math.abs(bs[1].left - bs[0].right - gap) > 1)"
            "   return 'actions-spacing ' + (bs[1].left - bs[0].right);"
            " const py = Math.max(4, Math.round(band.top / 2));"
            " window.scrollTo(0, 0);"
            " const t = victim.getBoundingClientRect();"
            " window.scrollBy(0, t.top + t.height / 2 - py);"
            " const r = victim.getBoundingClientRect();"
            " const cx = Math.round(r.left + r.width / 2);"
            " const cy = Math.round(r.top + r.height / 2);"
            " if (cy >= band.top) return 'probe-not-on-backdrop';"
            " if (document.elementFromPoint(cx, cy) !== victim) return 'victim-unreachable';"
            " dlg.showModal();"
            " const during = document.elementFromPoint(cx, cy);"
            " dlg.close();"
            " if (during === victim || victim.contains(during))"
            "   return 'backdrop-lets-clicks-through';"
            " if (document.elementFromPoint(cx, cy) !== victim) return 'stuck-blocked';"
            " return 'modal'; })()",
            "modal",
        )
        drive.check(modal == "modal", f"模态对话框该居中、遮罩挡住底层、按钮行吃 .actions，实测 {modal!r}")
        # 宽度上限单独在一扇宽窗里验：560 的窗里摘掉 max-width 也看不出区别
        # （518 本来就没到 520 这个上限），只有窗比上限宽时这条才谈得上。
        # 探针**要求**窗真的变宽了才放行（拉宽是异步的，不等到位就断言的话，
        # 上限这条会在窄窗里静静地绿）。
        window.resize(900, 600)
        capped = drive.wait_js(
            window,
            "(() => { const dlg = document.getElementById('confirm');"
            " if (!dlg) return 'missing';"
            " const vw = document.documentElement.clientWidth;"
            " const cap = parseFloat(getComputedStyle(document.documentElement)"
            "   .getPropertyValue('--content-max'));"
            " if (vw <= cap + 40) return 'window-not-wide-yet ' + vw;"
            " dlg.showModal(); const r = dlg.getBoundingClientRect(); dlg.close();"
            " if (Math.abs(r.width - cap) > 1) return 'not-capped ' + r.width;"
            " if (Math.abs(r.left + r.width / 2 - vw / 2) > 1) return 'off-center';"
            " return 'capped'; })()",
            "capped",
        )
        drive.check(capped == "capped", f"宽窗里对话框该停在 --content-max 并居中，实测 {capped!r}")
        window.resize(560, 520)
        # 文字可选：run() 默认 text_select=True，pywebview 不再往页面注入
        # `body { user-select: none }`——正文选得中、复制得出；按钮这类点的东西由
        # base.css 声明不可选。（WebKit 只认带前缀的那个属性，两个都读。）
        selectable = drive.wait_js(
            window,
            "(() => { const us = el => { const cs = getComputedStyle(el);"
            "   return cs.userSelect || cs.webkitUserSelect; };"
            " const p = document.querySelector('p'); const b = document.querySelector('button');"
            " if (!p || !b) return 'missing';"
            " return (us(p) === 'none' ? 'text-locked ' : 'text-ok ')"
            "   + (us(b) === 'none' ? 'button-ok' : 'button-selectable ' + us(b)); })()",
            "text-ok button-ok",
        )
        drive.check(
            selectable == "text-ok button-ok",
            f"正文该可选、按钮该不可选，实测 {selectable!r}",
        )
        # 应用式页面（app-layout.html）：步骤卡、读数卡、深浅切换。换页后等新页面的
        # 读数卡出现——旧页面没有 .kpis，不会把旧页面的 complete 误当成新页面的。
        window.load_url(str(serve_dir / "app-layout.html"))
        loaded = drive.wait_js(
            window,
            "document.readyState === 'complete' && !!document.querySelector('.kpis')"
            " ? 'ready' : 'loading'",
            "ready",
        )
        drive.check(loaded == "ready", f"app-layout.html 没加载出来，实测 {loaded!r}")
        # 没存过偏好（这一趟 run 没给 storage_dir，localStorage 是空的）→ 开窗即浅色。
        theme = drive.wait_js(
            window, "document.documentElement.dataset.theme || 'dark'", "light"
        )
        drive.check(theme == "light", f"没存过偏好时该开窗即浅色，实测 {theme!r}")
        # 步骤卡、读数卡真的吃到了 token 色（比的是浅色下页面实际解出来的值）。
        # 放在切主题之前：步骤卡的底色带 transition，隐藏窗里 transition 不推进，
        # 切完再读会读到过渡起点。
        drive.check_token_style(window, ".step.cur", "backgroundColor", "card")
        drive.check_token_style(window, ".step.done .num i", "backgroundColor", "brand")
        drive.check_token_style(window, ".step.done .num i", "color", "on-brand")
        drive.check_token_style(window, ".step.wait .title", "color", "muted")
        drive.check_token_style(window, ".eyebrow", "color", "muted")
        drive.check_token_style(window, ".kpi .val", "color", "text")
        drive.check_token_style(window, ".kpi.warn .val", "color", "warn")
        wrap = window.evaluate_js(
            "(() => { const td = document.querySelector('.grid td.wrap');"
            " return td ? getComputedStyle(td).whiteSpace : 'missing'; })()"
        )
        drive.check(wrap == "normal", f"整句列 td.wrap 该允许换行，实测 {wrap!r}")
        # 运行日志区：三组到齐后，最早的成功组收起、失败组展开、最新组展开；
        # 失败组铺 --error-bg；长行真的换行、不横滚；正文选得中。
        groups = drive.wait_js(
            window,
            "[...document.querySelectorAll('.runlog-run')].map(g =>"
            " (g.querySelector('.runlog-lines').hidden ? 'closed' : 'open')"
            " + ':' + g.querySelector('.st').textContent).join(' ')",
            "closed:成功 open:失败 open:成功",
        )
        drive.check(
            groups == "closed:成功 open:失败 open:成功",
            f"日志区该是旧组收起、失败组与最新组展开，实测 {groups!r}",
        )
        drive.check_token_style(window, ".runlog-run.error", "backgroundColor", "error-bg")
        drive.check_token_style(window, ".runlog-line.error .lv", "color", "error")
        long_line = window.evaluate_js(
            "(() => { const tx = [...document.querySelectorAll('.runlog-line .tx')]"
            "   .find(e => e.textContent.includes('sample-0001'));"
            " const list = document.querySelector('[data-runlog-list]');"
            " if (!tx || !list) return 'missing'; const cs = getComputedStyle(tx);"
            " if (cs.whiteSpace !== 'pre-wrap') return 'white-space ' + cs.whiteSpace;"
            " if (tx.getBoundingClientRect().height < parseFloat(cs.lineHeight) * 1.5)"
            "   return 'one-line';"
            " if (list.scrollWidth > list.clientWidth) return 'hscroll';"
            " const us = cs.userSelect || cs.webkitUserSelect;"
            " return us === 'none' ? 'locked' : 'wraps'; })()"
        )
        drive.check(long_line == "wraps", f"日志长行该换行、可选，实测 {long_line!r}")
        # 折叠后 Python 再记一条 error：日志区自动展开，偏好仍记着「折叠」。
        folded = window.evaluate_js(
            "(() => { const b = document.querySelector('[data-runlog-toggle]');"
            " if (!b) return 'missing'; b.click();"
            " return document.querySelector('[data-runlog-list]').hidden ? 'folded' : 'open'; })()"
        )
        drive.check(folded == "folded", f"点折叠后日志区该收起，实测 {folded!r}")
        runlog.error("折叠着来了一条失败")
        unfolded = drive.wait_js(
            window,
            "(() => { const list = document.querySelector('[data-runlog-list]');"
            " if (!list) return 'missing'; let saved;"
            " try { saved = localStorage.getItem('runlog-collapsed'); } catch (e) { saved = '?'; }"
            " return (list.hidden ? 'folded' : 'open') + ' ' + JSON.stringify(saved); })()",
            'open "1"',
        )
        drive.check(unfolded == 'open "1"', f"来了 error 该自动展开且不写回偏好，实测 {unfolded!r}")
        # 主题按钮：点一次翻到深色（图标换成太阳、localStorage 存 ''、提示改成
        # 「切换到浅色」），再点一次翻回浅色。
        flips = window.evaluate_js(
            "(() => { const b = document.querySelector('[data-theme-toggle]');"
            " if (!b) return 'missing';"
            " const shown = () => ['sun', 'moon'].filter(c =>"
            "   getComputedStyle(b.querySelector('.' + c)).display !== 'none').join('+');"
            " const state = () => { let saved; try { saved = localStorage.getItem('theme'); }"
            "   catch (e) { saved = 'unavailable'; }"
            "   return [document.documentElement.dataset.theme || 'dark', shown(),"
            "     JSON.stringify(saved), b.getAttribute('aria-label')].join(' '); };"
            " const before = state(); b.click(); const once = state(); b.click();"
            " return [before, once, state()].join(' / '); })()"
        )
        want = (
            "light moon null 切换到深色 / dark sun \"\" 切换到浅色"
            " / light moon \"light\" 切换到深色"
        )
        drive.check(flips == want, f"主题按钮该翻转主题、图标与偏好，实测 {flips!r}")
        # 横幅钉版：落地 css 第一行 == "/* msui <钉的版本> */"。横幅只证明
        # css 落了地，「页面吃进去了」由上面 check_token_style 证明，两条各管一半。
        banner = (serve_dir / "tokens.css").read_text(encoding="utf-8").splitlines()[0]
        drive.check(
            banner == f"/* msui {MSUI_PINNED} */",
            f"tokens.css 横幅该是 '/* msui {MSUI_PINNED} */'，实测 {banner!r}",
        )

    return smoke_script


def main() -> None:
    serve_dir = copy_assets(page_dir())  # 每次启动覆盖落样式，页面永远跟着装的这版 msui 走
    runlog = RunLog()  # 要按天落文件就给 log_dir=（比如 storage_dir 下的「日志」）
    demo_log(runlog)
    smoke = os.environ.get("APP_SMOKE") == "1"
    driver = SmokeDriver(make_smoke_script(serve_dir, runlog)) if smoke else None
    run(
        serve_dir / "index.html",
        js_api=Api(runlog),
        title="示例小程序",
        single_instance="msui-example-minimal",  # 连点图标只开一扇窗
        hidden=driver is not None,
        on_ready=driver,
    )
    if driver is not None:
        driver.exit()  # 有失败：逐条打印后退出码 1；全绿：打印「冒烟通过」


if __name__ == "__main__":
    main()
```

要点：

- `copy_assets` **无条件覆盖**地把 `tokens.css` + `base.css` + `tokens-light.css`
  + `theme.js` + `runlog.js` 落进页面目录并返回该开窗的目录——开窗一律用返回值，
  别写死 `page_dir`；`tokens-light.css`（浅色主题）、`theme.js`（深浅切换，§4）与
  `runlog.js`（运行日志区，§3）都是可选的，页面不引用它们就不起任何作用；
- 这几份副本不入仓、不手改（`pages/.gitignore` 把它们排除掉）；
- 钉版本的官方姿势就是上面的 `MSUI_PINNED` 常量 + 横幅断言：**钉死常量证明
  「产物带的确实是钉的这一版」，改读 `importlib.metadata` 只是回显装了哪版、
  永远绿**——升级 msui 时改两处（requirements 的 wheel URL + 这个常量），
  冒烟红了就是有一处忘了改；
- `run(...)` 还收 `width/height/min_size`、`icon=`、`storage_dir=` +
  `version=`（持久化与按版本清缓存）、`text_select=`（页面文字能否选中复制，
  默认 `True`）等关键字参数，按需加。

### 桥的页面侧：三件事

上面 Python 那半边只是把 `js_api=Api()` 递给 `run`、方法包上
`msui.bridge.Serializer`；页面那半边（完整代码在下一节 index.html 尾部的
`<script>` 里，可整段照抄）只有三件事：

1. **等 `pywebviewready` 再调**——`window.pywebview` 是窗口起来后才注入的，
   页面脚本一执行就去调必然 undefined；把首次调用挂在
   `window.addEventListener("pywebviewready", …)` 上。
2. **调用返回 Promise**——`window.pywebview.api.ping()` 这样调，`await` 拿到
   的就是 Python 方法的返回值（必须 JSON 可序列化）。Python 侧抛异常会变成
   这个 Promise 的 reject，前端 try/catch 兜底显示。
3. **忙碌信封就地丢弃**——方法包了 `Serializer` 时，应答统一是
   `{"busy": false, "data": …}` 信封；拿到 `busy: true` 表示上一次调用还在
   处理中，**就地 `return` 丢弃本次、绝不排队**（排队会把「连点五下」攒成
   执行五次）。

外加一条硬纪律：**页面里不许用 `confirm()` / `alert()` / `prompt()`**。这三个
是同步阻塞的对话框，弹着的那段时间**整个 webview 的消息循环停摆**——桥调用回
不来、进度回推卡住、窗口连重绘都不做，某些 WebView2 版本上还会连着宿主窗口一
起僵住。每个有破坏性动作的小程序都会先想到 `confirm("确定吗？")`，所以这条写
在这里：确认框用裸 `<dialog>` + `showModal()`（长相见下一节，代码见示例页），
它是页面自己的元素，模态由浏览器的 top layer 负责，主循环照跑。

### 单实例：连点图标只开一扇窗

`run(..., single_instance="<小程序 id>")`——**这个参数必填**（值用
`miniprog.toml` 的 id，全局唯一现成）。单实例是**默认模式**而不是可选装饰，
所以口子收在 API 上：

- **不传 → `TypeError`，窗压根开不了**。漏接入在编码期就炸，不留到用户连点
  图标开出 N 个窗才发现；
- **真要多开 → 显式写 `single_instance=False`**，守卫整段跳过。多开必须是
  写下来的决定，这就是它跟「漏传」的区别；
- **空串 / 纯空白 → `ValueError`**。空 id 会让 mutex 名退化成裸前缀
  `Local\msui-`，两个不同的小程序共用同一把锁、互相顶掉窗口——比不设守卫更糟，
  而且是静默的。

一条陷阱：**同一个进程里第二次 `run()` 用同一个 id，会被自己第一次的锁挡住**。
锁随进程活到死、没有释放函数（刻意的，见 `single_instance.py`）。测试里连开两扇
窗要给不同 id，或者传 `False`。

同 id 已有实例在跑时，第二个进程：

- **不建窗、不碰 storage、连 pywebview 都不 import**，`run(...)` 直接返回；
- 先尽力把已开的那扇窗按 `title` **带到前台**（Windows 对抢焦点有权限限制，
  带不动很正常）；
- 带不动就**静默退出**，日志一行。**绝不弹错误框**——用户按下图标的语义是
  「我想打开它」，弹错是在惩罚这个意图。

机制：Windows 命名 mutex（`Local\msui-<id>`），POSIX 用 flock 锁文件等价实现。
选内核对象而不是「锁文件存在即占用」就是为了**没有 stale 态**——上一次崩溃
或被任务管理器杀掉，不会把小程序永久锁死。加锁机制自身出错（权限、临时目录
不可写……）一律**放行**：守卫是来拦多余的窗的，不能成为「打不开」的新理由。

接冒烟时注意：守卫拦下时 `on_ready` 从不触发，`SmokeDriver` 会因此判
「冒烟脚本从未跑过」直接报失败（退出码 1），不会静静报绿。

## 3. 页面写语义 HTML

新页面不从空白起步——先抄这份**标准单列页骨架**。容器约定：**body 就是
容器**（边距、内容列宽 `--content-max`、垂直节奏全由 base.css 落在 body 上，
不存在也不需要 `.page` 之类的容器类；裸语义 HTML 零 class 就有边距与节奏）：

```html
<!-- examples/minimal/pages/skeleton.html -->
<!DOCTYPE html>
<!--
  标准单列页骨架：新页面从这几行起步，不写一行版式 CSS。
  容器约定：**body 就是容器**——边距、内容列宽（--content-max）、垂直节奏
  全由 base.css 落在 body 上；不存在也不需要 .page 之类的容器类，裸语义
  HTML 零 class 就有边距与节奏。.display 挂在主角读数上（增强，不是必需），
  没有主角读数的页面删掉那一行即可。
  卡片里只装按钮时给它同时挂 .actions：按钮横排、间距走档、窄窗自动折行；
  要让按钮居中，再加一个 .center。
  「表单 + 进度 + 日志」这种形态的页面从下面几块起步：一行三件（标签 + 输入框
  + 尾部按钮）给容器挂 .field；进度直接写裸 <progress>，不给 value 就是算不出
  百分比时的不定态；校验/结果提示挂 .notice + 一个状态（error/warn/info/ok），
  收放用 hidden 属性；跑批日志用 <pre class="log">（等宽、自己滚、长行横滚）。
  破坏性动作的确认用下面那个 <dialog> + showModal()，**绝不用 JS 的
  confirm()**（它会阻塞 webview 的消息循环）。用不上的整块删掉即可。
-->
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>应用名</title>
  <link rel="stylesheet" href="tokens.css">
  <link rel="stylesheet" href="base.css">
</head>
<body>
  <h1>应用名</h1>
  <p>一句话说明这个小工具是干什么的。</p>
  <output class="display">0</output>
  <div class="card">
    <div class="field">
      <label for="src">某某目录</label>
      <input id="src">
      <button>浏览</button>
    </div>
    <progress max="100" value="0"></progress>
    <p class="notice error" id="tip" hidden>校验没过的原因写这里。</p>
  </div>
  <div class="card">
    <pre class="log" id="log"></pre>
  </div>
  <div class="card actions">
    <button class="primary" id="start">主操作</button>
    <button>次要操作</button>
  </div>
  <dialog id="confirm">
    <h2>确定要继续吗？</h2>
    <p>这个动作不可逆，把后果写清楚：动了哪些文件、失败了要怎么收尾。</p>
    <div class="actions">
      <button id="confirm-no">取消</button>
      <button class="primary" id="confirm-yes">确定</button>
    </div>
  </dialog>
  <script>
    // 破坏性动作先弹模态确认，绝不用 confirm()（阻塞消息循环）。
    const dlg = document.getElementById("confirm");
    document.getElementById("start").addEventListener("click", () => dlg.showModal());
    document.getElementById("confirm-no").addEventListener("click", () => dlg.close("no"));
    document.getElementById("confirm-yes").addEventListener("click", () => {
      dlg.close("yes");
      document.getElementById("tip").hidden = true; // 提示条的收放就是 hidden
    });
  </script>
</body>
</html>
```

写裸 `button` / `input` / `table` / `a` / `h1` 就得到统一长相；任何颜色只经
`var(--token)` 取用，**不许手写十六进制色值**（第 5 步的闸门盯着）。完整
示例（骨架长开之后的样子，带桥调用）：

```html
<!-- examples/minimal/pages/index.html -->
<!DOCTYPE html>
<!--
  语义 HTML 约定：写裸 button / input / table 就得到统一长相；任何颜色只经
  var(--token) 取用，不手写十六进制色值（闸门测试盯着）。
  tokens.css / base.css 不入仓、不手改——启动时由 msui.resources.copy_assets
  落进本目录（无条件覆盖，头部带 msui 版本横幅）。
  要换色时才加 override.css：放本目录、只覆写同名 token 变量值，
  并在 base.css 之后加一行 <link rel="stylesheet" href="override.css">。
-->
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>示例小程序</title>
  <link rel="stylesheet" href="tokens.css">
  <link rel="stylesheet" href="base.css">
</head>
<body>
  <h1>示例小程序</h1>
  <p>下面全是裸标签：没有写任何一行自定义样式，长相与版式（边距、垂直节奏、
    居中的大读数）全来自共享的 base.css。</p>
  <output class="display">42</output>
  <div class="card">
    <h2>操作区</h2>
    <input placeholder="输入点什么">
  </div>
  <!-- 表单行：一行三件（标签 + 弹性输入框 + 尾部按钮）给容器挂 .field。
       标签定宽 → 多行竖排时输入框左边缘各自对齐；输入框吃掉剩余宽度，
       窗口拉大时跟着变宽；窄窗自动折行，不横向溢出。 -->
  <div class="card">
    <h2>表单区</h2>
    <div class="field">
      <label for="src">源目录</label>
      <input id="src" value="//nas/share/输入">
      <button>浏览</button>
    </div>
    <div class="field">
      <label for="dst">输出目录</label>
      <input id="dst" value="D:/导出">
      <button>浏览</button>
    </div>
  </div>
  <!-- 整张卡只装一行表单时，card 自己兼作 .field——与下面 card + actions
       是同一套写法，三行的输入框左边缘照样对齐。 -->
  <div class="card field">
    <label for="log">日志文件</label>
    <input id="log" value="D:/导出/run.log">
    <button>打开</button>
  </div>
  <!-- 进度条：裸 <progress> 就有长相，两种态都不用写样式。
       写了 value 是 determinate（按比例填充）；不给 value 就是不定态
       （算不出百分比时的样子，桥的 progress_percent 回 None 那种情形）。 -->
  <div class="card">
    <h2>进度区</h2>
    <progress id="job" max="100" value="42"></progress>
    <p>上面写了 value，按比例填充；下面不给 value，是算不出百分比时的不定态：</p>
    <progress id="waiting"></progress>
  </div>
  <!-- 整张卡只装按钮时，card 自己兼作 .actions（按钮横排、间距走档）。
       卡里还有别的内容时，按钮组另包一层 <div class="actions"> 即可，
       两种写法长相一致。 -->
  <div class="card actions" id="ops">
    <button class="primary">主操作</button>
    <button>次要操作</button>
  </div>
  <!-- 内联提示条：中性 .notice 加一个状态修饰（error / warn / info / ok）。
       底色走对应的 --*-bg 晕染、文字走同名实色，四行长文案也读得下去；
       行内可以直接跟一个按钮（错误态那个「重试」就是）。
       显示/隐藏就是 hidden 属性（el.hidden = true / false）——校验失败时显示、
       成功时收起，别自己写 display。 -->
  <div class="card">
    <h2>提示区</h2>
    <p class="notice error">校验没过：源目录与输出目录不能重叠。这样填的话搬迁会
      把刚写出去的文件当成新的输入再读一遍，第二轮之后目录里到底还剩什么谁也说
      不清；而且这个动作不可逆，出了事只能从备份恢复。请把输出目录挪到源目录之
      外，再点一次开始。 <button id="retry">重试</button></p>
    <p class="notice warn">共享盘上有 3 个文件正被别人占用，这一轮会跳过它们。</p>
    <p class="notice info">正在连共享盘，第一次连接可能要等十几秒。</p>
    <p class="notice ok" id="tip-ok" hidden>校验通过，可以开始了。（这一条起初带着
      hidden 属性，冒烟会把它打开：藏起来的提示条不许显示出来。）</p>
  </div>
  <!-- 定高滚动日志区：<pre class="log">。等宽（--font-mono 档）、自己滚、最高
       40vh；长行不折行、横向滚动——日志里全是长文件路径，折了眼睛没法扫。
       样例内容刻意写成不属于任何一个小程序的样子：这份文件是所有下游都要照
       着抄的契约，写成某一家的业务日志会让别人以为这套长相是给那类业务定的。
       这里要证明的只有一件事——长行不折、横向滚得动。 -->
  <div class="card">
    <h2>日志区</h2>
    <pre class="log" id="run-log">10:12:03 扫描 //fileserver/share/归档/2024/第一季度/原始数据/批次A（外协）/sample-0001_20240131.dat
10:12:03 命中 目录年月=2024-01 批次=A 序号=0001
10:12:04 复制 -> D:/导出/2024/01/批次A/sample-0001_20240131.dat
10:12:04 扫描 //fileserver/share/归档/2024/第一季度/原始数据/批次A（外协）/sample-0002.dat
10:12:05 警告 文件名里没有日期，退回目录年月 2024-01
10:12:05 复制 -> D:/导出/2024/01/批次A/sample-0002_202401.dat
10:12:06 扫描 //fileserver/share/归档/2024/第二季度/原始数据/批次B（返工）/sample-0003_20240212.dat
10:12:06 跳过 文件正被别人占用（WinError 32），记进报告的警告表
10:12:07 扫描 //fileserver/share/归档/2024/第二季度/原始数据/批次B（返工）/sample-0004_20240212.dat
10:12:07 复制 -> D:/导出/2024/02/批次B/sample-0004_20240212.dat
10:12:08 汇总 418 个文件：414 个成功，3 个被占用跳过，1 个需要人工确认
10:12:08 报告 -> D:/导出/运行报告_20240212_101208.xlsx
10:12:08 完成 用时 4 分 51 秒
</pre>
  </div>
  <!-- 破坏性动作的确认走模态 <dialog> + showModal()，**不用 JS 的 confirm()**
       （它会阻塞 webview 的消息循环：桥调用、进度回推、重绘全停摆）。
       对话框里的按钮行直接挂 .actions，不另造一套。 -->
  <div class="card">
    <h2>破坏性动作</h2>
    <p>下面这个按钮弹一张模态确认，遮罩会把底层压下去（压着时底层点不动）。</p>
    <button id="danger">搬迁文件夹…</button>
  </div>
  <div class="card">
    <h2>桥演示</h2>
    <p>点按钮经 js_api 桥调 Python，应答回显在这里：
      <output id="pong">（等待 pywebviewready）</output></p>
    <button id="ping">调一下 Python</button>
  </div>
  <table>
    <thead><tr><th>名称</th><th>状态</th></tr></thead>
    <tbody>
      <tr><td>任务一</td><td>已完成</td></tr>
      <tr><td>任务二</td><td>进行中</td></tr>
    </tbody>
  </table>
  <small>底部弱化文字，带一个<a href="#">链接</a>。</small>
  <dialog id="confirm">
    <h2>确定要搬迁吗？</h2>
    <p>这个动作不可逆：源目录里的文件是被<b>移走</b>，不是复制。共享盘上正被别人
      打开的文件会跳过，并记进报告的警告表。</p>
    <p>这一轮受影响的是 418 个文件，预计三到五分钟。中途关窗会留下一个搬了一半
      的目录，只能对着报告手工收尾。</p>
    <div class="actions">
      <button id="confirm-no">取消</button>
      <button class="primary" id="confirm-yes">确定搬迁</button>
    </div>
  </dialog>
  <script>
    // 桥的页面侧三件事（详见 README「桥的页面侧」一节）：
    // 1. pywebviewready 之后才允许调用（js_api 注入完成的信号）；
    // 2. window.pywebview.api.xxx() 返回 Promise，await 拿 Python 返回值；
    // 3. 应答是 Serializer 信封，busy=true 表示上一次还在处理——就地丢弃。
    const pongEl = document.getElementById("pong");
    async function ping() {
      const reply = await window.pywebview.api.ping();
      if (reply.busy) return; // 忙碌信封：丢弃本次，不排队
      pongEl.textContent = reply.data;
    }
    document.getElementById("ping").addEventListener("click", ping);
    window.addEventListener("pywebviewready", ping);
    // 破坏性动作的确认：showModal() 弹模态，取消/确定都只是 close()。
    // 绝不用 confirm()——它会阻塞 webview 的消息循环。
    const dlg = document.getElementById("confirm");
    document.getElementById("danger").addEventListener("click", () => dlg.showModal());
    document.getElementById("confirm-no").addEventListener("click", () => dlg.close("no"));
    document.getElementById("confirm-yes").addEventListener("click", () => dlg.close("yes"));
  </script>
</body>
</html>
```

展示型大读数（计数器、倒计时这类页面的主角数字）给承载元素挂 `.display`
类：成块居中、字号走 tokens 的 `--font-display` 档（48px）、数字等宽不晃动、
上下自带一档内衬，照样零自定义样式。

一组按钮给它们的容器挂 `.actions`：横排、间距走 `--space-3` 档、窄窗自动
折行。**默认左对齐**（跟着文字流的左边缘最好扫）；要居中再加一个 `.center`。
容器可以是卡片自己（`<div class="card actions">`，整张卡只装按钮时），也可以
是卡片里单独包的一层（卡里还有标题、输入框这些别的内容时）。别自己写
`text-align` / `display: flex` ——不挂 `.actions` 的按钮会竖着堆起来，那是
卡片的垂直节奏在起作用，不是缺样式。

一行「标签 + 输入框 + 尾部按钮」给它们的容器挂 `.field`：

- 标签定宽走 `--field-label` 档（96px），**多行表单竖排时输入框的左边缘靠
  这一个值对齐**——每行各写各的宽度就会参差不齐；标签更长的页面用
  `override.css` 覆写这一个变量，别去改行内样式；
- 输入框吃掉剩余宽度（窗口拉大时跟着变宽，长路径不被截断），尾部按钮不被
  压扁，输入框与按钮**顶边齐平、等高**；
- 窄窗自动折行、不横向溢出；多行之间的行距走卡片的垂直节奏，不用自己加
  `margin`。

容器同样可以是卡片自己（`<div class="card field">`，整张卡只装一行时）或卡片
里单独包的一层，两种写法长相一致——与 `.actions` 是同一套规矩。

进度直接写裸 `<progress>`，两种态都不用写一行样式：

- 写了 `value` 是 determinate，按 `value / max` 的比例填充（轨道 `--track`、
  进度 `--brand`、圆角与按钮同一档、默认占满内容列宽）；
- **不给 `value` 就是不定态**——算不出百分比（桥那边回 `None`）时，页面要做的
  就是把 `value` 属性去掉（`el.removeAttribute("value")`），得到一条来回移动
  的品牌色，宽度不表示任何进度；
- 不定态那圈动画跟着系统的「减少动态效果」走：勾上之后条子静止。这需要在
  `prefers-reduced-motion` 那段里**单独点名** `::-webkit-progress-bar`——通配符
  选择器匹配不到引擎内部的伪元素，只写 `*` 的话动画照跑（base.css 里已经点了，
  自己另写动画时记着这条）；
- 轨道是**凹陷式**的：`--track` 比卡片更暗（不是罩在卡片上的提亮罩），紧挨着
  它的填充才过得了控件档 3.0:1；轨道自己陷进底色里、边界看不见，所以另有一圈
  1px `--border` 描边把槽画出来。换品牌色时 `--brand` 对 `--track` 是全表余量
  最小的组合之一，改之前照 tokens.css 里 `--track` 那段记的实测数字算一遍；
- WebKit（开发机）与 Chromium/WebView2（目标平台）走的是同一对伪元素，两边
  长相一致——填充几何与色值逐像素核对过。

破坏性动作（覆盖、搬迁、删除）的确认写裸 `<dialog>`，用 `showModal()` 弹：

```html
<button id="go">搬迁文件夹…</button>
<dialog id="confirm">
  <h2>确定要搬迁吗？</h2>
  <p>把后果写清楚：动了哪些文件、失败了怎么收尾。三四行都读得下去。</p>
  <div class="actions">
    <button id="no">取消</button>
    <button class="primary" id="yes">确定搬迁</button>
  </div>
</dialog>
```

- 长相全自带：遮罩（`::backdrop` 走 `--scrim`）、视口居中、卡片式容器、宽度
  上限跟着 `--content-max`（与正文列同宽，长说明的行长跟页面里的段落一个手感）、
  说明太长时对话框自己滚；
- 里面的按钮行**直接挂 `.actions`**，别另造一套——横排、间距走档、窄窗折行都
  是现成的；
- **不许用 JS 的 `confirm()`**（理由见上一节最后那段：它阻塞 webview 的消息
  循环）。`showModal()` 打开、`close()` 关闭，要拿结果读 `dialog.returnValue`。

校验没过、跑完了这类**内联提示**挂 `.notice` 加一个状态修饰：

```html
<p class="notice error">校验没过：源目录与输出目录不能重叠……</p>
<p class="notice ok" id="tip" hidden>校验通过，可以开始了。</p>
```

- 四个状态 `error` / `warn` / `info` / `ok`：底走对应的半透明晕染
  （`--error-bg` 这一系），文字走同名实色，四行长文案也读得下去；
- **显示/隐藏就是 `hidden` 属性**（`el.hidden = true / false`）——校验失败时
  显示、成功时收起。别给 `.notice` 加 `display`：那会盖掉 `[hidden]`，藏起来
  的提示条会照样显示出来；
- 错误条里可以直接跟一个行内 `<button>`（典型是「重试」），它会跟着条子一起
  染红，不用另写样式。

跑批日志用 `<pre class="log">`：等宽字体（`--font-mono` 档）、自己滚、最高
40vh，**长行不折行、横向滚动**——日志里全是长文件路径，折了眼睛没法顺着扫。
要它占满剩余高度就覆写 `max-height`（或改 `height`），滚动条是全局那一套，
不用管。

### 应用式版式（opt-in）：宽表格程序整窗即容器

上面那套「body 就是容器」是给 560×520 小工具窗的：内容列停在 `--content-max`
居中，窗口拉大两边空着。左栏参数 + 右边几十列宽表格这种程序要的是另一种形态，
**给 body 挂 `class="app"` 开启**（纯 CSS，`run()` 一个参数不用改）。不挂的
页面一条新规则都命中不到，小工具窗一个像素不变。骨架照抄这份：

```html
<!-- examples/minimal/pages/app-layout.html -->
<!DOCTYPE html>
<!--
  应用式版式骨架（opt-in）：宽表格程序（左栏参数 + 右边几十列的表）从这里起步。
  开关就是 <body class="app">——整窗即容器：顶栏 / 多栏主体 / 状态栏三段贴边
  拼满整窗，内容区各自滚，body 自己不滚。不挂 class="app" 的页面还是 560×520
  小工具窗那套（skeleton.html），一个像素不变。
  三段：
  - 顶栏 <header class="top">：程序名 + 分段 .seg + 弹簧 .grow + 徽章 .pill +
    深浅切换按钮（button.icon[data-theme-toggle]，配 <head> 里的 tokens-light.css
    与 theme.js；没存过偏好时开窗即浅色）；
  - 多栏 <div class="cols">：左栏 .rail 定宽（--rail-width）、主区 .pane 吃剩余
    宽度，两边各自滚；窄窗（< 900px）左栏自动退到上面。没有左栏的页面删掉
    <aside>，.pane 留着即可；
  - 状态栏 <footer class="status">：版本 / 数据目录 / 当前状态一条细栏。
  左栏是一串步骤卡 .step（.done 已完成 / .cur 当前 / .wait 等待，卡里放说明
  .meta、参数 .param、动作 .act、进度条），上面一行小标题 .eyebrow；主区一排读数卡
  .kpis / .kpi（空态写破折号、警示态 .warn），数据网格里放整句话的列挂 td.wrap；
  主区底部是运行日志区 section.runlog[data-runlog]（配 </body> 前的 runlog.js 与
  Python 侧 js_api 的 get_log：按一次运行分组、两层折叠）。
  进场动效给块挂 .fade-in，要错峰就在元素上写 style="--i: 序号"；系统开了
  「减少动态效果」时自动静止。用不上的整块删掉即可。
-->
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>应用名</title>
  <link rel="stylesheet" href="tokens.css">
  <link rel="stylesheet" href="base.css">
  <link rel="stylesheet" href="tokens-light.css">
  <script src="theme.js"></script>
</head>
<body class="app">
  <header class="top">
    <h1>应用名</h1>
    <div class="seg" id="views">
      <button class="on" aria-pressed="true">视图甲</button>
      <button aria-pressed="false">视图乙</button>
    </div>
    <span class="grow"></span>
    <span class="pill info">2024-01-31</span>
    <span class="pill ok">已同步</span>
    <button class="icon" type="button" data-theme-toggle aria-label="切换深色 / 浅色">
      <svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
      <svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
    </button>
  </header>
  <div class="cols">
    <aside class="rail" id="steps">
      <div class="eyebrow"><span class="t">流程</span><span class="n">第 2 步 / 共 3 步</span></div>
      <div class="step done" tabindex="0" role="button">
        <div class="head"><span class="num"><i>1</i></span><span class="title">读取数据</span></div>
        <p class="meta">已读 <b>6</b> 张表。</p>
        <p class="meta good">全部识别成功。</p>
      </div>
      <div class="step cur" tabindex="0" role="button">
        <div class="head"><span class="num"><i>2</i></span><span class="title">设定范围</span></div>
        <div class="param">
          <label for="from">起始月</label>
          <input id="from" placeholder="YYYY-MM">
          <label for="src">数据目录</label>
          <div class="row"><input id="src"><button>浏览</button></div>
        </div>
        <p class="meta hint">结束月留空 = 到最新一个月。</p>
        <div class="act"><button class="primary">运行</button><button>重置</button></div>
        <progress value="42" max="100"></progress>
      </div>
      <div class="step wait" tabindex="0" role="button">
        <div class="head"><span class="num"><i>3</i></span><span class="title">导出</span></div>
        <p class="meta">上一步跑完才能导出。</p>
        <p class="meta fail" hidden>导出失败：目标文件被占用。</p>
        <div class="act"><button disabled>导出结果</button></div>
      </div>
    </aside>
    <main class="pane">
      <h2>结果</h2>
      <p>主区自己滚；宽表格放这里，窗口拉多大就摊多宽。</p>
      <div class="kpis">
        <div class="card kpi fade-in" style="--i: 0">
          <div class="lbl">合计</div>
          <div class="val">128<small>件</small></div>
          <div class="sub"><span>甲 96</span><span>乙 32</span></div>
        </div>
        <div class="card kpi fade-in" style="--i: 1">
          <div class="lbl">已完成</div>
          <div class="val">120<small>件</small></div>
          <div class="sub">占合计 94%</div>
        </div>
        <div class="card kpi warn fade-in" style="--i: 2">
          <div class="lbl">告警</div>
          <div class="val">8<small>条</small></div>
          <div class="sub">需要人工确认</div>
        </div>
        <div class="card kpi fade-in" style="--i: 3">
          <div class="lbl">待导出</div>
          <div class="val">—</div>
          <div class="sub"><span class="dim">还没读取数据，先跑第 1 步。</span></div>
        </div>
      </div>
      <div class="card fade-in" style="--i: 4">
        <div class="eyebrow"><span class="t">明细</span><span class="n">2 条</span><span class="grow"></span><button>导出</button></div>
        <div class="grid">
          <table>
            <thead><tr><th>名称</th><th>状态</th><th>说明</th></tr></thead>
            <tbody>
              <tr><td>条目一</td><td><span class="pill ok">完成</span></td><td class="wrap">按默认范围读取：D:/数据/2024/01/条目一_明细_最终版.xlsx</td></tr>
              <tr><td>条目二</td><td><span class="pill warn">待确认</span></td><td class="wrap">数量与上一轮相差超过一成，请核对来源表后再导出。</td></tr>
            </tbody>
          </table>
        </div>
      </div>
      <section class="runlog" data-runlog="get_log" aria-label="运行日志">
        <div class="eyebrow"><span class="t">运行日志</span><span class="n" data-runlog-count></span><span class="grow"></span><button type="button" data-runlog-clear>清空显示</button><button type="button" data-runlog-toggle aria-expanded="true">折叠</button></div>
        <div class="runlog-list" data-runlog-list></div>
      </section>
    </main>
  </div>
  <footer class="status">
    <span>v1.0.0</span>
    <span>数据目录 D:/数据</span>
    <span class="grow"></span>
    <span>就绪</span>
  </footer>
  <script src="runlog.js"></script>
  <script>
    // 分段选择：当前项挂 .on，aria-pressed 跟着写对。
    const views = document.getElementById("views");
    views.addEventListener("click", (event) => {
      const picked = event.target.closest("button");
      if (!picked) return;
      for (const button of views.querySelectorAll("button")) {
        const on = button === picked;
        button.classList.toggle("on", on);
        button.setAttribute("aria-pressed", String(on));
      }
    });
    // 步骤卡：点一下（或 Tab 过去按 Enter / 空格）切成当前步；卡里的按钮、输入框照常用。
    const steps = document.getElementById("steps");
    const pick = (step) => {
      for (const s of steps.querySelectorAll(".step")) s.classList.toggle("cur", s === step);
    };
    steps.addEventListener("click", (event) => {
      if (event.target.closest("button, input")) return;
      const step = event.target.closest(".step");
      if (step) pick(step);
    });
    steps.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      if (!event.target.classList.contains("step")) return;
      event.preventDefault();
      pick(event.target);
    });
  </script>
</body>
</html>
```

- **三段贴边拼满整窗**：顶栏 `.top` / 多栏 `.cols` / 状态栏 `.status`，body 自己
  不滚，滚的是左栏 `.rail` 与主区 `.pane`——这样顶栏和状态栏永远钉在窗口上下；
- **多栏**：左栏定宽走 `--rail-width`（300px，左栏内容宽窄不同就用 override.css
  覆写这一个变量）、主区吃掉剩余宽度。窄窗（< 900px）左栏自动退到上面、最高
  40vh 自己滚。没有左栏的页面把 `.pane` 直接挂在 body 下也成立；
- 自己往骨架里加 flex 容器时记着两处归零（base.css 里 `.cols` / `.pane` 已经
  写了）：竖向 flex 子项要 `min-height: 0`、横向要 `min-width: 0`，漏了不报错，
  表现是滚动条出不来、宽表格把整窗撑出横滚条；
- 主区里的块间距、标题与说明段的紧排与小窗同一套，照写裸语义 HTML；
- 应用式页面里 `hidden` 属性一律压过作者写的 `display`（小窗仍然是「别给要
  收放的东西写 display」那条约定）；Tab 走到的控件有一圈 `--info` 焦点环。

顶栏里的两样部件**不限于应用式**，小窗里也能用：

- **分段选择 `.seg`**：两三个互斥选项挤在一条槽里，当前项挂 `.on`（同时把
  `aria-pressed` 写对）。与总程序首页的分段按钮同一副长相；
- **徽章 `.pill`**：一小颗胶囊报日期 / 计数 / 状态。裸 `.pill` 是中性档，四个
  状态 `ok` / `warn` / `info` / `error` 与 `.notice` 同一套配色；收放同样用
  `hidden`，别给它写 `display`；
- **弹簧 `.grow`**：flex 行里把后面的东西推到最右（顶栏把徽章推到右端就靠它）。

卡片、区块进场时要一点动静就挂 **`.fade-in`**（上浮 6px 淡入，240ms）；一组要
错峰时在元素上写 `style="--i: 序号"`，每档晚 40ms。系统开了「减少动态效果」时
自动静止、直接以终态出现，不用自己处理。

### 左栏步骤卡、读数卡、小标题、整句列

上面 app-layout.html 的左栏和主区里还用了五样部件（0.11.0 起）。和 `.seg` /
`.pill` 一样**是部件不是版式**，小窗里也能用；全是新类名，没写过它们的页面
一个像素不变。每样一段写法：

**区块小标题 `.eyebrow`**——卡片与左栏里给一块内容起名。标题包进 `.t` 就不会
被后面的长说明挤成两行；计数 `.n` 次要色；右侧按钮用 `.grow` 推过去：

```html
<!-- examples/minimal/pages/app-layout.html 片段 -->
<div class="eyebrow"><span class="t">明细</span><span class="n">2 条</span><span class="grow"></span><button>导出</button></div>
```

**左栏步骤卡 `.step`**——编号圆圈、标题、一句说明、动作按钮：

```html
<!-- examples/minimal/pages/app-layout.html 片段 -->
<div class="step cur" tabindex="0" role="button">
  <div class="head"><span class="num"><i>2</i></span><span class="title">设定范围</span></div>
  <div class="param">
    <label for="from">起始月</label>
    <input id="from" placeholder="YYYY-MM">
    <label for="src">数据目录</label>
    <div class="row"><input id="src"><button>浏览</button></div>
  </div>
  <p class="meta hint">结束月留空 = 到最新一个月。</p>
  <div class="act"><button class="primary">运行</button><button>重置</button></div>
  <progress value="42" max="100"></progress>
</div>
```

- 三态挂在 `.step` 上：`.done` 已完成（编号实心品牌色）、`.cur` 当前（卡片底 +
  描边）、`.wait` 等待（前一步没完成）；都不挂是「可做未做」。既完成又是当前
  （用户点回去看）两个都挂，编号保持实心；
- **等待态不用 opacity**：标题、说明、编号统一换 `--muted`，对比度闸门算得出来。
  里面的按钮该 `disabled` 就写 `disabled`；
- 说明行 `.meta` 小字弱化、长路径自动断开，里面 `<b>` 是要点；三种语义色
  `.meta.fail`（失败）/ `.meta.hint`（提示）/ `.meta.good`（正常）；收放用 `hidden`；
- 动作行 `.act`：窄左栏里自动折行、按钮撑满；
- 参数行 `.param`：标签在上、输入框占满（左栏放不下 `.field` 那种左右排）；
  输入框后面要跟按钮时包一层 `.row`；
- 卡内直接放裸 `<progress>`；
- 整块可点（点了切换主区）就写 `tabindex="0" role="button"`，Enter / 空格由页面
  接（示例页尾部的脚本）：手形光标、悬停换边、焦点环与 `body.app` 同一档。

**读数卡 `.kpis` / `.kpi`**——主区一排「小标签 + 大数字 + 单位 + 副行」，四列
等宽、窄窗（< 900px）退到两列：

```html
<!-- examples/minimal/pages/app-layout.html 片段 -->
<div class="kpis">
  <div class="card kpi fade-in" style="--i: 0">
    <div class="lbl">合计</div>
    <div class="val">128<small>件</small></div>
    <div class="sub"><span>甲 96</span><span>乙 32</span></div>
  </div>
  <div class="card kpi fade-in" style="--i: 1">
    <div class="lbl">已完成</div>
    <div class="val">120<small>件</small></div>
    <div class="sub">占合计 94%</div>
  </div>
  <div class="card kpi warn fade-in" style="--i: 2">
    <div class="lbl">告警</div>
    <div class="val">8<small>条</small></div>
    <div class="sub">需要人工确认</div>
  </div>
  <div class="card kpi fade-in" style="--i: 3">
    <div class="lbl">待导出</div>
    <div class="val">—</div>
    <div class="sub"><span class="dim">还没读取数据，先跑第 1 步。</span></div>
  </div>
</div>
```

- 副行里并排的几个 `<span>` 之间自动加「·」；
- **空态**：还没有数据时卡照样摆着，`.val` 写破折号「—」，副行包一层 `.dim`
  写一句弱化提示——别把卡藏起来，卡的位置本身在告诉人「会有这几个数」；
- **警示态** `.kpi.warn`：数字换警示色。

**数据网格里的整句列 `td.wrap`**——`.grid` 的单元格默认不折行（宽表靠横滚读）；
说明、路径、原因这类放整句话的列，给单元格挂 `class="wrap"` 就允许换行、长路径
在任意处断开（最窄 16em，不会被挤成一条竖线）：

```html
<!-- examples/minimal/pages/app-layout.html 片段 -->
<tr><td>条目二</td><td><span class="pill warn">待确认</span></td><td class="wrap">数量与上一轮相差超过一成，请核对来源表后再导出。</td></tr>
```

**深浅切换按钮**——顶栏右端那颗 `button.icon[data-theme-toggle]`，写法和接法见
§4「深浅切换按钮」。

**文字可选**：`run()` 默认让页面文字可以选中复制（日志、告警、表格里的字能贴给
同事或 AI）；按钮、分段、徽章、筛选片、开关、`<label>` 由 base.css 声明不可选，
点击时不会误选中文字。确实不想让文字可选的程序 `run(..., text_select=False)`。

### 列表页 / 设置页部件：工具条、筛选片、搜索框、数据网格、图标按钮、开关、状态点

清单 / 设置这类页面常用的七样，**都是部件不是版式**：小工具窗与应用式
（`<body class="app">` 的 `.pane` 里）都能用，不写一行样式；全是新类名，
没写过它们的旧页面一个像素不变。照抄这份：

```html
<!-- examples/minimal/pages/widgets.html -->
<!DOCTYPE html>
<!--
  列表页 / 设置页部件：工具条 + 筛选片 + 搜索框、数据网格、图标按钮、开关、状态点。
  全是部件不是版式：小工具窗（这一页）与应用式（<body class="app"> 的 .pane 里）
  都能用，不写一行样式。
  - 工具条 .toolbar：一行排开、窄窗折行，右推用 .grow；
  - 筛选片 .chip：当前项挂 .on（同时把 aria-pressed 写对），右侧 .n 是计数；
  - 搜索框 .search：框画在 label 上，里面放放大镜 svg + 无框 input + 清除叉
    （有内容时才 hidden = false）；
  - 数据网格 .grid：包一层就有横竖滚 + 粘表头；数字列 td / th 挂 .num 右对齐，
    选中行挂 tr.sel；
  - 图标按钮 button.icon：只放一个内联 svg，stroke / fill 写 currentColor，
    aria-label 写明动作。**不用 Unicode 箭头**（Windows 字体里常缺字形）；
  - 开关 button.switch：role="switch"，点一下翻 aria-checked；文字用
    <label for> 指过去，点字也能切；
  - 状态点 .dot：裸 .dot 是中性点，ok / warn / info / error 四个状态。
  这几样收放都用 hidden 属性，别给它们写 display。用不上的整块删掉即可。
-->
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>应用名</title>
  <link rel="stylesheet" href="tokens.css">
  <link rel="stylesheet" href="base.css">
</head>
<body>
  <h1>清单</h1>
  <p>筛选、搜索、选中一行再上下挪。</p>
  <div class="toolbar" id="filters">
    <button class="chip on" aria-pressed="true">全部<span class="n">3</span></button>
    <button class="chip" aria-pressed="false">待处理<span class="n">1</span></button>
    <label class="search">
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5 14 14"/></svg>
      <input type="search" id="q" placeholder="搜索名称">
      <button class="icon" type="button" id="q-clear" aria-label="清除" hidden>
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>
      </button>
    </label>
    <span class="grow"></span>
    <button class="icon" aria-label="上移">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 13V3M4 7l4-4 4 4"/></svg>
    </button>
    <button class="icon" aria-label="下移">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 3v10M4 9l4 4 4-4"/></svg>
    </button>
  </div>
  <div class="grid">
    <table>
      <thead><tr><th>名称</th><th>状态</th><th class="num">数量</th><th class="num">金额</th></tr></thead>
      <tbody id="rows">
        <tr><td>条目一</td><td><span class="dot ok">完成</span></td><td class="num">1,200</td><td class="num">36.50</td></tr>
        <tr class="sel"><td>条目二</td><td><span class="dot warn">待确认</span></td><td class="num">85</td><td class="num">4.20</td></tr>
        <tr><td>条目三</td><td><span class="dot error">失败</span></td><td class="num">0</td><td class="num">0.00</td></tr>
      </tbody>
    </table>
  </div>
  <div class="card">
    <div class="toolbar">
      <button class="switch" role="switch" aria-checked="true" id="backup"></button>
      <label for="backup">每天自动备份</label>
    </div>
    <div class="toolbar">
      <button class="switch" role="switch" aria-checked="false" id="notify"></button>
      <label for="notify">跑完弹通知</label>
    </div>
  </div>
  <script>
    // 筛选片：单选，当前项挂 .on、aria-pressed 跟着写对。
    const filters = document.getElementById("filters");
    filters.addEventListener("click", (event) => {
      const picked = event.target.closest(".chip");
      if (!picked) return;
      for (const chip of filters.querySelectorAll(".chip")) {
        const on = chip === picked;
        chip.classList.toggle("on", on);
        chip.setAttribute("aria-pressed", String(on));
      }
    });
    // 搜索框：有内容才露出清除叉。
    const q = document.getElementById("q");
    const clear = document.getElementById("q-clear");
    q.addEventListener("input", () => { clear.hidden = q.value === ""; });
    clear.addEventListener("click", () => { q.value = ""; clear.hidden = true; q.focus(); });
    // 数据网格：点一行选中（tr.sel）。
    const rows = document.getElementById("rows");
    rows.addEventListener("click", (event) => {
      const row = event.target.closest("tr");
      if (!row) return;
      for (const tr of rows.rows) tr.classList.toggle("sel", tr === row);
    });
    // 开关：长相只认 aria-checked，点一下翻过去。
    for (const sw of document.querySelectorAll(".switch")) {
      sw.addEventListener("click", () => {
        const on = sw.getAttribute("aria-checked") !== "true";
        sw.setAttribute("aria-checked", String(on));
      });
    }
  </script>
</body>
</html>
```

- **工具条 `.toolbar`**：一行排开、垂直居中、窄窗折行；右推用 `.grow`。
  `<div class="card toolbar">` 整卡即一条也成立（与 `.actions` 同一个规矩）；
- **筛选片 `.chip`**：胶囊形按钮，当前项挂 `.on`（单选时同时把
  `aria-pressed` 写对），右侧 `<span class="n">` 是计数；
- **搜索框 `.search`**：框画在 `<label>` 上，里面放放大镜 svg + 无框 input；
  清除叉是一颗 `button.icon`，有内容时才 `hidden = false`（原生 type=search
  自带的那个浅灰叉不吃 token，已经摘掉）；
- **数据网格 `.grid`**：给普通 `<table>` 包一层 `<div class="grid">`，就有横竖
  滚（限高 46vh，要更高就覆写 `max-height`）+ 粘表头 + 单元格不折行；数字列
  的 td / th 挂 `.num` 右对齐；选中行挂 `tr.sel`（提亮 + 左侧 3px 品牌色条）；
- **图标按钮 `button.icon`**：28px 正方形，边框、hover、按下回弹全沿用通用
  按钮。图标**一律内联 svg**，stroke / fill 写 `currentColor`（按钮的字色、
  hover 变亮都跟着变），`aria-label` 写明动作。**不用 Unicode 箭头 / 符号字**
  （`↥` `⤒` 这类在 Windows 的 Segoe UI 里没有字形，会掉成方块）；
- **开关 `button.switch`**：`role="switch"`，长相只认 `aria-checked`——点一下
  在 `"true"` / `"false"` 之间翻，读屏也读它，两边不会对不上。文字用
  `<label for>` 指过去，点字也能切。关态是凹陷槽（同进度条），开态品牌色，
  深浅两套都过对比度闸门；
- **状态点 `.dot`**：`<span class="dot ok"></span>已同步`，或把字包进去
  `<span class="dot ok">已同步</span>`。裸 `.dot` 是中性点，四个状态
  `ok` / `warn` / `info` / `error` 与 `.pill` 同一套名字；
- 这几样收放一律用 `hidden`，**别给它们写 `display`**（同 `.notice`）。

**数据网格的坑：冒烟里别按列下标取值。** 表格加一列、挪一列是常事，冒烟里
写 `row.cells[3]` 的话，列位置一变，后面每一列的断言**整体错一位**——而且
往往不报错，只是拿「金额」去比「数量」，错得悄无声息。按表头文字找下标
（或者给单元格挂 `data-col`）再取：

```js
const heads = [...document.querySelectorAll(".grid thead th")].map((th) => th.textContent.trim());
const col = (name) => { const i = heads.indexOf(name); if (i < 0) throw new Error("没有这一列：" + name); return i; };
const qty = row.cells[col("数量")].textContent;
```

### 运行日志区：按一次运行分组、两层折叠

app-layout.html 主区底部那块是**运行日志区**：标题行写着行数，有「清空显示」和
「折叠」；下面按「一次运行」分组，每组一行结论「时间 · 状态 · 名称 · 结果」，点开看
原话；每行原话是「时间 · 等级 · 正文」，时间等宽灰字，等级「信息 / 告警 / 失败」用
语义色，失败行浅红底，长行自动换行。数据在 Python 侧的 `msui.runlog.RunLog`，长相在
base.css，行为在 msui 落下来的 `runlog.js`——**页面不写轮询和折叠逻辑**。三步：

1. **Python：建一个 `RunLog`，业务里记行、分组**（后台线程里记也行，它线程安全）：

   ```python
   # examples/minimal/app.py 片段
       runlog = RunLog()  # 要按天落文件就给 log_dir=（比如 storage_dir 下的「日志」）
   ```

   ```python
   # examples/minimal/app.py 片段
       runlog.start_run("读取数据")
       runlog.info("读到 6 张表。")
       runlog.end_run("ok", "6 张表全部识别成功")
   ```

   - 记一条：`runlog.info(…)` / `runlog.warn(…)` / `runlog.error(…)`，或
     `runlog.log("info" | "warn" | "error", 正文)`；等级就这三档，页面按这个字段上色，
     **不认正文里的字样**；
   - 一次运行：`start_run(名称)` 开始，`end_run(结局, 一句结果)` 结束，结局是
     `"ok"` / `"error"` / `"stopped"`。**那句结果就是页面组头上的结论**，页面不从原话
     里截，所以写成给业务用户看的一句话。期间记的行自动挂进这一组，运行之外的是散行；
     上一次没结束（比如中途抛了异常）就开始下一次，上一次记成 `stopped`；
   - 已经在用标准 `logging` 的程序不用改每处记日志的代码：
     `logging.getLogger().addHandler(RunLogHandler(runlog))`（`RunLogHandler`、
     `read_log_file` 与 `RunLog` 都从 `msui.runlog` 导入），WARNING → 告警，
     ERROR 及以上 → 失败，其余 → 信息；
   - 内存里最多留 `max_lines`（默认 5000）行，超了丢最旧的；
   - 给了 `log_dir=` 就按天落文件 `<log_dir>/<YYYY-MM-DD>.log`：一条一行页眉
     `2026-01-31 09:12:05 [失败] 导出`，原话每行缩进四格，人能直接读，
     `read_log_file(路径)` 能读回；`runlog.log_file_path()` 是今天那份。写不进（权限、
     路径不对）不抛，日志区里出一条告警「日志文件写不进：…」，只提示一次。

2. **js_api 上放一个取日志的方法**，把 `since()` 原样转给页面（不包 `Serializer`：
   取日志不该被正在跑的业务动作挡成「忙」）：

   ```python
   # examples/minimal/app.py 片段
       def get_log(self, since: int = 0) -> dict:
           """日志区每半秒调一次：since 之后的新行与运行变化。不包 Serializer——
           RunLog 自己线程安全，取日志不该被正在跑的业务动作挡成「忙」。"""
           return self._runlog.since(since)
   ```

   `since(序号)` 返回 `{"lines": [{"seq", "time", "level", "text", "run"}…],
   "runs": [{"id", "name", "start", "status", "result"}…], "last": 最新序号}`：
   上次之后的新行、有变化的运行（`status` 多一个 `"running"`）和下次要带回来的序号。

3. **页面：放一段标准标记，`</body>` 前引用 `runlog.js`**：

   ```html
   <!-- examples/minimal/pages/app-layout.html 片段 -->
   <section class="runlog" data-runlog="get_log" aria-label="运行日志">
     <div class="eyebrow"><span class="t">运行日志</span><span class="n" data-runlog-count></span><span class="grow"></span><button type="button" data-runlog-clear>清空显示</button><button type="button" data-runlog-toggle aria-expanded="true">折叠</button></div>
     <div class="runlog-list" data-runlog-list></div>
   </section>
   ```

   ```html
   <!-- examples/minimal/pages/app-layout.html 片段 -->
   <script src="runlog.js"></script>
   ```

   `data-runlog` 的值是第 2 步那个方法名（空着就是 `get_log`）。要「打开日志文件夹」
   就在「折叠」前面加一颗 `<button type="button" data-runlog-folder="open_log_folder">打开日志文件夹</button>`，
   值是 js_api 上打开文件夹的方法名（自己写，比如 Windows 上
   `os.startfile(runlog.log_dir)`）。

`runlog.js` 管的事：

- 每半秒调一次那个方法、只取新的；应答包在 `Serializer` 信封里也认，忙就等下一轮；
- **整区折叠**：点「折叠」只剩标题行和行数，状态存 localStorage 的 **`runlog-collapsed`**
  键（`'1'` 折叠；没存过 = 展开）。**折叠着新到了告警 / 失败行、或有运行以失败结束，
  自动展开，这次展开不记**——下次打开照样折叠；开窗时取回的历史不算「新到」。下次
  打开还记得的前提同主题按钮：`run()` 给了 `storage_dir=`；
- **分组**：失败组浅红底、默认展开；最新一组默认展开，更早的收起；还在跑的组状态写
  「运行中」，跑完自动换成结论。用户亲手点开或收起的组以用户为准，新数据不改它；
- 停在底部才跟着滚到最新，往上翻着看时不把人拽下去；
- 页面上最多留 2000 行，超了删最早的（行删空的组整组删），行数写成「N 行，显示最近
  2000 行」；
- 「清空显示」只清页面上的显示和行数，不动 Python 里的缓冲、不删日志文件；
- 原话可以选中复制（`run()` 默认文字可选）。

旧的 `<pre class="log">` 原样保留（不换行、不折叠），没换新部件的页面一个像素不变。

## 4. override.css（默认不用）

默认零配置、不建这个文件。真要换色（比如另一套品牌色）时：

- 在 `pages/` 里建 `override.css`，内容只有一段 `:root { --brand: …; }`——
  **只覆写 tokens.css 里已有的同名变量值**，不写选择器样式；
- 页面里在 `base.css` **之后**加 `<link rel="stylesheet" href="override.css">`；
- 防游离扫描的允许清单已含 `override.css`（改色值就是它的本职），闸门的对比度
  检查吃的是合成后的结果——override 改了什么、闸门就按什么算，压不住红。

### 浅色主题（opt-in）

msui 自带一套官方浅色：`tokens-light.css`，`copy_assets` 每次启动和另外几份
一起落进页面目录。它只在 `:root[data-theme="light"]` 下覆写同名颜色 token，
组件样式一条不改——**不开开关就一个像素不变**，默认仍是深色。启用两步：

1. `<head>` 里在 `base.css` 之后加一行：

   ```html
   <link rel="stylesheet" href="tokens-light.css">
   ```

2. 页面脚本里打开开关（关掉就是删掉这个属性；要不要记住用户的选择、记在
   哪——比如 `localStorage`——由页面自己决定）：

   ```js
   document.documentElement.dataset.theme = "light";   // 切到浅色
   delete document.documentElement.dataset.theme;      // 回到深色
   ```

要知道的四条：

- 品牌色上的文字（主按钮文案这类）走 `--on-brand`，**不要写 `var(--text)`**——
  浅色下 `--text` 是黑的，红底黑字；
- 同时有 `override.css` 换品牌色的话：浅色那份重新声明了 `--brand`，而
  `:root[data-theme="light"]` 比 `:root` 更具体，浅色下会把 override 的品牌色
  压回红色。两个主题都要换色就写 `:root, :root[data-theme="light"] { --brand: …; }`；
- 浅色的配色过的是同一张 `BASE_TOKEN_PAIRS`、同一套档位（msui 自己的 CI 把过
  关）；页面自己的 `MY_PAIRS` 与 override 也要在浅色下过一遍——§5 的闸门已经
  按 `gate.THEMES` 深色、浅色各跑一遍：`gate.theme_colors(theme, override)`
  按页面实际的层叠合成（浅色下只写在 `:root` 的 override 会被浅色值压掉，闸门
  算的也是被压掉之后的颜色）；
- 已知限制：Windows 原生标题栏开窗时染成深色的 `--win`，页面切浅色时它不跟着变。

### 深浅切换按钮（opt-in，0.11.0 起）

要让用户自己在深浅之间切，别写 localStorage 逻辑，用 msui 落下来的 `theme.js`
加一颗标准按钮（app-layout.html 顶栏右端就是）：

1. `<head>` 里在 `tokens-light.css` 之后**同步**引用（不加 `defer` / `async`）——
   开窗前就把主题设好，不会先闪一下深色再变浅色：

   ```html
   <!-- examples/minimal/pages/app-layout.html 片段 -->
   <link rel="stylesheet" href="tokens-light.css">
   <script src="theme.js"></script>
   ```

2. 顶栏放这颗按钮（两颗内联 svg：深色下显示太阳、浅色下显示月亮——图标表示
   「点了会去哪」；**不用 ☀ ☾ 这类字形**，Windows 缺字）：

   ```html
   <!-- examples/minimal/pages/app-layout.html 片段 -->
   <button class="icon" type="button" data-theme-toggle aria-label="切换深色 / 浅色">
     <svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
     <svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
   </button>
   ```

`theme.js` 管的事：

- 偏好存在 localStorage 的 **`theme`** 键：`'light'` = 浅色，`''` = 用户选了深色，
  **没存过按浅色处理**（第一次打开就是浅色）。全家同一个键、同一个默认；
- 点按钮在两者之间翻，同时把按钮的 `title` / `aria-label` 写成「切换到浅色」/
  「切换到深色」；
- localStorage 读写不了时只管这一次，不报错；
- **下次打开还记得，前提是 `run()` 给了 `storage_dir=`**：不给的话 pywebview 走
  隐私模式，关窗即清掉 localStorage（而且每次开窗的页面来源都不同），每次都回到
  默认浅色。

### 自己的版式：layout.css（默认不用）

msui 管的是「一家人」那部分：同一套 token、同一种控件、同一套版式骨架。一个
真实的业务小程序总有**只有它自己要**的版式和部件（页面导航、工序链、追溯侧栏、
一类一行的设置行……），它们的正式位置是 `pages/layout.css`：

- **判据只有一条**：别的小程序也会要的 → **开票回 msui**（收进 base.css，大家
  升级一起拿到）；只有你要的 → **layout.css**。拿不准就先开票问；
- 页面里在 `base.css` **之后**加 `<link rel="stylesheet" href="layout.css">`；
- **只许加、不许改**：用自己的新类名写版式与专属部件，不许重写 base.css 里
  已有的选择器（`button`、`button:hover`、`.seg button`、`.chip.on`、`dialog`、
  `.dot::before`……）——那等于悄悄改共享部件的长相，一家人变两家。闸门
  `scan_base_redefinitions` 按**整条选择器**比对（空白、引号写法不同也认得出），
  命中当场红。它是绊线不是证明：`.nav button` 这种带自己前缀的后代选择器过得了
  闸门，也只该改你自己那块区域里的东西；
- **配色照旧只许 `var(--token)`**：layout.css 不在 hex 允许清单里，手写 hex
  `scan_stray_hex` 照抓（闸门只认得 hex 字面量，`rgb()` / 颜色名同样不许写）；
  自己部件新用到的前景/背景组合登记进 `MY_PAIRS`；
- 它是你自己的文件、**要入仓**：`copy_assets` 不落它也不碰它，`.gitignore`
  别排除它；
- 层叠：layout.css 在 base.css 之后加载，特异性相同时它赢——自己的部件要压过
  通用的 `button:hover` 这类规则，靠的就是这个先后；
- html 里的内联 `<style>` 与任意名的 css 受同一条闸门检查；专属样式集中放
  layout.css 一处，最好找。

## 5. 闸门测试

自己仓里放一份下面的文件，pytest 就有三条样式闸门：配色对比度（WCAG 档位）、
防游离色值扫描，以及「自己的样式（layout.css、任意名的 css、html 内联
`<style>`）不许重定义 base.css 已有的选择器」：

```python
# examples/minimal/tests/test_style_gate.py
"""样式闸门：对比度 + 防游离色值 + 不改共享部件。整份可照抄，零件全部来自 msui.testing。"""
from __future__ import annotations

from pathlib import Path

import pytest

from msui import testing as gate

PAGES = Path(__file__).resolve().parent.parent / "pages"
OVERRIDE = PAGES / gate.OVERRIDE_CSS_NAME  # 默认不存在；要换色时才加
# 自己的版式与专属部件写 PAGES / gate.LAYOUT_CSS_NAME（默认不存在；要时才加）

# 页面自己的前景/背景组合往这里追加登记：gate.TokenPair(说明, 前景, 背景, 档位)
MY_PAIRS: tuple[gate.TokenPair, ...] = ()


@pytest.mark.parametrize("theme", gate.THEMES)
def test_contrast_gate(theme):
    # 深色、浅色各算一遍（浅色 = tokens-light.css 覆写，按页面实际层叠合 override）
    override = OVERRIDE.read_text(encoding="utf-8") if OVERRIDE.is_file() else None
    colors = gate.theme_colors(theme, override)
    failures = gate.contrast_failures(colors, gate.BASE_TOKEN_PAIRS + MY_PAIRS)
    assert not failures, gate.format_contrast_failures(failures, colors)


def test_no_stray_hex():
    offenders = gate.scan_stray_hex(PAGES)
    assert not offenders, gate.format_stray_hex(offenders)


def test_own_css_never_redefines_base_selectors():
    # 扫 pages/ 下自己的 .css（含 layout.css）与 html 内联 <style>
    offenders = gate.scan_base_redefinitions(PAGES)
    assert not offenders, gate.format_base_redefinitions(offenders)
```

## 打包成冻结产物（PyInstaller）

spec 对 msui **零资源配置**——样式与版本元数据由包自带的 hook 自动收齐，
`datas` 只写自己的页面目录：

```python
# examples/minimal/app.spec
# -*- mode: python ; coding: utf-8 -*-
# 最小消费者的 PyInstaller spec。关键点：对 msui 的资源与元数据**零配置**——
# tokens.css / base.css / tokens-light.css / theme.js / runlog.js / dist-info 全由
# msui 包自带的 pyinstaller40 hook 收齐。
# datas 只声明自己持有的页面目录。
import os

a = Analysis(
    [os.path.join(SPECPATH, "app.py")],
    pathex=[],
    binaries=[],
    datas=[(os.path.join(SPECPATH, "pages"), "pages")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

# 开发机上冒烟落地过的 tokens.css / base.css / tokens-light.css / theme.js / runlog.js 副本
# （gitignored、但在盘上）会被 pages/ 整目录收集顺手带进产物——纯冗余：运行时
# copy_assets 每次启动都无条件覆盖，产物里那几份副本永远不会被用到。按目的地
# 路径剔掉；CI 的干净 checkout 本来就没有它们，此过滤不改变 CI 产物。
def _is_landed_asset(dest: str) -> bool:
    parts = dest.replace("\\", "/").split("/")
    return parts[0] == "pages" and parts[-1] in (
        "tokens.css", "base.css", "tokens-light.css", "theme.js", "runlog.js",
    )

a.datas = [entry for entry in a.datas if not _is_landed_asset(entry[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="app",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # 真实小程序是窗口程序；冒烟只看退出码，不需要控制台
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="app",
)
```

打包与冒烟（不上屏）。打包命令两平台一样，冒烟按平台各一行：

```
pyinstaller examples/minimal/app.spec --noconfirm --distpath dist --workpath build
```

```powershell
# Windows（PowerShell）——正式目标平台
$env:APP_SMOKE = "1"; .\dist\app\app.exe
```

```sh
# macOS / Linux——开发机预演用
APP_SMOKE=1 ./dist/app/app
```

冒烟的自动驾驶骨架是 `msui.testing.SmokeDriver`（上面 app.py 的 APP_SMOKE
分支就是全部用法），它替你扛下四件容易踩坑的事：`on_ready` 跑在 pywebview
后台线程、**异常不会变成非零退出码**，所以失败一律收集、`run()` 返回后
`driver.exit()` 统一判定；桥往返是异步的，用 `wait_js` 轮询等到位；窗口
销毁在 finally 里，脚本怎么炸都不挂死；外加 watchdog 硬闹钟兜底（默认
120 秒，到点 `os._exit(2)`）。样式生效断言用 `check_token_style`（见下节）。

`wait_js` 两条行为要知道：页面探针表达式抛异常（典型：`querySelector` 返回
null 被直接 `getComputedStyle`）时**不中断整场**——异常文本当结果值返回，
那条 check 正常报「实测=<异常文本>」，剩余断言照跑；整个冒烟脚本共用一个
超时预算，**注定等不到的期望会烧满剩余预算才放行**（失败路径变慢是设计
使然，不为失败开小灶）——所以探针尽量写成 null-safe（照上面 `.display`
那段先判元素再取样式），元素缺席时报出的是 `missing` 而不是一串异常文本。

msui 落进来的五份副本（三份样式 + `theme.js` + `runlog.js`）要挡在 git 外——`pages/.gitignore`
写这五行（仓里的唯一来源是 msui 包，副本入了仓就是漂移源）：

```
tokens.css
base.css
tokens-light.css
theme.js
runlog.js
```

## 版本标记：产物里读得出带的是哪版 msui

`copy_assets` 落出去的每份 css 第一行是版本横幅 `/* msui X.Y.Z */`，值取包
自身安装元数据（单一来源，无第二份版本号）：

- **产物文件系统**：`head -1 pages/tokens.css` 直接读出；
- **页面 devtools**：Sources 面板打开 tokens.css，第一行就是。

横幅是 css 注释：tokens 解析整块剔注释、横幅里没有色值，样式闸门不受影响。

两级证明要分清：**横幅只证明 css 落了地**（文件在、版本对），不证明页面
把它吃进去了（`<link>` 被删、路径写错时横幅照样在）。「页面真的吃进去了」
用冒烟里的 `SmokeDriver.check_token_style` 断言：把某个 token 解成 rgb、与
元素实测 computedStyle 比对——砍掉 base.css 的 `<link>` 时它必红。两条各管
一半，都要有。

## 图标（exe 级，风格约定）

小程序的任务栏/资源管理器/标题栏图标不归 msui 运行时管（Windows 上它们都跟着
exe 资源走），但**长相有全家约定**，让一排小程序在任务栏上像一族：

- **品牌红圆角底板 + 白色简笔符号**：底板为圆角方形、填 tokens 的 `--brand`
  （#db021d，图标正是品牌用途），圆角 ≈ 22% 边长；符号白色、几何简笔，
  16px 下不糊的判据是线宽 ≥ 边长 15%；
- 一份 `assets/icon.ico`，内含 256/48/32/16 四档；
- spec 的 `EXE(...)` 加一行 `icon=os.path.join(SPECPATH, "assets", "icon.ico")`；
- 生成脚本可整份照抄官方样板仓（Tool_Counter）的 `assets/make_icon.py`，
  只改 `draw_symbol` 画自己工具的符号（Pillow 仅生成时用，不进产物）；
- 一条避坑：**白十字放红底上像红十字会徽（受保护标志），别用「+」当符号**。

宿主平台客户端列表里的图标是另一回事（接入契约 §3 的 `icon` 目前是死字段，
等那侧功能定型），本节只管 exe 自己的图标。

## 从 0.10.x 升到 0.11.0

0.11.0 把几个小程序各自抄了一份的部件收回了 msui：步骤卡 `.step`、读数卡
`.kpis` / `.kpi`、小标题 `.eyebrow`、整句列 `td.wrap`、深浅切换（`theme.js` +
标准按钮），并且 `run()` 默认让页面文字可选。没用这些类名、没引用 `theme.js` 的
页面，除了「文字能选中、点控件不误选」以外一个像素不变。升级时按下面做：

1. **钉版本几处一起改**：`requirements.txt` 那行 wheel URL 里的两处版本号
   （路径段 `v0.11.0` + 文件名 `msui-0.11.0-…`），加上冒烟里的 `MSUI_PINNED`
   常量。漏改一处，冒烟的横幅断言就红；
2. **`pages/.gitignore` 补一行 `theme.js`**（四行写法见上文「打包」一节末尾）；
   **`.spec` 的副本过滤**文件名元组补上 `"theme.js"`（样板里这个函数改名叫
   `_is_landed_asset`，旧名照用也行）；拿 `ASSET_NAMES` 对账这两处的测试会先红、
   补齐转绿——别把测试期望改回写死的清单；
3. **删掉本地那份重复样式**。重定义闸门 `test_own_css_never_redefines_base_selectors`
   会逐条报出和 base.css 同名的选择器（`.eyebrow`、`.step`、`.step .num i`、
   `.step.cur`、`.kpis`、`.kpi .val`、`button`……），照着删。**闸门报不出、也要删**
   的几条（它们和 base.css 不是同一条选择器，留着会和新写法打架）：
   - `.step.wait { opacity: … }`——等待态改成换 `--muted` 前景了，留着就是又淡又灰；
   - `.step.cur.done .num i` / `.step.done.cur .num i`——base.css 里完成态已经压过当前态；
   - `.step:hover`、`.step .act > button`、`.step .param …`、`.eyebrow .grow`、
     `.card > .eyebrow + *`、`.kpi .val.changed` 这类自己补的：base.css 有同功能的
     就删，确实是自己独有的（比如 `.kpi .val.changed`）留着；
   - 主题图标的显隐：`button.icon .sun { display: none }`、
     `:root[data-theme="light"] button.icon .sun / .moon`——**语义反过来了**（见第 4
     条），留着会让图标显示错；
   - 文字可选的硬压：`html body { user-select: text }` 删掉（`run()` 接手）；自己那串
     `button, .seg, … { user-select: none }` **只删与 base.css 重合的项**（`button`、
     `.btn`、`.seg`、`.pill`、`.chip`、`.switch`、`label`），自己独有的控件类留一条
     `user-select: none`——例如包装排产的 `.nav, .set-tabs { -webkit-user-select: none;
     user-select: none; }`，base.css 不认识它们；
   - 读数卡不是四列的（例如一排五张）：别改 `.kpis`（闸门会红），给容器加一个自己的
     类、用不同名的选择器写列数，**并自带窄窗那段**——它比 base.css 的 `.kpis` 更具体，
     base.css 里窄窗退两列的那条压不过它：
     `.kpis.five { grid-template-columns: repeat(5, minmax(0, 1fr)); }` +
     `@media (max-width: 900px) { .kpis.five { grid-template-columns: 1fr 1fr; } }`；
   - 数据网格整句列的 `#某表 td.path, #某表 td.say { white-space: normal; … }` 改成
     给单元格挂 `class="wrap"`；
4. **改页面写法**：
   - 步骤卡的头一行 `<div class="blk-head">` 改成 `<div class="head">`（或者把
     `.blk-head` 留在自己的 layout.css 里，不冲突）；
   - **编号圆圈画在 `<i>` 上**：`<span class="num"><i>1</i></span>`。圆圈直接画在
     `.step .num` 上、头一行叫 `.step-head` 的写法（EHS 体检）要改两处：
     `<div class="step-head">` → `<div class="head">`，`<span class="num">1</span>` →
     `<span class="num"><i>1</i></span>`，再删掉自己的 `.step .num`、`.step-head` 规则。
     EHS 原来的 `.step { display: flex; flex-direction: column; gap: … }` 是它自己的
     卡内排法，要留就挂一个自己的类、换不同名的选择器写（比如 `<section class="step
     stack">` + `.step.stack { … }`）——写回 `.step` 闸门会红；
   - 深浅切换：删掉 `<head>` 里那段读 localStorage 的内联 `<script>` 和 app.js 里的
     点击处理，换成 `<script src="theme.js"></script>` + 带 `data-theme-toggle` 的
     标准按钮（§4「深浅切换按钮」）。图标改成**深色下显示太阳、浅色下显示月亮**
     （「点了会去哪」），和旧的包装排产写法正好相反；
5. **主题偏好会失效一次的程序**：偏好统一存在 localStorage 的 `theme` 键、没存过
   按浅色。下面三个程序的用户升级后第一次打开会回到浅色，点一下就记住了——发版
   说明里提一句——它们原来都用 `msui-theme` 键，新键 `theme` 里没有存过东西：
   Counter、CIPData（原来没存过按深色，存 `"light"` 才浅色）、EHS 体检（深色存的是
   `"dark"`；新约定里深色存 `""`）。要跨次记住，
   `run()` 得给 `storage_dir=`；
6. **文字可选**：`run()` 新参数 `text_select` 默认 `True`，什么都不用改；确实不想
   让文字可选的程序显式传 `text_select=False`。

## 从 0.9.x 及更早升到 0.10.0

0.10.0 起 `copy_assets` 每次启动多落一份 `tokens-light.css`（可选的浅色主题，
见 §4）。照旧版 README 抄过去的几处只认 `tokens.css` / `base.css`，升钉版本时
跟着一起改：

1. **`pages/.gitignore`** 补一行 `tokens-light.css`（三行写法见上文「打包」一节
   末尾）——不补的话落地副本以未跟踪文件出现，一次整目录 add 就进了仓；
2. **PyInstaller `.spec` 的副本过滤**（样板里的 `_is_landed_css`）文件名元组补上
   `"tokens-light.css"`——不补只是产物里多一份永远用不到的副本，但与样板对不上；
3. **拿 `msui.resources.ASSET_NAMES` 对账 `.gitignore` / `.spec` 的测试**：升级后
   `ASSET_NAMES` 多了一项，这条会红——按上两条补齐让它转绿，别把测试里的期望
   改回写死的两份；
4. **闸门测试补成三条**：照新版 §5 的 `test_style_gate.py` 整份覆盖（`MY_PAIRS`
   留自己的）——对比度改为深色、浅色各一遍（`gate.theme_colors`），并新增
   `test_own_css_never_redefines_base_selectors`（`scan_base_redefinitions`）；
5. 给 `scan_stray_hex` 显式传过 `allowed_names=` 的，同样补上 `tokens-light.css`
   （用默认的 `ALLOWED_HEX_FILE_NAMES` 就不用管，它由 `ASSET_NAMES` 派生）。

页面长相上，小工具窗默认形态不变；对所有页面自动生效的只有两条修正：
`dialog[open]` 在窗内居中，品牌色上的文字走 `--on-brand`（深色下值与原来相同）。

## 给 AI 的转述块

给一个要新建/改造小程序仓的 AI 当引导词，整段粘贴即可：

```text
本项目界面使用 msui（共享 UI 运行时与样式，pywebview + WebView2）。约定如下：
1. 安装：requirements 里写一行钉版本 wheel URL（升级 = 只改版本号）：
   msui @ https://github.com/WangYiTao0/msui/releases/download/v0.11.0/msui-0.11.0-py3-none-any.whl
   另加一行 pyinstaller（宿主平台接入契约要求它进 requirements，CI 打包
   要用）；pytest 不进 requirements，CI 测试步内现装。
2. 页面（HTML/CSS/JS）放本仓 pages/ 目录。启动三步：page_dir() 定位页面目录
   （冻结态 sys._MEIPASS/pages，源码态在启动文件旁）→
   serve_dir = msui.resources.copy_assets(page_dir()) →
   msui.shell.run(serve_dir / "index.html", title="应用名")。开窗一律用
   copy_assets 的返回值。
3. 页面 <head> 依次相对引用 tokens.css、base.css。copy_assets 每次启动无条件
   覆盖落下这两份外加可选的 tokens-light.css 与 theme.js，四份都不入仓、不手改
   （pages/.gitignore 排除它们）。run() 默认 text_select=True（页面文字可选中
   复制），按钮 / 分段 / 开关 / 标签由 base.css 声明不可选——不要自己写
   user-select。
4. HTML 直接写语义化标签（button/input/table/a/h1…），不写自定义配色；任何
   颜色只允许 var(--token) 引用，禁止手写十六进制色值。
5. 换色（默认不需要）：pages/ 里加 override.css，只覆写 :root 里同名 token
   变量值，并在 base.css 之后 <link> 它。浅色主题（默认不开）：base.css 之后
   <link> tokens-light.css，再给 <html> 设 data-theme="light"；品牌色底上的
   文字用 var(--on-brand)，不用 var(--text)。要让用户切深浅：不写
   localStorage 逻辑，<head> 里在 tokens-light.css 之后同步写
   <script src="theme.js"></script>，顶栏放 msui README §4 那颗
   <button class="icon" data-theme-toggle>（.sun / .moon 两颗内联 svg）。偏好存
   localStorage 的 theme 键，没存过按浅色；跨次记住需要 run(storage_dir=…)。
6. 测试加三条样式闸门（照抄 msui README 的 test_style_gate.py）：
   contrast_failures 对比度（theme_colors 深色、浅色各一遍）+ scan_stray_hex 防游离色值 +
   scan_base_redefinitions 不重定义 base.css 已有选择器。
7. PyInstaller spec 里对 msui 零资源配置（包自带 hook 收齐样式与元数据），
   datas 只写自己的 ("pages", "pages")。
8. 版本核对：copy_assets 落下的 css 第一行是 /* msui X.Y.Z */。冒烟里定义
   常量 MSUI_PINNED（与 requirements 的 wheel URL 版本一致，升级时两处一起
   改）并断言横幅 == "/* msui <MSUI_PINNED> */"——钉死常量证明产物带的是
   钉的这一版，不改读 importlib.metadata（那只是回显、永远绿）。
9. 页面调 Python（js_api 桥）：Python 侧对象方法包 msui.bridge.Serializer
   （忙碌信封，连点丢弃不排队）；页面侧等 pywebviewready 事件后经
   window.pywebview.api.xxx() 调用（返回 Promise），应答 busy=true 就地丢弃。
10. 冒烟自动驾驶用 msui.testing.SmokeDriver（照抄 msui README §2 的
    APP_SMOKE 分支）：失败收集与退出码判定、finally 销毁窗口、watchdog
    超时兜底都由它代办；样式生效断言用它的 check_token_style（token 解成
    rgb 与元素实测 computedStyle 比对）。
11. 展示型大读数（计数器主角数字这类）给元素挂 .display 类：成块居中、
    字号走 --font-display 档（48px），不自己写字号、不自己居中。一组按钮
    给容器挂 .actions（横排、间距走档、窄窗折行），要居中再加 .center；
    不挂 .actions 的按钮会竖着堆起来（卡片垂直节奏在起作用，不是缺样式）。
    一行「标签 + 输入框 + 尾部按钮」给容器挂 .field：标签定宽走
    --field-label 档（多行表单的输入框左边缘靠它对齐）、输入框吃掉剩余
    宽度、尾部按钮不被压扁、窄窗折行。进度直接写裸 <progress>：写了 value
    按比例填充，**不给 value 就是不定态**（算不出百分比时把 value 属性去
    掉即可）。这四样都不许自己写版式 CSS，也不许自己写宽度与配色。
12. 单实例：run(..., single_instance="<miniprog.toml 的 id>")，连点图标只开
    一扇窗——第二个进程把已开的窗带到前台，带不动就静默退出（绝不弹错误
    框）。这个参数**必填**：不传 TypeError、空串 ValueError，真要多开显式写
    single_instance=False。同进程内第二次 run 用同一 id 会被自己的锁挡住。
13. 版式零决策：body 就是容器——边距、内容列宽、垂直节奏由 base.css 落在
    body 上，没有 .page 容器类；新页面从 msui README §3 的「标准单列页
    骨架」可抄块起步，不写任何版式 CSS，间距要自取时用 --space-1…6 档。
14. 三个二级表面同样零自定义样式：破坏性动作的确认写裸 <dialog> 用
    showModal() 弹（遮罩、居中、卡片容器、宽度上限全自带；里面的按钮行挂
    .actions，不另造一套），**禁止用 JS 的 confirm()/alert()/prompt()——它们
    阻塞 webview 的消息循环**；内联提示挂 .notice + 一个状态
    （error/warn/info/ok），显示/隐藏用 hidden 属性，不要给它写 display；
    跑批日志用 <pre class="log">（等宽、自己滚、长行不折行横向滚动），要占
    满剩余高度就覆写 max-height。
15. 宽表格程序（左栏参数 + 右边宽表）用应用式版式：给 body 挂 class="app"
    （纯 CSS，run() 不改），从 msui README §3 的 app-layout.html 可抄块起步——
    顶栏 <header class="top"> / 多栏 <div class="cols"> 里左栏 .rail +
    主区 .pane / 底部 <footer class="status">，内容区各自滚，窄窗左栏自动
    退到上面；左栏宽走 --rail-width。不挂 app 的页面仍是小工具窗版式。
    互斥选项用 .seg（当前项挂 .on），日期/计数/状态胶囊用 .pill（可加
    ok/warn/info/error），flex 行里推到最右用 .grow，进场动效挂 .fade-in
    （错峰写 style="--i: 序号"）。这些都不许自己写版式 CSS 或配色。
16. 清单 / 设置页的部件（小窗与应用式都能用，从 msui README §3 的
    widgets.html 可抄块起步）：工具条 .toolbar（右推用 .grow）、筛选片
    .chip（当前项 .on，计数 <span class="n">）、搜索框 <label class="search">、
    数据网格 <div class="grid"><table>（数字列 td/th 挂 .num，选中行 tr.sel）、
    图标按钮 button.icon（**只用内联 svg + currentColor，不用 Unicode 箭头**，
    写 aria-label）、开关 <button class="switch" role="switch"
    aria-checked="false">（点击翻 aria-checked）、状态点 .dot（ok/warn/
    info/error）。收放用 hidden、不写 display。冒烟里取表格单元格按表头
    文字找列，**不按下标**——加列 / 挪列后下标取值会整体错位。
17. 只有本程序要的版式与专属部件（页面导航、工序链这类）写进
    pages/layout.css（在 base.css 之后 <link>，入仓）：只用自己的新类名，
    不许重写 base.css 已有的选择器（button、.seg button、dialog……，闸门
    会红），配色只许 var(--token)。别的小程序也会要的部件不写这里——
    开票回 msui。
18. 左栏流程与主区读数（从 msui README §3 的 app-layout.html 与「左栏步骤卡、
    读数卡、小标题、整句列」一节起步，不自己写这些样式）：区块小标题
    .eyebrow（标题包 .t、计数 .n）；步骤卡 .step > .head > .num > i + .title，
    说明 .meta（.fail/.hint/.good），参数 .param（标签在上，输入框带按钮包
    .row），动作 .act，卡内可放 <progress>；三态 .done/.cur/.wait（等待态是
    弱化前景，**不用 opacity**），可点的卡写 tabindex="0" role="button"。读数卡
    <div class="kpis"><div class="card kpi"> 里 .lbl / .val（单位 <small>）/
    .sub，没数据时 .val 写「—」、副行包 .dim，告警态 .kpi.warn。数据网格里
    整句话的列给单元格挂 class="wrap"。
```

## 发布（维护者）

版本号只写在 `pyproject.toml` 一处。发布：

```
git tag v<版本号> && git push origin v<版本号>
```

CI 在装依赖之前核对 tag 与 pyproject 版本一致（不一致当场 fail），跑测试，
构建 wheel，用自带 GITHUB_TOKEN 发到本仓 Release——零 PAT。发完后把上面
第 1 步安装行里的版本号改成新版。
