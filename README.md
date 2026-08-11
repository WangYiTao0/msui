# msui

小程序共享 UI 运行时与样式（pywebview + WebView2）：WebView2 检测引导、一行开窗、
共享 tokens/base 样式与样式闸门、js_api 桥通用件、自带 PyInstaller hook。

设计与切票见 spec：[WangYiTao0/MSToolbox#107](https://github.com/WangYiTao0/MSToolbox/issues/107)。

本 README 就是消费者契约：下面五件事按顺序做，一个新的小程序仓从零到跑起来。
所有代码块与 `examples/minimal/` 里的完整示例一字一致（有测试盯着不许漂移），
放心整段照抄。

## 1. 装

requirements 里写一行钉版本的 wheel URL，无需任何凭据；**升级 = 只改这一行里的
两处版本号**：

```
msui @ https://github.com/WangYiTao0/msui/releases/download/v0.8.0/msui-0.8.0-py3-none-any.whl
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
from msui.shell import run
from msui.testing import SmokeDriver

# 本仓钉死的 msui 版本，与 requirements 里 wheel URL 的版本号一致，升级
# msui 时两处一起改。冒烟据此断言横幅——钉死常量证明「产物带的确实是钉的
# 这一版」；改读 importlib.metadata 只是回显装了哪版、永远绿，证明不了钉住。
MSUI_PINNED = "0.8.0"


class Api:
    """js_api 桥对象：业务留在 Python，页面只管调用与显示。

    pywebview 对每次前端调用各开一个后台线程（官方文档明说 not
    thread-safe），方法一律包在 Serializer 里：抢不到锁立即回
    {"busy": True, ...}，绝不排队——连点五下不会攒成一队。
    """

    def __init__(self) -> None:
        self._serial = Serializer()

    def ping(self) -> dict:
        """页面调一次拿一句应答：{"busy": False, "data": "pong 来自 Python"}。"""
        return self._serial.run(lambda: "pong 来自 Python")


def page_dir() -> Path:
    """页面目录：冻结态在 _MEIPASS/pages（app.spec 收进去的），源码态在本文件旁。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "pages"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / "pages"


def make_smoke_script(serve_dir: Path):
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
    smoke = os.environ.get("APP_SMOKE") == "1"
    driver = SmokeDriver(make_smoke_script(serve_dir)) if smoke else None
    run(
        serve_dir / "index.html",
        js_api=Api(),
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

- `copy_assets` **无条件覆盖**地把 `tokens.css` + `base.css` 落进页面目录并返回
  该开窗的目录——开窗一律用返回值，别写死 `page_dir`；
- 这两份 css 不入仓、不手改（`pages/.gitignore` 把它们排除掉）；
- 钉版本的官方姿势就是上面的 `MSUI_PINNED` 常量 + 横幅断言：**钉死常量证明
  「产物带的确实是钉的这一版」，改读 `importlib.metadata` 只是回显装了哪版、
  永远绿**——升级 msui 时改两处（requirements 的 wheel URL + 这个常量），
  冒烟红了就是有一处忘了改；
- `run(...)` 还收 `width/height/min_size`、`icon=`、`storage_dir=` +
  `version=`（持久化与按版本清缓存）等关键字参数，按需加。

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

## 4. override.css（默认不用）

默认零配置、不建这个文件。真要换色（比如另一套品牌色）时：

- 在 `pages/` 里建 `override.css`，内容只有一段 `:root { --brand: …; }`——
  **只覆写 tokens.css 里已有的同名变量值**，不写选择器样式；
- 页面里在 `base.css` **之后**加 `<link rel="stylesheet" href="override.css">`；
- 防游离扫描的允许清单已含 `override.css`（改色值就是它的本职），闸门的对比度
  检查吃的是合成后的结果——override 改了什么、闸门就按什么算，压不住红。

## 5. 闸门测试

自己仓里放一份下面的文件，pytest 就有两条样式闸门：配色对比度（WCAG 档位）
与防游离色值扫描：

```python
# examples/minimal/tests/test_style_gate.py
"""样式闸门：对比度 + 防游离色值。整份可照抄，零件全部来自 msui.testing。"""
from __future__ import annotations

from pathlib import Path

from msui import testing as gate
from msui.resources import parse_tokens, tokens_css_path

PAGES = Path(__file__).resolve().parent.parent / "pages"
OVERRIDE = PAGES / gate.OVERRIDE_CSS_NAME  # 默认不存在；要换色时才加

# 页面自己的前景/背景组合往这里追加登记：gate.TokenPair(说明, 前景, 背景, 档位)
MY_PAIRS: tuple[gate.TokenPair, ...] = ()


def _colors() -> dict[str, str]:
    tokens = parse_tokens(tokens_css_path().read_text(encoding="utf-8"))
    if OVERRIDE.is_file():
        tokens = gate.merge_tokens(
            tokens, parse_tokens(OVERRIDE.read_text(encoding="utf-8"))
        )
    return gate.hex_tokens(tokens)


def test_contrast_gate():
    colors = _colors()
    failures = gate.contrast_failures(colors, gate.BASE_TOKEN_PAIRS + MY_PAIRS)
    assert not failures, gate.format_contrast_failures(failures, colors)


def test_no_stray_hex():
    offenders = gate.scan_stray_hex(PAGES)
    assert not offenders, gate.format_stray_hex(offenders)
```

## 打包成冻结产物（PyInstaller）

spec 对 msui **零资源配置**——样式与版本元数据由包自带的 hook 自动收齐，
`datas` 只写自己的页面目录：

```python
# examples/minimal/app.spec
# -*- mode: python ; coding: utf-8 -*-
# 最小消费者的 PyInstaller spec。关键点：对 msui 的资源与元数据**零配置**——
# tokens.css / base.css / dist-info 全由 msui 包自带的 pyinstaller40 hook 收齐。
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

# 开发机上冒烟落地过的 tokens.css / base.css 副本（gitignored、但在盘上）
# 会被 pages/ 整目录收集顺手带进产物——纯冗余：运行时 copy_assets 每次启动
# 都无条件覆盖，产物里那两份副本永远不会被用到。按目的地路径剔掉；CI 的
# 干净 checkout 本来就没有它们，此过滤不改变 CI 产物。
def _is_landed_css(dest: str) -> bool:
    parts = dest.replace("\\", "/").split("/")
    return parts[0] == "pages" and parts[-1] in ("tokens.css", "base.css")

a.datas = [entry for entry in a.datas if not _is_landed_css(entry[0])]

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

msui 落进来的两份样式副本要挡在 git 外——`pages/.gitignore` 写这两行
（仓里的唯一样式来源是 msui 包，副本入了仓就是漂移源）：

```
tokens.css
base.css
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

## 给 AI 的转述块

给一个要新建/改造小程序仓的 AI 当引导词，整段粘贴即可：

```text
本项目界面使用 msui（共享 UI 运行时与样式，pywebview + WebView2）。约定如下：
1. 安装：requirements 里写一行钉版本 wheel URL（升级 = 只改版本号）：
   msui @ https://github.com/WangYiTao0/msui/releases/download/v0.8.0/msui-0.8.0-py3-none-any.whl
   另加一行 pyinstaller（宿主平台接入契约要求它进 requirements，CI 打包
   要用）；pytest 不进 requirements，CI 测试步内现装。
2. 页面（HTML/CSS/JS）放本仓 pages/ 目录。启动三步：page_dir() 定位页面目录
   （冻结态 sys._MEIPASS/pages，源码态在启动文件旁）→
   serve_dir = msui.resources.copy_assets(page_dir()) →
   msui.shell.run(serve_dir / "index.html", title="应用名")。开窗一律用
   copy_assets 的返回值。
3. 页面 <head> 依次相对引用 tokens.css、base.css。这两份不入仓、不手改，
   由 copy_assets 每次启动无条件覆盖落下（pages/.gitignore 排除它们）。
4. HTML 直接写语义化标签（button/input/table/a/h1…），不写自定义配色；任何
   颜色只允许 var(--token) 引用，禁止手写十六进制色值。
5. 换色（默认不需要）：pages/ 里加 override.css，只覆写 :root 里同名 token
   变量值，并在 base.css 之后 <link> 它。
6. 测试加两条样式闸门（照抄 msui README 的 test_style_gate.py）：
   contrast_failures 对比度 + scan_stray_hex 防游离色值。
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
```

## 发布（维护者）

版本号只写在 `pyproject.toml` 一处。发布：

```
git tag v<版本号> && git push origin v<版本号>
```

CI 在装依赖之前核对 tag 与 pyproject 版本一致（不一致当场 fail），跑测试，
构建 wheel，用自带 GITHUB_TOKEN 发到本仓 Release——零 PAT。发完后把上面
第 1 步安装行里的版本号改成新版。
