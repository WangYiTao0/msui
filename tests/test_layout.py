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


@pytest.mark.parametrize("name", SPACE_STEPS + ("content-max",))
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
