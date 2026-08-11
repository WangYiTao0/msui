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
