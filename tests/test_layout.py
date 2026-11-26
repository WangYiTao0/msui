"""版式地基的静态闸门（issue #10）：间距体系、容器约定、垂直节奏、大读数。

这层测的是「CSS 文本层」的契约——规则存在、间距只经 token 引用、约定没被
后来的改动悄悄拆掉。「渲染层」的实测（computedStyle 里 body 真有非零内边距、
.display 真居中）在 examples/minimal 的冒烟脚本里，真打包隐藏窗跑。

容器约定（写进 README §3，后来者零决策）：**body 就是容器**——base.css 给
body 上 max-width + margin-inline auto + 内边距，裸语义 HTML 不写任何 class
就有边距与节奏；.page 之类的容器类不存在，也不需要。
"""
from __future__ import annotations

import re

import pytest

from msui.resources import base_css_path, parse_tokens, tokens_css_path
from msui.testing import NON_HEX_TOKENS, _css_selectors

BASE = base_css_path().read_text(encoding="utf-8")
TOKENS = parse_tokens(tokens_css_path().read_text(encoding="utf-8"))

# 间距体系：4px 基线的六档。base.css 里所有「块与块之间」的间距只取这些档。
SPACE_STEPS = ("space-1", "space-2", "space-3", "space-4", "space-5", "space-6")


def rule(selector: str) -> str:
    """按选择器逐字取出 base.css 里那条规则的声明块（花括号内的文本）。

    选择器要写得与 base.css 里一字一样；取不到当场 fail，好过返回空串让
    后面的断言含混地红。锚定在行首——不锚的话查 "body" 会先命中
    "html, body" 那条（账本 SED：匹配到的未必是要找的那个，先保证唯一）。
    """
    pattern = re.compile("(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}")
    match = pattern.search(BASE)
    assert match, f"base.css 里找不到选择器 {selector!r} 的规则"
    return match.group(1)


def rule_pos(selector: str) -> int:
    """那条规则在 base.css 里的位置，用于比较两条规则的先后。

    同样行首锚定，理由比 `rule()` 更硬：base.css 的注释里**逐字写着**
    `.card > * + *` / `.actions > * + *` 这些选择器（解释特异性同分时靠源码
    顺序决胜）。裸 `BASE.index(selector)` 会先命中注释里那处，比较的就成了
    注释的先后——注释挪一下位置，测试照样绿，而真规则可能已经失效。
    """
    match = re.search("(?m)^" + re.escape(selector) + r"\s*\{", BASE)
    assert match, f"base.css 里找不到选择器 {selector!r} 的规则"
    return match.start()


# ---------------------------------------------------------------------------
# 间距 token 体系
# ---------------------------------------------------------------------------


def test_spacing_scale_exists_and_ascends():
    """六档间距 token 全在、都是 px、且严格递增（乱序说明有人改错档）。"""
    values = []
    for name in SPACE_STEPS:
        value = TOKENS.get(name, "")
        assert value.endswith("px"), f"tokens.css 里缺间距档 --{name}（或不是 px）"
        values.append(int(value.removesuffix("px")))
    assert values == sorted(values) and len(set(values)) == len(values), (
        f"间距档必须严格递增：{dict(zip(SPACE_STEPS, values))}"
    )


def test_content_max_token_exists():
    assert TOKENS.get("content-max", "").endswith("px"), (
        "tokens.css 里缺内容列宽 --content-max"
    )


def test_field_label_token_exists():
    assert TOKENS.get("field-label", "").endswith("px"), (
        "tokens.css 里缺表单行的标签列宽 --field-label"
    )


@pytest.mark.parametrize("name", SPACE_STEPS + ("content-max", "field-label"))
def test_layout_tokens_are_whitelisted(name: str):
    """量值 token 不是色值，必须登记进 NON_HEX_TOKENS，否则 hex_tokens 当场炸。"""
    assert name in NON_HEX_TOKENS


# ---------------------------------------------------------------------------
# 容器约定：body 就是容器
# ---------------------------------------------------------------------------


def test_body_is_the_content_container():
    body = rule("body")
    assert "max-width: var(--content-max)" in body
    assert "margin-inline: auto" in body
    assert re.search(r"padding:[^;]*var\(--space-", body), (
        "body 的内边距必须走间距档——这是「内容不贴窗框」的唯一来源"
    )


# ---------------------------------------------------------------------------
# 垂直节奏：兄弟块常规档、标题+说明紧排成组、卡片内部收紧
# ---------------------------------------------------------------------------


def test_sibling_blocks_get_the_regular_rhythm():
    flow = rule("body > * + *")
    assert re.search(r"margin-top: var\(--space-\d\)", flow.strip()), (
        "顶层兄弟块的节奏必须走间距档"
    )


def test_heading_and_its_lede_are_a_tight_pair():
    """h1/h2/h3 后紧跟的说明段收紧成一组——真机诊断第 4 条的解法。"""
    pair = rule("h1 + p, h2 + p, h3 + p")
    assert re.search(r"margin-top: var\(--space-\d\)", pair.strip())


def test_card_children_get_the_tight_rhythm():
    inner = rule(".card > * + *")
    assert re.search(r"margin-top: var\(--space-\d\)", inner.strip())


def test_rhythm_and_container_never_hardcode_px():
    """节奏与容器规则里不许出现字面 px 间距——间距只经 token 取用。"""
    for selector in ("body", "body > * + *", "h1 + p, h2 + p, h3 + p", ".card > * + *"):
        block = rule(selector)
        for prop in re.findall(r"(?:margin|padding)[a-z-]*:\s*([^;]+);", block):
            assert "px" not in prop or "var(--" in prop, (
                f"{selector!r} 的间距写了字面 px：{prop!r}"
            )


# ---------------------------------------------------------------------------
# 大读数排版
# ---------------------------------------------------------------------------


def test_display_is_a_centered_block():
    """.display 挂在 output（inline）上也要成块居中——转 block 是前提。"""
    display = rule(".display")
    assert "display: block" in display
    assert "text-align: center" in display
    assert "var(--font-display)" in display


def test_display_font_step_fits_a_small_tool_window():
    """字号档 48px：18px 的 h1 压不住主角读数，32px 在 560×520 里仍偏客气。

    这是设计定版值——改它要连着真机截图重新核对，不是随手可调的数。
    """
    assert TOKENS.get("font-display") == "48px"


def test_card_padding_uses_the_scale():
    card = rule(".card")
    assert re.search(r"padding: var\(--space-\d\)", card)


# ---------------------------------------------------------------------------
# 操作行：一组按钮横排
# ---------------------------------------------------------------------------


def test_actions_is_a_wrapping_flex_row():
    """按钮组横排、窄窗折行；按钮之间的间距同样只走间距档。"""
    actions = rule(".actions")
    assert "display: flex" in actions
    assert "flex-wrap: wrap" in actions, "窄窗放不下时要折行，不许横向溢出"
    assert re.search(r"gap: var\(--space-\d\)", actions), "按钮间距必须走间距档"


def test_actions_centering_is_opt_in():
    """默认左对齐（跟着文字流的左边缘最好扫），居中是显式加 .center 才有。

    `.actions` 自己不许出现 justify-content —— 写了就等于把居中变成默认，
    `.center` 这个开关也就没有意义了。
    """
    assert "justify-content" not in rule(".actions")
    assert "justify-content: center" in rule(".actions.center")


def test_actions_kills_the_card_rhythm_and_wins_by_source_order():
    """`.actions > * + *` 必须写在 `.card > * + *` **之后**才生效。

    两条选择器特异性同为 (0,1,1)，同分时靠源码顺序决胜。位置一旦上移到垂直
    节奏那一节，卡片里的按钮组从第二个按钮起会带 margin-top，在 flex 行里
    表现为按钮高低不齐 —— 这正是 `<div class="card actions">` 的常规写法。

    位置比较走 `rule_pos`（行首锚定），不用 `BASE.index`：base.css 的注释里
    逐字写着这两个选择器，朴素查找会先命中注释。
    """
    assert re.search(r"margin-top:\s*0\s*;", rule(".actions > * + *")), (
        "卡片给的竖向节奏必须在操作行里归零"
    )
    assert rule_pos(".actions > * + *") > rule_pos(".card > * + *"), (
        "顺序反了：.actions 的归零会被 .card 的节奏盖掉（特异性同分，后来者胜）"
    )


# ---------------------------------------------------------------------------
# 表单行：标签 + 弹性输入框 + 尾部按钮
# ---------------------------------------------------------------------------

FIELD_CONTROLS = ".field > input, .field > select, .field > textarea, .field > .input"


def test_field_is_a_wrapping_flex_row_with_token_gaps():
    """一行排开、窄窗折行；行内间距同样只走间距档，不散写字面 px。"""
    field = rule(".field")
    assert "display: flex" in field
    assert "flex-wrap: wrap" in field, "窄窗放不下时要折行，不许横向溢出"
    assert re.search(r"gap: var\(--space-\d\) var\(--space-\d\)", field), (
        "行内间距（折行后的行距 + 件与件之间）必须走间距档"
    )


def test_field_label_width_is_one_shared_token_not_a_per_row_number():
    """标签定宽走 --field-label：多行竖排时输入框的左边缘靠这一个值对齐。"""
    assert "var(--field-label)" in rule(".field > label")


def test_field_input_grows_and_may_shrink_to_zero():
    """输入框吃掉剩余宽度（flex-grow）+ min-width 归零（窄窗不顶破容器）。

    flex-basis 不许是 0 或 auto：折行看的是压缩前的基准尺寸，归零 min-width
    之后还得留一个基准，否则输入框只会一路缩到看不见、永远不折行。
    """
    controls = rule(FIELD_CONTROLS)
    match = re.search(r"flex: 1 1 (\S+?);", controls)
    assert match, "输入框必须 flex: 1 1 <基准>——grow 吃掉剩余宽度"
    assert match.group(1) not in ("0", "auto", "0%"), (
        f"flex-basis 是 {match.group(1)!r}：折行阈值没了，窄窗只会一路缩不折行"
    )
    assert "min-width: 0" in controls, "不归零 min-width 的话窄窗会横向溢出"


def test_field_trailing_button_is_not_squeezed_and_lines_up_with_the_input():
    """尾部按钮不参与压缩；与输入框同为 stretch，两者顶边才严丝合缝地齐平。"""
    button = rule(".field > button, .field > .btn")
    assert "flex: 0 0 auto" in button
    assert "align-self: stretch" in button
    assert "align-self: stretch" in rule(FIELD_CONTROLS)


def test_field_kills_the_card_rhythm_and_wins_by_source_order():
    """`.field > * + *` 必须写在 `.card > * + *` **之后**才生效。

    与 `.actions > * + *` 一字不差的同一个先例：两条选择器特异性同为
    (0,1,1)，同分时靠源码顺序决胜。位置一旦上移到垂直节奏那一节，
    `<div class="card field">`（整卡即一行的常规写法）里的输入框与按钮会
    带上 margin-top，在 flex 行里表现为整行被撑高、标签与输入框不再同心。

    位置比较走 `rule_pos`（行首锚定），不用 `BASE.index`：base.css 的注释里
    逐字写着这两个选择器，朴素查找会先命中注释。
    """
    assert re.search(r"margin-top:\s*0\s*;", rule(".field > * + *")), (
        "卡片给的竖向节奏必须在表单行里归零"
    )
    assert rule_pos(".field > * + *") > rule_pos(".card > * + *"), (
        "顺序反了：.field 的归零会被 .card 的节奏盖掉（特异性同分，后来者胜）"
    )


# ---------------------------------------------------------------------------
# 进度条：裸 <progress> 的两种态
# ---------------------------------------------------------------------------


def test_progress_paints_track_and_value_through_tokens_in_both_engines():
    """轨道 --track、进度 --brand，两个引擎共用同一对 -webkit- 伪元素。

    `appearance: none` 是前提：不摘掉原生控件长相，两个引擎里那对伪元素的
    规则都不起作用，深色窗里露出系统默认的浅色控件。
    """
    host = rule("progress")
    assert "appearance: none" in host and "-webkit-appearance: none" in host
    assert "var(--track)" in host, "不认伪元素的引擎至少要有轨道底兜底"
    assert "var(--track)" in rule("progress::-webkit-progress-bar")
    assert "var(--brand)" in rule("progress::-webkit-progress-value")


def test_progress_radius_is_the_same_step_as_buttons():
    """圆角与按钮同一档——档位从按钮那条规则里取，不许两边各写各的数。"""
    match = re.search(r"border-radius: (\d+px)", rule("button, .btn"))
    assert match, "按钮那条规则里找不到圆角档"
    assert f"border-radius: {match.group(1)}" in rule("progress")


def test_progress_is_ringed_by_the_border_token():
    """凹陷式轨道自己看不见边（对 card 只有 1.13:1），槽的边界靠这圈描边画。

    这一条与 testing.py 里那条 `进度条描边 border（track 底）` 登记是一对：
    登记只管「这两个颜色分得开」，这里管「描边真的画了」。描边一去，轨道就
    融进卡片底里，只剩一条飘着的红填充。
    """
    assert "border: 1px solid var(--border)" in rule("progress"), (
        "进度条需要一圈 --border 描边——凹陷式轨道自己够不到分隔线档 1.3"
    )


def test_progress_without_value_degrades_to_an_indeterminate_bar():
    """不给 value（progress_percent 回 None 那种情形）要有不定态长相。

    不定态画的是一段来回移动的品牌色，两个引擎各自的落点都要有：宿主元素
    自己一份（兜底），::-webkit-progress-bar 一份（两个引擎实际吃的那份）。
    """
    for selector in ("progress:not([value])", "progress:not([value])::-webkit-progress-bar"):
        block = rule(selector)
        assert "var(--brand)" in block and "var(--track)" in block
        assert "animation:" in block, "不定态是动的：宽度不表示进度，靠移动表示在跑"
    assert "@keyframes msui-progress-loop" in BASE, "不定态的关键帧不见了"


# ---------------------------------------------------------------------------
# 模态确认对话框：裸 <dialog> + ::backdrop
# ---------------------------------------------------------------------------


def test_dialog_is_a_centered_card_with_a_width_cap():
    """浮起来的一张卡：居中、宽度上限跟着内容列走、内衬与卡片同一档。"""
    dialog = rule("dialog")
    assert "margin: auto" in dialog, (
        "居中靠的就是 UA 那条 margin auto，而本文件顶上的 `* { margin: 0 }` 把它"
        "清掉了——不显式还回来，对话框会贴在窗口左上角"
    )
    assert "max-width: var(--content-max)" in dialog, "宽度上限跟着内容列宽走"
    assert "background: var(--card)" in dialog and "var(--border)" in dialog
    assert re.search(r"padding: var\(--space-\d\)", dialog), "内衬必须走间距档"


def test_open_dialog_pins_itself_to_the_viewport_explicitly():
    """打开的对话框显式 `position: fixed; inset: 0`（票 #23）。

    margin auto 四向居中的前提是元素被钉在整个视口上；只靠 UA 给的那一份，
    Chrome 140 实测对话框贴在视口顶上（WebView2 同是 Chromium）。写在
    `dialog[open]` 上而不是 `dialog` 上：关着的对话框一条声明都不多拿；同样
    一个 display 都不许写（「关着就不见」只靠 UA 的 display: none）。
    """
    opened = rule("dialog[open]")
    assert "position: fixed" in opened
    assert "inset: 0" in opened
    assert "display" not in opened


def test_dialog_radius_is_the_same_step_as_cards():
    """圆角与卡片同一档——档位从 .card 那条规则里取，不许两边各写各的数。"""
    match = re.search(r"border-radius: (\d+px)", rule(".card"))
    assert match, "卡片那条规则里找不到圆角档"
    assert f"border-radius: {match.group(1)}" in rule("dialog")


def test_dialog_never_declares_display():
    """`dialog:not([open]) { display: none }` 是「关着就不见」的唯一来源。

    它在 UA 层，作者层随便写个 display 都会盖过它（跨来源的层叠，与特异性
    无关），结果是没 open 的对话框直接摊在页面里。
    """
    assert "display" not in rule("dialog")


def test_dialog_backdrop_is_the_scrim_token():
    assert "background: var(--scrim)" in rule("dialog::backdrop")


def test_dialog_says_how_long_text_behaves():
    """三四行的确认文案是常态：装不下时对话框自己滚，不把按钮行顶出窗外。"""
    dialog = rule("dialog")
    assert "max-height" in dialog and "overflow: auto" in dialog


def test_dialog_reuses_actions_instead_of_a_bespoke_button_row():
    """对话框里的按钮行吃现成的 .actions —— 不许为它另造一套横排规则。

    `.actions > * + *` 带一个类选择器、`dialog > * + *` 只有类型选择器，前者
    特异性更高，横排该有的样子自动生效，与源码顺序无关（这一点与 .card 那对
    同分选择器不同，所以这里不需要顺序断言）。
    """
    assert re.search(r"margin-top: var\(--space-\d\)", rule("dialog > * + *")), (
        "对话框内部（标题、说明段、按钮行之间）的竖向节奏必须走间距档"
    )
    for selector, block in re.findall(r"(?m)^(dialog[^{\n]*?)\s*\{([^}]*)\}", BASE):
        assert "display: flex" not in block, (
            f"{selector!r} 里另造了一套按钮行——用 .actions"
        )


# ---------------------------------------------------------------------------
# 内联提示条：一个中性类 + 四个状态修饰
# ---------------------------------------------------------------------------

NOTICE_STATES = ("error", "warn", "info", "ok")


def test_notice_is_a_neutral_strip_with_token_spacing():
    notice = rule(".notice")
    assert re.search(r"padding: var\(--space-\d\) var\(--space-\d\)", notice), (
        "提示条的内衬必须走间距档"
    )
    assert "border-radius" in notice
    assert "line-height" in notice, "四行的长文案要读得下去"


@pytest.mark.parametrize("state", NOTICE_STATES)
def test_each_state_paints_its_own_tint_and_solid_text(state: str):
    """底走对应状态的半透明晕染 token，文字走同名实色 token。"""
    block = rule(f".notice.{state}")
    assert f"background: var(--{state}-bg)" in block
    assert f"color: var(--{state})" in block


def test_notice_error_consumes_the_two_error_strip_tokens():
    """--error-strip-border（条子与重试按钮的边框）与 --error-wash（按钮 hover
    提亮罩）是 tokens 里为「内联错误条」专门备的两个，本条盯着它们真有消费者。"""
    assert "border-color: var(--error-strip-border)" in rule(".notice.error")
    assert "var(--error-strip-border)" in rule(".notice.error button, .notice.error .btn")
    assert "background: var(--error-wash)" in rule(
        ".notice.error button:hover, .notice.error .btn:hover"
    )


def test_notice_never_declares_display_so_hidden_really_hides():
    """显示/隐藏的开关是 `hidden` 属性，而 `[hidden] { display: none }` 在 UA 层。

    `.notice` 自己一旦写了 display（作者层），UA 那条就被盖掉——「收起来的
    提示条」会照样显示在页面上。要横排就在里面挂 .actions，别动这里。
    """
    assert "display" not in rule(".notice")


@pytest.mark.parametrize(
    "token",
    ("error-bg", "warn-bg", "info-bg", "ok-bg", "error-strip-border", "error-wash"),
)
def test_the_status_tint_tokens_all_have_a_consumer(token: str):
    """这六个 token 曾经「有 token、没有任何类消费」，本条盯着它们别再变回摆设。"""
    assert f"var(--{token})" in BASE, f"--{token} 又没有消费者了"


# ---------------------------------------------------------------------------
# 日志区：等宽、定高、不折行
# ---------------------------------------------------------------------------


def test_log_is_a_bounded_monospace_scroller():
    log = rule(".log")
    assert "font-family: var(--font-mono)" in log, "等宽字体族必须走 --font-mono 档"
    assert re.search("max-height:|height:", log), "定高或最高，不能跟着内容一路长"
    assert "overflow: auto" in log
    assert re.search(r"padding: var\(--space-\d\)", log), "内衬必须走间距档"


def test_log_lines_never_wrap():
    """`white-space: pre`，不许是 pre-wrap / pre-line：消费者的日志每行都是长
    文件路径，折行之后一条路径断成两三截，眼睛没法顺着扫（tkinter 版就是
    wrap="none"）。"""
    assert re.search(r"white-space: pre\s*;", rule(".log"))


def test_scrollbar_set_covers_the_horizontal_bar_too():
    """横滚条的粗细由 height 决定：只写 width 的话，日志区那条横滚条会退回引擎
    默认粗细（实测 17px），与竖条的 10px 一粗一细，明显是漏了一半。"""
    bar = rule("::-webkit-scrollbar")
    assert re.search(r"width:\s*(\d+)px", bar) and re.search(r"height:\s*(\d+)px", bar)
    assert re.search(r"width:\s*(\d+)px", bar).group(1) == re.search(
        r"height:\s*(\d+)px", bar
    ).group(1), "竖条与横条同一档粗细"


# ---------------------------------------------------------------------------
# 减少动态效果（prefers-reduced-motion）
# ---------------------------------------------------------------------------
#
# 静止段那条基线规则的选择器是 `*, *::before, *::after`：它够得到元素本身与
# 这两个**标准**伪元素，**够不到厂商伪元素**（`::-webkit-progress-bar` 这类）。
# 而厂商伪元素画在宿主元素的背景之上——用户真正看见的就是那一层，所以挂在
# 它们身上的动画必须在静止段里被**逐条点名**，否则开了「减少动态效果」的机器
# 上，页面上会动的东西照样在动。这个坑踩过一次：进度条的不定态动画就是这么
# 漏过去的（当时还误以为通配符管得住它）。
#
# 下面三条正则合起来把「有没有漏点名」变成可测的：切出静止段、从选择器里认出
# 厂商伪元素、剥掉注释。**剥注释是必需的**——静止段自己的注释里逐字写着
# `::-webkit-progress-bar` 这样的名字，不剥就会把「注释里提到了」误判成
# 「规则里点名了」，删掉规则、留着注释时闸门照样绿（这个假绿真的发生过）。
REDUCED_MOTION_RE = re.compile(
    r"(?m)^@media \(prefers-reduced-motion: reduce\)\s*\{\n(.*?)^\}", re.DOTALL
)

# 从选择器里认出厂商前缀伪元素，取回 `-webkit-progress-bar` 这一段用于比对。
VENDOR_PSEUDO_RE = re.compile(r"::(-[\w-]+)")

# 剥 CSS 注释。所有判据一律先剥再看，理由见上面那段。
CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def reduced_motion_block() -> str:
    """取出 `@media (prefers-reduced-motion: reduce)` 那段的内容，**去掉注释**。

    收尾靠行首的 `}`（段内的规则都缩进着），所以段里嵌几条规则、写多少注释
    都不影响。

    去注释是必需的，与 `rule_pos` 那条注释是同一个坑、验过一次才写进来的：
    这一段的注释里逐字写着 `::-webkit-progress-bar`（解释「为什么通配符够不
    到它」），不去注释的话「静止段里点了名」这条断言会被解释性文字喂饱——把
    规则删掉、注释留着，测试照样绿。
    """
    match = REDUCED_MOTION_RE.search(BASE)
    assert match, "base.css 里找不到 prefers-reduced-motion 那段"
    return CSS_COMMENT_RE.sub("", match.group(1))


# 「这条规则会动」的判据。三处宽度都别收窄：
#   · animation 与 transition 都算 —— 「减少动态效果」要停的本来就是两者，静止段
#     那条基线自己也是两者都写 `none !important`。只认 animation 的话，一条纯
#     transition 的厂商伪元素规则整条溜过去。
#   · **任何**长写法都算，不只 `-name` —— 原来的 `if "animation:" in block` 是子串
#     判据，对长写法一个字都匹配不上：往 base.css 加一条
#     `::-webkit-scrollbar-thumb.mutant { animation-name: … }`，旧判据整条扫不到、
#     test_layout.py 照样 56 passed。而只放宽到 `(-name)?` 仍然不够：
#     `transition-property` + `transition-duration` 是一个能真正跑起来的过渡，
#     里面**没有**任何 `transition:` 或 `transition-name:`；反过来 `transition-name`
#     这个属性 CSS 里压根不存在，专门为它开个口子等于既漏又空。所以这里认
#     `animation-*` / `transition-*` 的**全部**长写法。
#   · `\s*:` 容忍 `animation : linear` 这种属性名与冒号之间带空格的写法。
MOTION_DECL_RE = re.compile(r"\b(animation|transition)(-[\w-]+)?\s*:")


def animated_selectors(css: str | None = None) -> set[str]:
    """CSS 里（静止段之外）所有**会动**的规则的选择器，逗号拆开。

    「会动」= 规则体里有 animation 或 transition，简写与 `-name` 长写法都算，
    判据见上面的 MOTION_DECL_RE。

    同样先去注释：注释里出现的选择器与 animation / transition 字样都不是规则。

    `css` 留空就吃包内的 base.css（这是它的正职）；传进来是给判据自己的自证
    测试用的——不真喂一段 CSS 进去，「判据认不认长写法」只能靠读代码猜。
    """
    body = CSS_COMMENT_RE.sub("", REDUCED_MOTION_RE.sub("", BASE if css is None else css))
    found: set[str] = set()
    for selector, block in re.findall(r"(?m)^([^@{\n][^{\n]*?)\s*\{([^}]*)\}", body):
        if MOTION_DECL_RE.search(block):
            found.update(part.strip() for part in selector.split(","))
    return found


def test_reduced_motion_stops_everything_the_wildcard_can_reach():
    """基线那条：元素与 ::before/::after 上的动画/过渡全体静止。"""
    block = reduced_motion_block()
    assert "*, *::before, *::after" in block
    assert "animation: none !important" in block
    assert "transition: none !important" in block


def test_reduced_motion_names_the_progress_pseudo_elements_explicitly():
    """不定态进度条那层动画画在 ::-webkit-progress-bar 上，通配符够不到。

    reviewer 用 headless Chrome（与 WebView2 同引擎）带对照组逐像素实测过：
    加 `--force-prefers-reduced-motion` 之后同一页里的 <div> 已经停住，
    ::-webkit-progress-bar 还在动 —— 而它恰恰画在宿主背景之上，就是用户
    看到的那一层。所以这两个伪元素必须单独点名。
    """
    block = reduced_motion_block()
    match = re.search(
        r"progress::-webkit-progress-bar[^{]*\{([^}]*)\}", block
    )
    assert match, (
        "静止段里没点名 progress::-webkit-progress-bar —— 关掉动效对不定态"
        "进度条不起作用（通配符匹配不到厂商伪元素）"
    )
    assert "progress::-webkit-progress-value" in block
    assert "animation: none !important" in match.group(1)


def test_no_animation_hides_behind_a_selector_the_wildcard_cannot_reach():
    """一条通用闸门：往后新加的动画只要挂在厂商伪元素上，就得进静止段。

    先自证扫描本身没坏（已知那条不定态规则必须被扫到），再逐条核对：普通
    元素选择器交给通配符，`::-webkit-…` 这类逐个点名。
    """
    animated = animated_selectors()
    assert "progress:not([value])::-webkit-progress-bar" in animated, (
        "扫描没扫到已知的那条动画规则——扫描本身坏了，它的绿不作数"
    )
    block = reduced_motion_block()
    for selector in sorted(animated):
        pseudo = VENDOR_PSEUDO_RE.search(selector)
        if pseudo is None:
            continue  # 元素选择器：通配符那条已经罩住
        assert f"::{pseudo.group(1)}" in block, (
            f"{selector!r} 上有动画，但静止段里没点名 ::{pseudo.group(1)}——"
            "通配符 `*` 匹配不到厂商伪元素，这条动画在「减少动态效果」下照跑"
        )


def test_the_motion_scan_catches_longhand_and_transition_too():
    """自证扫描的**判据宽度**：判据每收窄一次，就漏一类真的会动的规则。

    这条测试是被两次真实的漏网口逼出来的：
      · 最早写的是 `if "animation:" in block`（子串判据），于是 `animation-name:`
        这种长写法一个字都匹配不上、整条规则扫不到；纯 `transition:` 的规则同样
        扫不到——可「减少动态效果」要停的本来就是两者，静止段那条基线自己就写着
        `animation: none; transition: none`。
      · 改成 `(-name)?` 之后还剩一个：`transition-property` + `transition-duration`
        是一个能真正跑起来的过渡，里面**没有**任何 `transition:`；而
        `transition-name` 这个属性 CSS 里压根不存在，专门为它开口子等于既漏又空。
    这些写法都能挂在厂商伪元素上，漏掉就等于那条动画在开了「减少动态效果」的
    机器上照跑，而闸门全绿。这里直接喂一段 CSS 进去逐样核对。
    """
    css = """
    .shorthand { animation: spin 1s linear; }
    .longhand { animation-name: spin; }
    .spaced { animation : spin 1s linear; }
    .transition-only { transition: background 200ms ease-out; }
    .transition-longhand { transition-property: background; transition-duration: 200ms; }
    .still { color: red; }
    """
    assert animated_selectors(css) == {
        ".shorthand",
        ".longhand",
        ".spaced",
        ".transition-only",
        ".transition-longhand",
    }


# ---------------------------------------------------------------------------
# 应用式版式（票 #21）：<body class="app"> 开启，整窗即容器
# ---------------------------------------------------------------------------
#
# 小工具窗（不挂 class="app"）一个像素不变是 spec #25 的第一条约束：已发版的
# 三个消费者全是 560×520 单列小窗，升级后不该看到任何版式变化。所以这一节的
# 版式规则**全部**挂在 `body.app` 之下——不挂开关类的页面一条都命中不到。


def test_app_body_turns_the_whole_window_into_the_container():
    """整窗即容器：去掉内容列宽与居中、内衬归零、竖排 flex、body 自己不滚。

    内容区（.pane / .rail）各自滚——body 一滚，顶栏和状态栏就跟着滚出窗外。
    """
    app = rule("body.app")
    assert "max-width: none" in app
    assert "margin: 0" in app
    assert "padding: 0" in app
    assert "display: flex" in app and "flex-direction: column" in app
    assert "overflow: hidden" in app


def test_app_body_drops_the_small_window_sibling_rhythm():
    """顶栏 / 多栏 / 状态栏是贴边拼起来的三段，body 级的块间距在这里归零。"""
    assert re.search(r"margin-top:\s*0\s*;", rule("body.app > * + *"))


# 只在应用式版式里才有意义的类：多栏骨架（.cols / .rail / .pane）、顶栏
# .top、底部状态栏 .status。它们的规则（含窄窗那段 @media 里的）一律挂在
# body.app 之下。.seg / .pill / .fade-in 是**部件**不是版式，小窗里也能用，
# 不在此列——它们是新类名，旧页面没写过，加了也命中不到旧元素。
APP_ONLY_CLASSES = ("app", "cols", "rail", "pane", "top", "status")


def all_selectors(css: str = BASE) -> list[str]:
    """CSS 里每一条规则的每一个选择器（逗号拆开、保留源码写法），含 @media 里
    嵌着的。解析逻辑只有一套：复用 msui.testing 给重定义闸门用的那份，这里
    只是不做归一（下面的断言按源码原文比对，如 "body > * + *"）。
    """
    return _css_selectors(css, normalize=False)


def is_app_scoped(selector: str) -> bool:
    return selector.startswith(("body.app", ":where(body.app"))


def test_every_app_layout_rule_hangs_under_the_body_app_switch():
    """不挂 class="app" 的页面一条都命中不到——「小窗一个像素不变」的文本层证明。

    先自证扫描没坏（已知的 body.app 规则、@media 里嵌着的规则都扫得到），
    再逐条核对：选择器里提到应用式专属类、或 [hidden] 这类全局改写的，必须以
    body.app 开头。全局焦点环 `:focus-visible` 0.14.0 起有意放到全局（小窗也要
    看得见 Tab 走到了哪），不在这条里，由 test_focus_ring_is_global_and_token_coloured 盯着。
    """
    selectors = all_selectors()
    assert "body.app" in selectors, "扫描没扫到 body.app——扫描本身坏了，它的绿不作数"
    assert "progress::-webkit-progress-bar" in selectors, "@media 里嵌着的规则没扫到"
    pattern = re.compile(r"\.(?:" + "|".join(APP_ONLY_CLASSES) + r")(?![\w-])|\[hidden\]")
    leaks = [s for s in selectors if pattern.search(s) and not is_app_scoped(s)]
    assert not leaks, f"这些规则没挂在 body.app 下，会漏进小工具窗：{leaks}"


def test_the_small_window_body_rules_are_the_only_unscoped_body_rules():
    """小窗那几条 body 规则之外，不许再出现不带开关的 body 选择器。

    新版式要改 body 时只能写 `body.app …`；直接改 `body` 等于改了所有消费者。
    """
    # 按出现次数比（不是集合）：`html, body` 已经贡献了一个 "body"，再新增一条
    # `html, body { … }` 的话集合看不出来，计数看得出来。
    unscoped = sorted(
        s for s in all_selectors() if re.search(r"\bbody\b", s) and not is_app_scoped(s)
    )
    assert unscoped == ["body", "body", "body > * + *"], unscoped


def test_the_small_window_body_rule_gains_no_new_properties():
    """小窗 body 那条规则的属性集合钉死在 0.9.0 的样子。

    上一条只管「没有新的不带开关的 body 选择器」，管不到有人图省事把
    display: flex / overflow: hidden 直接塞进现有的 `body { … }`——那同样是改了
    所有消费者。应用式要的东西一律写进 `body.app`。
    """
    declarations = CSS_COMMENT_RE.sub("", rule("body")).split(";")
    props = {d.split(":")[0].strip() for d in declarations if d.strip()}
    assert props == {
        "color", "font-family", "font-size", "-webkit-font-smoothing",
        "max-width", "margin-inline", "padding",
    }, props


# ---------------------------------------------------------------------------
# 多栏骨架：.cols > .rail（定宽左栏）+ .pane（主区）
# ---------------------------------------------------------------------------


def test_cols_fills_the_rest_of_the_window_and_may_shrink():
    """多栏行吃掉顶栏与状态栏之外的全部高度；min-height: 0 让它肯缩，
    里面的 .pane / .rail 才滚得起来（不归零的话内容一长就把状态栏顶出窗外）。"""
    cols = rule("body.app .cols")
    assert "display: flex" in cols
    assert re.search(r"flex: 1\b", cols)
    assert "min-height: 0" in cols


def test_rail_is_a_fixed_width_scrolling_side_column():
    rail = rule("body.app .rail")
    assert "flex: 0 0 var(--rail-width)" in rail, "左栏定宽走 --rail-width 一个 token"
    assert "border-right: 1px solid var(--border)" in rail
    assert "overflow: auto" in rail
    assert re.search(r"padding: var\(--space-\d\)", rail)


def test_pane_grows_and_must_be_allowed_to_shrink_below_its_content():
    """⚠️ min-width: 0 漏了整个布局崩掉不报错：宽表格把 .pane 撑到内容宽，
    左栏被挤扁、横滚条落到整窗上。min-height: 0 同理（.pane 直接挂在 body.app
    下、不包 .cols 时，竖向也要肯缩才滚得起来）。"""
    pane = rule("body.app .pane")
    assert re.search(r"flex: 1\b", pane)
    assert "min-width: 0" in pane
    assert "min-height: 0" in pane
    assert "overflow: auto" in pane
    assert re.search(r"padding: var\(--space-\d\)", pane)


def test_rail_width_token_exists_and_is_whitelisted():
    assert TOKENS.get("rail-width", "").endswith("px")
    assert "rail-width" in NON_HEX_TOKENS


def test_narrow_window_stacks_the_rail_on_top():
    """窄窗（< 900px）左栏退到上面：多栏改竖排，左栏的右边线换成下边线。"""
    match = re.search(
        r"(?m)^@media \(max-width: 900px\)\s*\{\n(.*?)^\}", BASE, re.DOTALL
    )
    assert match, "base.css 里找不到窄窗那段 @media (max-width: 900px)"
    narrow = CSS_COMMENT_RE.sub("", match.group(1))
    cols = re.search(r"body\.app \.cols\s*\{([^}]*)\}", narrow)
    rail = re.search(r"body\.app \.rail\s*\{([^}]*)\}", narrow)
    assert cols and "flex-direction: column" in cols.group(1)
    assert rail and "border-right: 0" in rail.group(1)
    assert "border-bottom: 1px solid var(--border)" in rail.group(1)


def test_pane_rhythm_never_outranks_the_heading_lede_pair():
    """主区里的块间距与小窗 body 同一档，但特异性必须压到 0。

    `h1 + p`（0,0,2）的紧排要压过块间距；写成 `body.app .pane > * + *`
    （0,2,1）的话，主区里每个标题和它的说明段都会被拉开一整档。所以选择器
    包在 :where() 里，特异性归零、靠源码顺序压过 `* { margin: 0 }`。
    """
    flow = rule(":where(body.app .pane) > * + *")
    assert re.search(r"margin-top: var\(--space-\d\)", flow)
    assert rule_pos(":where(body.app .pane) > * + *") > rule_pos("*"), (
        "特异性归零之后靠源码顺序胜出，必须写在 `* { margin: 0 }` 之后"
    )


# ---------------------------------------------------------------------------
# 顶栏 .top + 分段 .seg + 徽章 .pill；底部状态栏 .status
# ---------------------------------------------------------------------------


def test_top_bar_is_a_single_centred_row():
    top = rule("body.app .top")
    assert "display: flex" in top and "align-items: center" in top
    assert re.search(r"gap: var\(--space-\d\)", top)
    assert re.search(r"padding: var\(--space-\d\) var\(--space-\d\)", top)
    assert "flex-wrap: wrap" in top, "窄窗放不下时折行，不许横向溢出"


def test_grow_pushes_the_rest_of_a_flex_row_to_the_far_end():
    """`<span class="grow"></span>`：顶栏里把徽章推到最右的那根弹簧。"""
    assert re.search(r"flex: 1\b", rule(".grow"))


def test_status_bar_is_a_thin_muted_strip_with_a_top_rule():
    status = rule("body.app .status")
    assert "display: flex" in status and "align-items: center" in status
    assert "border-top: 1px solid var(--border)" in status
    assert "color: var(--muted)" in status
    assert "font-variant-numeric: tabular-nums" in status, "版本号 / 计数跳动时不晃"
    assert re.search(r"padding: var\(--space-\d\) var\(--space-\d\)", status)


def test_seg_is_a_card_coloured_track_of_borderless_buttons():
    seg = rule(".seg")
    assert "display: inline-flex" in seg
    assert "background: var(--card)" in seg and "border: 1px solid var(--border)" in seg
    button = rule(".seg button")
    assert "border: 0" in button and "background: none" in button


def test_seg_marks_the_current_option_with_on():
    on = rule(".seg button.on")
    assert "background: var(--wash)" in on and "color: var(--text)" in on
    assert "font-weight: 600" in on


def test_seg_button_overrides_the_base_button_by_source_order():
    """`.seg button`（0,1,1）与 `button:hover`（0,1,1）同分，靠写在后面取胜——
    否则分段里的按钮 hover 时会冒出通用按钮那块提亮底。"""
    assert rule_pos(".seg button") > rule_pos("button:hover, .btn:hover")


PILL_STATES = ("ok", "warn", "info", "error")


def test_pill_is_a_neutral_capsule_by_default():
    pill = rule(".pill")
    assert "border-radius: 999px" in pill
    assert "white-space: nowrap" in pill
    assert "color: var(--muted)" in pill and "background: var(--wash)" in pill
    assert "display" not in pill, (
        "同 .notice：显示/隐藏靠 hidden 属性，写了 display 会盖掉 UA 的 [hidden]"
    )


@pytest.mark.parametrize("state", PILL_STATES)
def test_each_pill_state_paints_its_tint_and_solid_text(state: str):
    block = rule(f".pill.{state}")
    assert f"background: var(--{state}-bg)" in block
    assert f"color: var(--{state})" in block


def test_app_hidden_really_hides_even_over_author_display():
    """应用式页面里 display: flex 的块到处都是，作者层的 display 会盖掉 UA 的
    `[hidden] { display: none }`。在 body.app 下把它钉回来；小窗不动。"""
    assert "display: none !important" in rule("body.app [hidden]")


def test_focus_ring_is_global_and_token_coloured():
    """0.14.0 起焦点环不分版式：小窗里的输入框原来只靠 --border → --border-hover
    换边（深色 1.26:1、浅色 1.16:1），够不到焦点可见的 3:1。"""
    ring = rule(":focus-visible")
    assert re.search(r"outline: 2px solid var\(--info\)", ring)
    assert "outline-offset: 2px" in ring
    assert "body.app :focus-visible" not in all_selectors(), "旧的只挂 body.app 的那条该删了"


# 新部件画出来的「前景 × 底」组合。每一条：规则里真用了那个前景 token（防止
# 这张表与 CSS 脱节），且这一对已在 testing.BASE_TOKEN_PAIRS 里登记——登记了
# 就意味着深色与浅色两套 token 都过同一道闸门（test_testing 跑全表）。
# 底只有 card / win 两种：部件要么摆在窗底上（顶栏、状态栏），要么摆在卡片里；
# 半透明的 --wash / --*-bg 叠在它们上面，可读性由透出来的实色底承担（与 .notice
# 同一惯例）。
# 状态点 .dot 的四个状态，名字与 .pill / .notice 同一套。
DOT_STATES = ("ok", "warn", "info", "error")

# 运行日志区组头的状态字：运行中 info、成功 ok、失败 error（已停止用裸 .st 的 text-dim）。
RUNLOG_STATUS_COLOURS = (("running", "info"), ("ok", "ok"), ("error", "error"))

WIDGET_PAIRS = (
    (".seg", "border", "card"),
    (".seg", "border", "win"),
    (".seg button", "text-dim", "card"),
    (".seg button.on", "text", "card"),
    (".seg button:hover", "text", "card"),
    (".pill", "muted", "card"),
    (".pill", "muted", "win"),
    *((f".pill.{s}", s, "card") for s in PILL_STATES),
    *((f".pill.{s}", s, "win") for s in PILL_STATES),
    ("body.app .status", "muted", "win"),
    ("body.app .status", "border", "win"),
    ("body.app .rail", "border", "win"),
    (":focus-visible", "info", "win"),
    (":focus-visible", "info", "card"),
    # ---- 票 #22：列表页 / 设置页部件 ----
    (".grid", "border", "card"),
    (".grid", "border", "win"),
    (".grid tbody tr.sel", "brand", "card"),
    (".chip", "text-dim", "card"),
    (".chip", "border", "card"),
    (".chip", "border", "win"),
    (".chip:hover", "text", "card-hover"),
    (".chip.on", "text", "card"),
    (".chip.on", "text", "win"),
    (".chip.on", "border-hover", "card"),
    (".chip.on", "border-hover", "win"),
    (".chip .n", "muted", "card"),
    (".search", "border", "card"),
    (".search", "border", "win"),
    (".search", "muted", "card"),
    (".search:focus-within", "border-hover", "card"),
    (".search:focus-within", "border-hover", "win"),
    (".search input", "text", "card"),
    # 开关两态：关态描边两侧（外 card / win、内 track）+ 滑块对轨道；开态品牌块
    # 对外侧底 + 滑块对品牌色；hover 换的那圈边同样两侧都登记。
    ("button.switch", "border", "card"),
    ("button.switch", "border", "win"),
    ("button.switch", "border", "track"),
    ("button.switch::after", "text-dim", "track"),
    ("button.switch:hover", "border-hover", "card"),
    ("button.switch:hover", "border-hover", "win"),
    ("button.switch:hover", "border-hover", "track"),
    ('button.switch[aria-checked="true"]', "brand", "card"),
    ('button.switch[aria-checked="true"]', "brand", "win"),
    ('button.switch[aria-checked="true"]::after', "on-brand", "brand"),
    (".dot::before", "muted", "card"),
    (".dot::before", "muted", "win"),
    *((f".dot.{s}::before", s, "card") for s in DOT_STATES),
    *((f".dot.{s}::before", s, "win") for s in DOT_STATES),
    # ---- 票 #27：小标题、步骤卡、读数卡 ----
    # 步骤卡平时直接摆在窗底上（左栏），当前态铺 card 底，所以卡里的字两种底都登记；
    # 编号圆圈自己的底是 --win，圆圈的边与完成态的品牌块外侧挨着 win 或 card。
    (".eyebrow", "muted", "card"),
    (".eyebrow", "muted", "win"),
    (".eyebrow .n", "text-dim", "card"),
    (".eyebrow .n", "text-dim", "win"),
    (".step.cur", "border", "card"),
    (".step.cur", "border", "win"),
    (".step .num i", "text-dim", "win"),
    (".step .num i", "border-hover", "win"),
    (".step .num i", "border-hover", "card"),
    (".step.cur .num i", "text", "win"),
    (".step.cur .num i", "brand", "win"),
    (".step.cur .num i", "brand", "card"),
    (".step.done .num i", "on-brand", "brand"),
    (".step.done .num i", "brand", "win"),
    (".step.done .num i", "brand", "card"),
    (".step .title", "text", "win"),
    (".step .title", "text", "card"),
    (".step .meta", "muted", "win"),
    (".step .meta", "muted", "card"),
    (".step .meta b", "text-dim", "win"),
    (".step .meta b", "text-dim", "card"),
    *((f".step .meta.{k}", t, bg) for k, t in (("fail", "error"), ("hint", "warn"), ("good", "ok"))
      for bg in ("win", "card")),
    (".step.wait .num i, .step.wait .title, .step.wait .meta, .step.wait .meta b", "muted", "win"),
    (".step.wait .num i, .step.wait .title, .step.wait .meta, .step.wait .meta b", "muted", "card"),
    (".step .param > label", "text-dim", "win"),
    (".step .param > label", "text-dim", "card"),
    (".step[tabindex]:hover", "border-hover", "win"),
    (".step[tabindex]:hover", "border-hover", "card"),
    (".step:focus-visible", "info", "win"),
    (".step:focus-visible", "info", "card"),
    (".kpi .lbl", "muted", "card"),
    (".kpi .val", "text", "card"),
    (".kpi .val small", "muted", "card"),
    (".kpi .sub", "text-dim", "card"),
    (".kpi .sub span + span::before", "muted", "card"),
    (".kpi .sub .dim", "muted", "card"),
    (".kpi.warn .val", "warn", "card"),
    # ---- 票 #29：运行日志区 ----
    # 日志区的滚动区自己铺 --win 底（摆在卡片里、窗底上都一样），所以里面的字只对
    # win 登记；外框那圈 --border 外侧挨着的可能是卡片也可能是窗底，两边都登记。
    # 失败行 / 失败组的 --error-bg 是半透明晕染，透出来的还是 win（同 .notice 惯例）。
    (".runlog-list", "border", "win"),
    (".runlog-list", "border", "card"),
    (".runlog-head .tm, .runlog-line .tm", "muted", "win"),
    # 已停止（裸 .st）用次要色：它是结论，不是「看得见就行」的提示（审查修复）
    (".runlog-head .st", "text-dim", "win"),
    *((f".runlog-head .st.{s}", t, "win") for s, t in RUNLOG_STATUS_COLOURS),
    (".runlog-head .nm", "text", "win"),
    (".runlog-head .rs", "text-dim", "win"),
    (".runlog-run.error .rs", "error", "win"),
    (".runlog-head:focus-visible", "info", "win"),
    (".runlog-line .lv", "info", "win"),
    (".runlog-line.warn .lv", "warn", "win"),
    (".runlog-line.error .lv", "error", "win"),
    (".runlog-line .tx", "text", "win"),
)

COLOUR_PROPS_RE = re.compile(
    r"\b(color|background(?:-color)?|border(?:-[a-z]+)*|outline(?:-color)?)\s*:\s*([^;]+);"
)


@pytest.mark.parametrize("selector", sorted({s for s, _, _ in WIDGET_PAIRS}))
def test_new_widget_colours_come_only_from_tokens(selector: str):
    """新部件的每一条着色声明只许是 var(--token)（或 none / 0 / transparent）。"""
    for prop, value in COLOUR_PROPS_RE.findall(rule(selector)):
        if prop.startswith("border") and ("radius" in prop or "width" in prop):
            continue
        rest = re.sub(r"var\(--[\w-]+\)", "", value)
        rest = re.sub(r"\b(none|transparent|0|solid|\d+px)\b", "", rest)
        assert not rest.strip(), f"{selector} 的 {prop} 写了 token 之外的东西：{value!r}"


@pytest.mark.parametrize(("selector", "fg", "bg"), WIDGET_PAIRS)
def test_new_widget_pairs_are_registered_for_both_themes(selector: str, fg: str, bg: str):
    from msui.testing import BASE_TOKEN_PAIRS

    assert f"var(--{fg})" in rule(selector), f"{selector} 里没用 --{fg}，这张表与 CSS 脱节了"
    registered = {(p.foreground, p.background) for p in BASE_TOKEN_PAIRS}
    assert (fg, bg) in registered, (
        f"{selector} 把 --{fg} 画在 --{bg} 上，但这一对没在 BASE_TOKEN_PAIRS 里登记"
    )


# ---------------------------------------------------------------------------
# 进场动效 .fade-in：卡片 / 区块进场时上浮淡入
# ---------------------------------------------------------------------------


def test_fade_in_rises_and_fades_through_its_own_keyframes():
    """关键帧带 msui- 前缀（与 msui-progress-loop 同一惯例），不跟页面自己的撞名。"""
    fade = rule(".fade-in")
    assert "animation: msui-card-in var(--motion-enter) var(--ease-enter)" in fade
    assert "both" in fade, "fill-mode both：延迟期间停在起始帧，不先闪一下终态"
    assert "var(--i, 0)" in fade, "错峰靠元素上的 --i 序号，缺省 0"
    frames = re.search(r"@keyframes msui-card-in\s*\{(.*?)\n\}", BASE, re.DOTALL)
    assert frames, "进场动效的关键帧不见了"
    assert "opacity: 0" in frames.group(1) and "translateY" in frames.group(1)


def test_fade_in_is_stopped_by_reduced_motion():
    """新动效必须被「减少动态效果」管住。

    .fade-in 挂在元素上（不是厂商伪元素），归静止段的通配符基线管：先确认
    扫描认得出它是一条会动的规则，再确认它没躲到通配符够不到的伪元素上、
    基线那条确实把 animation 停掉。fill-mode both 的起始帧是 opacity 0——
    animation: none 之后元素直接以终态（不透明）出现，不会停在看不见的那一帧。
    """
    animated = animated_selectors()
    assert ".fade-in" in animated, "扫描没认出 .fade-in 会动——扫描坏了，它的绿不作数"
    assert VENDOR_PSEUDO_RE.search(".fade-in") is None
    baseline = re.search(r"\*, \*::before, \*::after\s*\{([^}]*)\}", reduced_motion_block())
    assert baseline, "静止段里找不到通配符基线那条"
    assert "animation: none !important" in baseline.group(1), (
        "通配符基线不停 animation 的话 .fade-in 照跑（静止段里别的规则停的是伪元素）"
    )


# ---------------------------------------------------------------------------
# 列表页 / 设置页部件（票 #22）：数据网格 .grid、工具条 .toolbar + 筛选片 .chip、
# 搜索框 .search、开关 button.switch、图标按钮 button.icon、状态点 .dot
# ---------------------------------------------------------------------------
#
# 与 .seg / .pill 同一性质：是**部件**不是版式，小窗与应用式都能用；全是新类名，
# 已发版消费者的页面一个都没写过，命中不到旧元素（小窗一个像素不变）。


def test_grid_is_a_bounded_scroller_around_a_plain_table():
    """`<div class="grid"><table>…</table></div>`：外框自己横竖滚、限高，
    窗口不跟着被宽表撑出横滚条。外框画成一张卡（底 / 描边 / 圆角同 .card）。"""
    grid = rule(".grid")
    assert "overflow: auto" in grid
    assert re.search(r"max-height: \d+vh", grid)
    assert "background: var(--card)" in grid
    assert "border: 1px solid var(--border)" in grid
    assert "border-radius: 10px" in rule(".card") and "border-radius: 10px" in grid


def test_grid_header_sticks_while_the_body_scrolls():
    """粘表头：滚动时表头钉在外框顶上；必须有不透明底，否则滚过去的行从
    表头底下透出来。"""
    th = rule(".grid th")
    assert "position: sticky" in th and "top: 0" in th
    assert "background: var(--card)" in th
    assert "white-space: nowrap" in th


def test_grid_cells_never_wrap_and_numbers_line_up():
    td = rule(".grid td")
    assert "white-space: nowrap" in td, "宽表靠横滚，不靠折行"
    assert "font-variant-numeric: tabular-nums" in td
    assert "text-align: right" in rule("td.num, th.num"), "数字列右对齐（表头跟着）"


def test_grid_selected_row_gets_a_brand_strip_on_the_left():
    """选中行：--wash 提亮 + 左侧 3px 品牌色条（inset 阴影画，不占列宽）。"""
    sel = rule(".grid tbody tr.sel")
    assert "background: var(--wash)" in sel
    assert "box-shadow: inset 3px 0 0 var(--brand)" in sel


def test_toolbar_is_a_wrapping_centred_row_that_kills_the_card_rhythm():
    """工具条：筛选片 + 搜索框 + 弹簧 .grow + 右侧动作一行排开，窄窗折行。
    `<div class="card toolbar">` 整卡即一条时，与 .actions / .field 同一个先例：
    `.toolbar > * + *` 与 `.card > * + *` 同分，靠写在后面把竖向节奏压掉。"""
    bar = rule(".toolbar")
    assert "display: flex" in bar and "align-items: center" in bar
    assert "flex-wrap: wrap" in bar
    assert re.search(r"gap: var\(--space-\d\)", bar)
    assert "margin-top: 0" in rule(".toolbar > * + *")
    assert rule_pos(".toolbar > * + *") > rule_pos(".card > * + *")


def test_chip_is_a_capsule_button_with_an_on_state():
    chip = rule(".chip")
    assert "border-radius: 999px" in chip
    assert "border: 1px solid var(--border)" in chip
    assert "background: var(--card)" in chip and "color: var(--text-dim)" in chip
    on = rule(".chip.on")
    assert "background: var(--wash)" in on and "color: var(--text)" in on
    assert "font-weight: 600" in on
    count = rule(".chip .n")
    assert "color: var(--muted)" in count and "tabular-nums" in count


def test_chip_beats_the_base_button_hover_and_on_beats_chip_hover():
    """`.chip:hover`（0,2,0）本就压过 `button:hover`（0,1,1）；而 `.chip.on` 与
    `.chip:hover` 同为 (0,2,0)，当前项被悬停时靠源码顺序保住 --wash 底。"""
    assert rule_pos(".chip:hover") > rule_pos("button:hover, .btn:hover")
    assert rule_pos(".chip.on") > rule_pos(".chip:hover")


def test_search_is_one_framed_field_with_a_borderless_input_inside():
    """`<label class="search"><svg…/><input type="search"><button class="icon">…</label>`：
    框画在 label 上（底 / 描边 / 圆角与输入框同档），里面的 input 去掉自己的框；
    焦点落进来时整个框换 hover 边（:focus-within），与 .input 同一个手感。"""
    box = rule(".search")
    assert "display: flex" in box and "align-items: center" in box
    assert "background: var(--card)" in box and "border: 1px solid var(--border)" in box
    assert "color: var(--muted)" in box, "放大镜 svg 走 currentColor，弱化档"
    assert "border-color: var(--border-hover)" in rule(".search:focus-within")
    field = rule(".search input")
    assert "border: 0" in field and "background: none" in field
    assert "flex: 1" in field and "min-width: 0" in field
    assert "color: var(--text)" in field


def test_search_input_overrides_the_base_input_focus_by_source_order():
    """`.search input`（0,1,1）与 `input:focus`（0,1,1）同分：写在前面的话输入框
    一获焦就在框里再画一圈边。"""
    assert rule_pos(".search input") > rule_pos(
        "input:focus, textarea:focus, select:focus, .input:focus-within"
    )


def test_switch_off_state_is_a_recessed_track_with_a_readable_knob():
    """`<button class="switch" role="switch" aria-checked="false">`：34×20 胶囊。

    关态不照抄参考实现的「--border-hover 轨道 + --on-brand 滑块」：那一对浅色下
    只有 1.97:1，过不了控件档 3.0。改成与进度条同一套凹陷槽——轨道 --track +
    一圈 --border 描边画出边界，滑块 --text-dim（对 track 深 7.67 / 浅 6.1）。"""
    sw = rule("button.switch")
    assert "width: 34px" in sw and "height: 20px" in sw
    assert "border-radius: 999px" in sw and "padding: 0" in sw
    assert "position: relative" in sw, "滑块绝对定位在轨道里"
    assert "background: var(--track)" in sw
    assert "border: 1px solid var(--border)" in sw
    knob = rule("button.switch::after")
    assert 'content: ""' in knob and "position: absolute" in knob
    assert "background: var(--text-dim)" in knob
    assert "transition: transform" in knob, "滑块滑过去，不是瞬移"


def test_switch_on_state_is_a_brand_track_with_an_on_brand_knob():
    on = rule('button.switch[aria-checked="true"]')
    assert "background: var(--brand)" in on and "border-color: var(--brand)" in on
    knob = rule('button.switch[aria-checked="true"]::after')
    assert "background: var(--on-brand)" in knob
    assert "transform: translateX(14px)" in knob


def test_switch_hover_never_repaints_the_on_track():
    """hover 只把关态的边换成 --border-hover，开态整块不变色：参考实现开态 hover
    换 --brand-down，它对 card 只有 2.53:1（深色），掉出控件档。
    `button.switch:hover` 与开态规则同为 (0,2,1)，开态写在后面才压得住；
    两条都在通用按钮之后，才盖得掉 `button:hover` 那块 --wash 提亮底。"""
    hover = rule("button.switch:hover")
    assert "background: var(--track)" in hover
    assert "border-color: var(--border-hover)" in hover
    assert rule_pos('button.switch[aria-checked="true"]') > rule_pos("button.switch:hover")
    assert rule_pos("button.switch:hover") > rule_pos("button:hover, .btn:hover")
    assert "brand-down" not in BASE[rule_pos("button.switch"):rule_pos(".dot::before")]


def test_switch_motion_is_stopped_by_reduced_motion():
    """开关的轨道变色与滑块滑动都是 transition，挂在元素与 ::after 上——
    通配符基线 `*, *::before, *::after` 罩得住（不是厂商伪元素）。"""
    animated = animated_selectors()
    assert "button.switch" in animated and "button.switch::after" in animated
    for selector in ("button.switch", "button.switch::after"):
        assert VENDOR_PSEUDO_RE.search(selector) is None
    assert "*::after" in reduced_motion_block()


def test_dot_is_drawn_by_a_pseudo_element_so_the_host_stays_inline():
    """`<span class="dot ok"></span>已同步` 或 `<span class="dot ok">已同步</span>`：
    7px 圆点画在 ::before 上。参考实现给 .dot 本体写 display: inline-block——
    那会盖掉 hidden（小窗没有 body.app [hidden] 兜底）；挪到伪元素上，本体保持
    行内、hidden 照常收得起来。裸 .dot 是中性 --muted 点。"""
    dot = rule(".dot::before")
    assert 'content: ""' in dot and "display: inline-block" in dot
    assert "width: 7px" in dot and "height: 7px" in dot
    assert "border-radius: 999px" in dot
    assert "background: var(--muted)" in dot


@pytest.mark.parametrize("state", DOT_STATES)
def test_each_dot_state_paints_its_solid_colour(state: str):
    assert f"background: var(--{state})" in rule(f".dot.{state}::before")


DISPLAY_DECL_RE = re.compile(r"(?<![\w-])display\s*:")


def host_rules_declaring_display(cls: str, css: str = BASE) -> list[str]:
    """CSS 里所有落在 `.cls` **本体**上（不是 ::before 这类伪元素、也不是它的
    后代）且写了 display 的选择器。含 @media 里嵌着的；先剥注释。

    「落在本体上」= 选择器最后一个复合段里有 `.cls`、且没有 `::`。
    """
    body = CSS_COMMENT_RE.sub("", css)
    body = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^}]*\})*\s*\}", "", body)
    hits: list[str] = []
    for head, block in re.findall(r"([^{};]+)\{([^{}]*)\}", body):
        if not DISPLAY_DECL_RE.search(block):
            continue
        for part in head.strip().split(","):
            last = re.split(r"[\s>+~]+", part.strip())[-1]
            if re.search(re.escape(cls) + r"(?![\w-])", last) and "::" not in last:
                hits.append(part.strip())
    return hits


def test_icon_button_is_a_square_that_centres_its_svg():
    """图标按钮：正方形、内衬归零，内联 svg 成块居中、16px、颜色跟 currentColor
    走（按钮的字色、hover 变亮都跟着变）。正方形与 .seg 按钮同档圆角。"""
    icon = rule("button.icon")
    assert re.search(r"width: (\d+)px", icon) and re.search(r"height: (\d+)px", icon)
    assert re.search(r"width: (\d+)px", icon).group(1) == re.search(r"height: (\d+)px", icon).group(1)
    assert "padding: 0" in icon
    svg = rule("button.icon > svg")
    assert "display: block" in svg and "margin: auto" in svg
    assert "width: 16px" in svg and "height: 16px" in svg


@pytest.mark.parametrize("cls", [".chip", ".icon", ".switch", ".dot", ".field-error"])
def test_toggleable_widgets_never_declare_display(cls: str):
    """这四样是页面会拿 hidden 收放的（清除叉有字才出现、开关跟着权限出没、
    状态点按状态出没……）。小窗里没有 `body.app [hidden]` 那条兜底，作者层的
    任何 display 都会盖掉 UA 的 `[hidden] { display: none }`——同 .notice / .pill。
    居中、撑宽高这类要 display 的活交给子元素或伪元素去做。"""
    leaks = host_rules_declaring_display(cls)
    assert not leaks, f"这些规则给 {cls} 本体写了 display，hidden 收不起来：{leaks}"


def test_display_scan_is_not_blind():
    """自证判据：本体上写 display 的认得出（含 @media 里、选择器列表里的），
    伪元素与后代上的不算，注释里的不算，`-webkit-box-display` 这类别的属性不算。"""
    css = """
    .dot { display: inline-block; }
    .x, .chip.on { display: flex; }
    @media (max-width: 900px) {
      button.switch:hover { display: block; }
    }
    .dot::before { display: inline-block; }
    .icon > svg { display: block; }
    /* .icon { display: grid; } */
    .icon { -webkit-box-display: x; }
    """
    assert host_rules_declaring_display(".dot", css) == [".dot"]
    assert host_rules_declaring_display(".chip", css) == [".chip.on"]
    assert host_rules_declaring_display(".switch", css) == ["button.switch:hover"]
    assert host_rules_declaring_display(".icon", css) == []
    assert host_rules_declaring_display(".toolbar") == [".toolbar"]


# ---------------------------------------------------------------------------
# 票 #27：小标题 .eyebrow、步骤卡 .step、读数卡 .kpis / .kpi、整句列 td.wrap、
# 主题切换按钮、文字可选。模版是第三个消费者（宽表格程序）的现行写法，另外
# 两三个消费者抄过去后改好的地方择优合入。全是新类名，旧页面命中不到。
# ---------------------------------------------------------------------------


def test_eyebrow_is_a_small_caps_like_muted_row():
    """区块小标题：一行排开、字小、字距拉开、弱化灰字；计数 .n 次要色不拉字距。"""
    eyebrow = rule(".eyebrow")
    assert "display: flex" in eyebrow and "align-items: center" in eyebrow
    assert re.search(r"gap: var\(--space-\d\)", eyebrow)
    assert "font-size: 11px" in eyebrow and "letter-spacing: .08em" in eyebrow
    assert "color: var(--muted)" in eyebrow
    count = rule(".eyebrow .n")
    assert "color: var(--text-dim)" in count and "letter-spacing: 0" in count


def test_eyebrow_title_never_wraps_under_a_long_note():
    """标题 .t 不被后面的长说明挤成两行：不折行、不参与收缩。"""
    title = rule(".eyebrow .t")
    assert "white-space: nowrap" in title and "flex: none" in title


def test_step_is_a_rounded_block_with_an_invisible_border_until_current():
    """步骤卡平时没底没边（边框透明占位，切到当前态时不跳一像素）；当前态 .cur
    是卡片底 + 分隔线边。"""
    step = rule(".step")
    assert "border: 1px solid transparent" in step
    assert "border-radius: 10px" in step
    cur = rule(".step.cur")
    assert "background: var(--card)" in cur and "border-color: var(--border)" in cur


def test_step_number_is_a_ring_that_fills_with_brand_when_done():
    """编号圆圈：默认窗底 + 一圈 border-hover、次要色数字；当前态描边换品牌色、
    数字主色；完成态整颗品牌色、数字走 --on-brand（浅色主题下品牌红底上的字
    仍是白的，借道 --text 就成了红底黑字）。"""
    ring = rule(".step .num i")
    assert "border-radius: 999px" in ring
    assert "border: 2px solid var(--border-hover)" in ring
    assert "background: var(--win)" in ring and "color: var(--text-dim)" in ring
    assert "font-style: normal" in ring
    cur = rule(".step.cur .num i")
    assert "border-color: var(--brand)" in cur and "color: var(--text)" in cur
    done = rule(".step.done .num i")
    assert "background: var(--brand)" in done and "border-color: var(--brand)" in done
    assert "color: var(--on-brand)" in done


def test_done_beats_current_by_source_order():
    """`.step.cur .num i` 与 `.step.done .num i` 同分 (0,3,1)；既完成又是当前
    的那一步（用户点回去看）编号要保持实心——完成态写在后面取胜。参考实现把
    完成态写在前面，于是两个消费者各自补了一条 `.step.cur.done`。"""
    assert rule_pos(".step.done .num i") > rule_pos(".step.cur .num i")


def test_waiting_step_is_muted_by_colour_not_by_opacity():
    """等待态换弱化前景，不用 opacity：半透明的字对比度闸门算不出来、会漏检。"""
    for selector in all_selectors():
        if ".step" in selector:
            block = rule_containing(selector)
            assert "opacity" not in block, f"{selector} 用了 opacity"
    wait = rule(".step.wait .num i, .step.wait .title, .step.wait .meta, .step.wait .meta b")
    assert "color: var(--muted)" in wait


def rule_containing(selector: str) -> str:
    """含这个选择器（在选择器列表里任一位置）的那条规则的声明块。"""
    body = CSS_COMMENT_RE.sub("", BASE)
    for head, block in re.findall(r"([^{};]+)\{([^{}]*)\}", body):
        if selector in [part.strip() for part in head.split(",")]:
            return block
    raise AssertionError(f"base.css 里找不到含 {selector!r} 的规则")


@pytest.mark.parametrize(("kind", "token"), [("fail", "error"), ("hint", "warn"), ("good", "ok")])
def test_step_meta_has_three_semantic_colours(kind: str, token: str):
    assert f"color: var(--{token})" in rule(f".step .meta.{kind}")


def test_step_meta_is_a_small_muted_line_that_breaks_long_paths():
    meta = rule(".step .meta")
    assert "color: var(--muted)" in meta and "font-size: 12px" in meta
    assert "overflow-wrap: anywhere" in meta, "说明行里常有长路径，不断开会撑破左栏"


def test_step_actions_wrap_and_fill_the_narrow_rail():
    """动作按钮行：窄左栏里自动折行、按钮占满宽度。"""
    act = rule(".step .act")
    assert "display: flex" in act and "flex-wrap: wrap" in act
    assert re.search(r"gap: var\(--space-\d\)", act)
    assert "flex: 1 1 auto" in rule(".step .act > button, .step .act > .btn")


def test_step_param_stacks_label_above_a_full_width_input():
    """参数行：标签在上、输入框占满（左栏放不下 .field 那种左右排）。"""
    param = rule(".step .param")
    assert "display: flex" in param and "flex-direction: column" in param
    assert "color: var(--text-dim)" in rule(".step .param > label")
    row = rule(".step .param .row")
    assert "display: flex" in row
    assert "min-width: 0" in rule(".step .param .row > input")


def test_step_can_hold_a_progress_bar():
    assert re.search(r"margin-top: var\(--space-\d\)", rule(".step progress"))


def test_clickable_step_is_reachable_by_tab_with_the_app_focus_ring():
    """可点的步骤卡写 tabindex="0"：手形光标、悬停换边；焦点环与 body.app 同一档
    （小窗里没有 body.app 那条全局焦点环，这里自己带）。"""
    assert "cursor: pointer" in rule(".step[tabindex]")
    assert "border-color: var(--border-hover)" in rule(".step[tabindex]:hover")
    assert rule(".step:focus-visible").strip() == rule(":focus-visible").strip()


def test_kpis_is_a_four_column_grid_that_drops_to_two_in_a_narrow_window():
    kpis = rule(".kpis")
    assert "display: grid" in kpis
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in kpis
    assert re.search(r"gap: var\(--space-\d\)", kpis)
    narrow = re.search(r"@media \(max-width: 900px\)\s*\{(.*?)\n\}", BASE, re.DOTALL)
    assert narrow, "窄窗那段 @media 不见了"
    assert re.search(r"\.kpis \{ grid-template-columns: 1fr 1fr; \}", narrow.group(1)), (
        "窄窗（< 900px）读数卡该退到两列"
    )


def test_kpis_kills_the_card_rhythm_so_grid_cells_line_up():
    """卡片套卡片（`<div class="card"><div class="kpis">…`）时 `.card > * + *`
    不该落到格子上——同分 (0,1,1)，靠写在后面取胜（同 .actions / .field）。"""
    assert re.search(r"margin-top:\s*0\s*;", rule(".kpis > * + *"))
    assert rule_pos(".kpis > * + *") > rule_pos(".card > * + *")


def test_kpi_card_has_label_value_and_sub_line():
    """`<div class="card kpi"><div class="lbl">…</div><div class="val">128<small>件</small>
    </div><div class="sub">…</div></div>`：小标签弱化、大数字等宽、副行次要色。"""
    assert re.search(r"padding: var\(--space-\d\)", rule(".kpi"))
    lbl = rule(".kpi .lbl")
    assert "color: var(--muted)" in lbl and "letter-spacing: .08em" in lbl
    val = rule(".kpi .val")
    assert "font-size: 26px" in val and "font-variant-numeric: tabular-nums" in val
    assert "color: var(--text)" in val
    assert "color: var(--muted)" in rule(".kpi .val small")
    assert "color: var(--text-dim)" in rule(".kpi .sub")


def test_kpi_inner_spacing_outranks_the_card_rhythm():
    """.val / .sub 是 .card 的直接子元素，`.card > * + *`（0,1,1）会给它们一整档
    卡片行距；`.kpi .val`（0,2,0）分数更高，读数卡自己的紧凑间距说了算。"""
    assert re.search(r"margin-top: var\(--space-\d\)", rule(".kpi .val"))
    assert re.search(r"margin-top: var\(--space-\d\)", rule(".kpi .sub"))


def test_kpi_empty_state_and_warning_state():
    """空态：卡还在、数字写破折号、副行包 .dim 弱化；警示态：数字换警示色。"""
    assert "color: var(--muted)" in rule(".kpi .sub .dim")
    assert "color: var(--warn)" in rule(".kpi.warn .val")


def test_sentence_column_in_a_grid_may_wrap():
    """数据网格默认不折行（宽表靠横滚读）；放整句话的列（说明、路径、原因）给
    单元格挂 td.wrap 就允许换行、长路径断开。`.grid td.wrap`（0,2,1）压过
    `.grid td`（0,1,1），不靠顺序。"""
    wrap = rule(".grid td.wrap")
    assert "white-space: normal" in wrap
    assert "overflow-wrap: anywhere" in wrap
    assert re.search(r"min-width: \d+em", wrap), (
        "anywhere 让最小内容宽度趋近一个字，不给下限的话这一列会被挤成一条竖线"
    )


def test_theme_toggle_shows_where_a_click_will_take_you():
    """深浅切换按钮 `<button class="icon" data-theme-toggle>` 里放 .sun 与 .moon
    两颗内联 svg：深色下显示太阳（点了去浅色）、浅色下显示月亮。显隐写在 svg 上，
    按钮本体不写 display（hidden 照常收得起来）。"""
    assert "display: none" in rule("[data-theme-toggle] .moon")
    assert "display: none" in rule(':root[data-theme="light"] [data-theme-toggle] .sun')
    assert "display: block" in rule(':root[data-theme="light"] [data-theme-toggle] .moon')
    assert not host_rules_declaring_display("[data-theme-toggle]")


CONTROLS_NOT_SELECTABLE = ("button", ".btn", ".seg", ".pill", ".chip", ".switch", "label")


def test_controls_are_not_selectable_so_clicks_never_select_text():
    """run() 默认放开文字选择（票 #27，#17）；按钮、分段、徽章、筛选片、开关、标签
    这些点的东西声明不可选，点击时不误选中文字。"""
    block = rule(", ".join(CONTROLS_NOT_SELECTABLE))
    assert "-webkit-user-select: none" in block and "user-select: none" in block


def test_base_never_forces_body_text_selectable():
    """正文可不可选由 run(text_select=…) 决定；base.css 不许替它拍板——写了
    `user-select: text` 的话，run(text_select=False) 就关不掉了。"""
    assert "user-select: text" not in CSS_COMMENT_RE.sub("", BASE)


def test_step_head_lines_up_the_number_and_the_title():
    head = rule(".step .head")
    assert "display: flex" in head and "align-items: center" in head


# ---------------------------------------------------------------------------
# 票 #29：运行日志区 .runlog——标题行 + 分组列表，两层折叠，行格式「时间 · 等级 ·
# 正文」。模版是包装排产的日志窗口与 PQPR 的底部运行日志。旧 .log 一条不改
# （上面「不换行」那条继续钉着）。
# ---------------------------------------------------------------------------


def test_runlog_list_is_a_bounded_scroller_on_the_window_colour():
    body = rule(".runlog-list")
    assert re.search(r"max-height: \d+vh", body), "定最高，不跟着日志一路长"
    assert "overflow: auto" in body
    assert "background: var(--win)" in body
    assert "border: 1px solid var(--border)" in body


def test_runlog_area_lays_out_its_title_row_and_list_with_a_token_gap():
    area = rule(".runlog")
    assert "flex-direction: column" in area
    assert re.search(r"gap: var\(--space-\d\)", area)
    # 卡片里放日志区时，卡片的竖向节奏不该再给列表加一截上边距
    assert "margin-top: 0" in rule(".runlog > * + *")


def test_runlog_text_wraps_long_lines_instead_of_scrolling_sideways():
    """日志区的正文要换行（与旧 .log 相反）：pre-wrap 保住原话里的换行与缩进，
    长路径在任意处断开。"""
    text = rule(".runlog-line .tx")
    assert re.search(r"white-space: pre-wrap\s*;", text)
    assert "overflow-wrap: anywhere" in text


def test_runlog_line_is_time_level_text_in_three_columns():
    line = rule(".runlog-line")
    assert "display: grid" in line
    assert re.search(r"grid-template-columns: [^;]*minmax\(0, 1fr\)", line), (
        "正文列吃剩余宽度且允许收缩到 0，长行才会换行而不是撑破"
    )
    times = rule(".runlog-head .tm, .runlog-line .tm")
    assert "font-family: var(--font-mono)" in times, "时间等宽，竖着对得齐"
    assert "color: var(--muted)" in times


@pytest.mark.parametrize(("level", "token"), [("warn", "warn"), ("error", "error")])
def test_runlog_level_label_uses_the_semantic_colour(level: str, token: str):
    assert f"color: var(--{token})" in rule(f".runlog-line.{level} .lv")


def test_runlog_failed_line_and_failed_run_get_the_error_tint():
    assert "background: var(--error-bg)" in rule(".runlog-line.error")
    assert "background: var(--error-bg)" in rule(".runlog-run.error")


def test_runlog_group_head_is_a_clickable_four_column_row():
    """组头一行结论：时间 · 状态 · 名称 · 结果。整行可点（开合），键盘可达。"""
    head = rule(".runlog-head")
    assert "display: grid" in head
    assert len(re.search(r"grid-template-columns: ([^;]+);", head).group(1).split()) >= 4
    assert "cursor: pointer" in head
    assert "background: var(--wash)" in rule(".runlog-head:hover")
    assert "outline: 2px solid var(--info)" in rule(".runlog-head:focus-visible")


def test_runlog_folded_group_keeps_its_result_to_one_line():
    folded = rule(".runlog-run:not(.open) > .runlog-head .rs")
    assert "white-space: nowrap" in folded
    assert "text-overflow: ellipsis" in folded


@pytest.mark.parametrize("cls", [".runlog-list", ".runlog-lines"])
def test_runlog_parts_folded_by_hidden_never_declare_display(cls: str):
    """整区折叠收的是 .runlog-list、组折叠收的是 .runlog-lines，都靠 hidden——
    作者层写了 display 就收不起来（同 .notice / .dot）。"""
    assert not host_rules_declaring_display(cls)


def test_old_log_rule_is_untouched_by_the_runlog_widget():
    """旧 .log 不改：新部件全是 runlog- 前缀的新类名，没有一条落在 .log 上。"""
    assert not [s for s in all_selectors() if "runlog" in s and re.search(r"\.log(?![\w-])", s)]


# ---------------------------------------------------------------------------
# 0.14.0：可访问性与动效 token（UI UX Pro Max 评估补的六条 + 两个新外观）
# ---------------------------------------------------------------------------

TOKENS_TEXT = tokens_css_path().read_text(encoding="utf-8")

MOTION_TOKENS = ("motion-fast", "motion-enter", "motion-stagger", "motion-loop", "ease-enter")


@pytest.mark.parametrize("name", MOTION_TOKENS + ("measure",))
def test_new_quantity_tokens_exist_and_are_whitelisted(name: str):
    assert name in TOKENS, f"tokens.css 里没有 --{name}"
    assert name in NON_HEX_TOKENS


def _css_without_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def test_base_css_never_writes_a_literal_duration():
    """时长只经 --motion-* 取用：改节奏只改 tokens.css 一处（与「不手写色值」同一个道理）。"""
    literals = re.findall(r"(?<![\w.-])\d*\.?\d+m?s\b", _css_without_comments(BASE))
    assert literals == [], f"base.css 里写了字面时长：{literals}"


def test_the_duration_scan_is_not_blind():
    assert re.findall(r"(?<![\w.-])\d*\.?\d+m?s\b", "a { transition: color 150ms; animation: x 1.1s }") == ["150ms", "1.1s"]


def test_search_box_draws_the_ring_on_the_box_not_on_the_bare_input():
    """搜索框是「图标 + 无边框输入框」拼成的一块：环画在外框上，里面的输入框不再画一圈。"""
    assert "outline: 0" in rule(".search input:focus-visible")
    ring = rule(".search:has(input:focus-visible)")
    assert "outline: 2px solid var(--info)" in ring


def test_dark_tokens_declare_the_dark_color_scheme():
    """不写的话 WebView2 按浅色画原生控件（下拉列表、日期框、复选框）。浅色那份已有。"""
    root = re.search(r"(?m)^:root\s*\{([^}]*)\}", TOKENS_TEXT)
    assert root and "color-scheme: dark" in root.group(1)


def test_wide_pane_paragraphs_keep_a_readable_measure():
    """小窗靠 --content-max 限住行长；应用式主区能拉到上千 px，说明段要自己限。提示条不限。"""
    assert "max-width: var(--measure)" in rule(":where(body.app .pane) p:not(.notice)")


INVALID_SELECTOR = (
    'input[aria-invalid="true"], textarea[aria-invalid="true"], '
    'select[aria-invalid="true"], .input[aria-invalid="true"]'
)


def test_invalid_field_is_outlined_in_error_and_wins_over_focus():
    assert "border-color: var(--error)" in rule(INVALID_SELECTOR)
    assert rule_pos(INVALID_SELECTOR) > rule_pos(
        "input:focus, textarea:focus, select:focus, .input:focus-within"
    ), "写在聚焦规则前面的话，聚焦时红框会被换回 --border-hover"


def test_field_error_text_is_small_error_coloured_and_lines_up_under_the_input():
    assert "color: var(--error)" in rule(".field-error")
    under = rule(".field > .field-error")
    assert "flex: 1 0 100%" in under
    assert "padding-left: calc(var(--field-label) + var(--space-3))" in under


BUSY = 'button[aria-busy="true"], .btn[aria-busy="true"]'
SPINNER = 'button[aria-busy="true"]:not(.icon):not(.switch)::before, .btn[aria-busy="true"]::before'


def test_busy_button_ignores_pointer_and_shows_a_token_coloured_spinner():
    assert "cursor: progress" in rule(BUSY)
    assert "pointer-events: none" in rule(BUSY)
    spin = rule(SPINNER)
    assert "border: 2px solid currentColor" in spin
    assert "animation: msui-spin var(--motion-loop) linear infinite" in spin


def test_busy_spinner_is_stopped_by_reduced_motion():
    """::before 由静止段的通配符 `*::before` 罩住——这里只证明那条通配符还在。"""
    assert "*, *::before, *::after" in reduced_motion_block()


WIDGET_PAIRS_0_14 = (
    (INVALID_SELECTOR, "error", "card"),
    (".field-error", "error", "card"),
    (".field-error", "error", "win"),
)


@pytest.mark.parametrize(("selector", "fg", "bg"), WIDGET_PAIRS_0_14)
def test_new_error_colours_are_registered_pairs(selector, fg, bg):
    assert f"var(--{fg})" in rule(selector)
    from msui.testing import BASE_TOKEN_PAIRS

    assert any(p.foreground == fg and p.background == bg for p in BASE_TOKEN_PAIRS), (fg, bg)
