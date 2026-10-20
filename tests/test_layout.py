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
from msui.testing import NON_HEX_TOKENS

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
    """CSS 里每一条规则的每一个选择器（逗号拆开），含 @media 里嵌着的。

    先剥注释（注释里逐字写着选择器）；@keyframes 里的 from / to / 百分比
    不是选择器，整段剔掉。
    """
    body = CSS_COMMENT_RE.sub("", css)
    body = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^}]*\})*\s*\}", "", body)
    found: list[str] = []
    for head in re.findall(r"([^{};]+)\{[^{}]*\}", body):
        head = head.strip()
        if head.startswith("@"):
            continue
        found.extend(part.strip() for part in head.split(","))
    return found


def is_app_scoped(selector: str) -> bool:
    return selector.startswith(("body.app", ":where(body.app"))


def test_every_app_layout_rule_hangs_under_the_body_app_switch():
    """不挂 class="app" 的页面一条都命中不到——「小窗一个像素不变」的文本层证明。

    先自证扫描没坏（已知的 body.app 规则、@media 里嵌着的规则都扫得到），
    再逐条核对：选择器里提到应用式专属类、或 [hidden] / :focus-visible 这类
    全局改写的，必须以 body.app 开头。
    """
    selectors = all_selectors()
    assert "body.app" in selectors, "扫描没扫到 body.app——扫描本身坏了，它的绿不作数"
    assert "progress::-webkit-progress-bar" in selectors, "@media 里嵌着的规则没扫到"
    pattern = re.compile(
        r"\.(?:" + "|".join(APP_ONLY_CLASSES) + r")(?![\w-])|\[hidden\]|:focus-visible"
    )
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


def test_app_focus_ring_is_visible_and_token_coloured():
    ring = rule("body.app :focus-visible")
    assert re.search(r"outline: 2px solid var\(--info\)", ring)


# 新部件画出来的「前景 × 底」组合。每一条：规则里真用了那个前景 token（防止
# 这张表与 CSS 脱节），且这一对已在 testing.BASE_TOKEN_PAIRS 里登记——登记了
# 就意味着深色与浅色两套 token 都过同一道闸门（test_testing 跑全表）。
# 底只有 card / win 两种：部件要么摆在窗底上（顶栏、状态栏），要么摆在卡片里；
# 半透明的 --wash / --*-bg 叠在它们上面，可读性由透出来的实色底承担（与 .notice
# 同一惯例）。
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
    ("body.app :focus-visible", "info", "win"),
    ("body.app :focus-visible", "info", "card"),
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
    assert re.search(r"animation: msui-card-in \d+ms", fade)
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
