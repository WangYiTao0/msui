"""`msui.testing`（样式闸门函数库）的自测，含全部自证测试。

`msui.testing` 本体不依赖 pytest —— 消费者在自己仓里用三五行 pytest 调它。
这里做三件事：

  1. 对包内 `tokens.css` + `base.css` 自身把一遍闸门（对比度全绿、无游离
     色值）—— 共享侧一次把关，消费者不必替包内文件负责；
  2. 验证库函数本身（WCAG 公式、合并、扫描、白名单校验）的行为；
  3. 自证：喂坏 token 必红、允许清单外的十六进制必红、白名单双向核验 ——
     一条永远不会红的检查等于没有检查。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from msui.resources import BASE_CSS_NAME, TOKENS_CSS_NAME, parse_tokens, tokens_css_path
from msui.testing import (
    ALLOWED_HEX_FILE_NAMES,
    BASE_TOKEN_PAIRS,
    DISABLED_MINIMUM,
    HEX_COLOR_RE,
    NON_HEX_TOKENS,
    SEPARATOR_MINIMUM,
    TEXT_MINIMUM,
    TokenPair,
    contrast_failures,
    contrast_ratio,
    format_contrast_failures,
    format_stray_hex,
    hex_tokens,
    merge_tokens,
    relative_luminance,
    scan_stray_hex,
)


@pytest.fixture(scope="module")
def all_tokens() -> dict[str, str]:
    return parse_tokens(tokens_css_path().read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def colors(all_tokens: dict[str, str]) -> dict[str, str]:
    return hex_tokens(all_tokens)


# ---------------------------------------------------------------------------
# WCAG 公式本身
# ---------------------------------------------------------------------------


def test_contrast_ratio_hits_the_two_ends_of_the_scale():
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("#141417", "#141417") == pytest.approx(1.0, abs=0.001)


def test_contrast_ratio_does_not_care_which_one_is_the_foreground():
    assert contrast_ratio("#f4f4f5", "#141417") == pytest.approx(
        contrast_ratio("#141417", "#f4f4f5")
    )


def test_relative_luminance_rejects_malformed_colors():
    for bad in ("#fff", "#12345", "rgba(0,0,0,.5)", ""):
        with pytest.raises(ValueError):
            relative_luminance(bad)


# ---------------------------------------------------------------------------
# merge_tokens：对比度检查吃「合成后」的字典，合并由这里代办
# ---------------------------------------------------------------------------


def test_merge_tokens_override_wins_and_new_keys_join():
    base = {"brand": "#db021d", "text": "#f4f4f5"}
    override = {"brand": "#0055aa", "extra": "#123456"}
    merged = merge_tokens(base, override)
    assert merged == {"brand": "#0055aa", "text": "#f4f4f5", "extra": "#123456"}
    # 两个入参都不被改动
    assert base["brand"] == "#db021d"
    assert "text" not in override


def test_contrast_gate_consumes_the_merged_dict(all_tokens: dict[str, str]):
    """闸门读的是合成结果：override 把 muted 改到看不见，合成后必红；不合并则绿。"""
    override = {"muted": "#1c1c20"}  # 几乎等于 --card 的 #1a1a1f
    merged_colors = hex_tokens(merge_tokens(all_tokens, override))
    failures = contrast_failures(merged_colors)
    assert failures, "override 合成进去之后闸门必须看得见它"
    assert any("弱化文字" in pair.what for pair in failures)
    # 同一份 tokens 不合并 override 时全绿——红确实是合并带来的
    assert not contrast_failures(hex_tokens(all_tokens))


# ---------------------------------------------------------------------------
# 非十六进制白名单：双向自证
# ---------------------------------------------------------------------------


def test_whitelist_members_actually_exist_and_are_non_hex(all_tokens: dict[str, str]):
    """方向一：白名单不能是摆设——每个成员真在 tokens.css 里、且真不是 hex。"""
    for name in NON_HEX_TOKENS:
        assert name in all_tokens, f"白名单里的 --{name} 在 tokens.css 里不存在了"
        assert not HEX_COLOR_RE.match(all_tokens[name]), (
            f"--{name} 现在是合法 hex 值了，应从 NON_HEX_TOKENS 移出、"
            "正常参与对比度断言"
        )


def test_every_declared_token_is_either_hex_or_explicitly_whitelisted(
    all_tokens: dict[str, str],
):
    """包内 tokens.css 不许漏出一个闸门完全不知道的怪值。"""
    for name, value in all_tokens.items():
        assert HEX_COLOR_RE.match(value) or name in NON_HEX_TOKENS, (
            f"--{name}: {value!r} 既不是 #rrggbb，也没登记进 NON_HEX_TOKENS"
        )


def test_hex_tokens_raises_on_unregistered_non_hex_value():
    """方向二：没登记的非 hex 值当场报错，不被闸门悄悄放过。"""
    with pytest.raises(ValueError, match="rogue"):
        hex_tokens({"rogue": "rgba(0, 0, 0, 0.5)"})


def test_hex_tokens_accepts_a_caller_supplied_whitelist():
    """消费者的 override 可以带自己的非 hex 变量，用显式入参登记。"""
    result = hex_tokens(
        {"rogue": "rgba(0, 0, 0, 0.5)", "text": "#f4f4f5"},
        non_hex={"rogue"} | NON_HEX_TOKENS,
    )
    assert result == {"text": "#f4f4f5"}


# ---------------------------------------------------------------------------
# 对比度闸门：包内 tokens.css + 基础登记表，全绿
# ---------------------------------------------------------------------------


def test_every_registered_pair_in_package_tokens_is_readable(colors: dict[str, str]):
    """共享侧一次把关：基础登记表对包内 tokens.css 全部达标。"""
    failures = contrast_failures(colors)
    assert not failures, format_contrast_failures(failures, colors)


def test_the_gate_really_goes_red_when_a_token_becomes_unreadable(colors: dict[str, str]):
    """自证：故意把 muted 调到几乎融进 card 底，闸门必须红。

    断言里的字面量与登记表的 `what` 文案是配套的——改登记表文案时必须同步
    改这里，否则这条自证会静默失效、失效方式恰好是绿。前置断言先确认被喂坏
    的键真的存在，token 改名时这里当场炸、而不是悄悄测了个寂寞。
    """
    assert "muted" in colors, "token 名变了？自证喂坏的键必须真实存在"
    broken = dict(colors)
    broken["muted"] = "#1c1c20"  # 几乎等于 --card 的 #1a1a1f

    failures = contrast_failures(broken)

    assert failures, "把弱化文字调到几乎看不见，闸门居然还是绿的"
    assert any(
        pair.foreground == "muted" and "弱化文字" in pair.what for pair in failures
    )


def test_failure_message_names_the_pair_in_words(colors: dict[str, str]):
    """红了报的是登记表里的人话 + 实际比值 + 档位下限，不是两串十六进制。"""
    broken = dict(colors)
    broken["muted"] = "#1c1c20"
    message = format_contrast_failures(contrast_failures(broken), broken)
    assert "弱化文字" in message
    assert str(DISABLED_MINIMUM) in message


# ---------------------------------------------------------------------------
# 登记表结构约定
# ---------------------------------------------------------------------------


def test_separator_pairs_are_held_to_the_relaxed_threshold_not_text():
    """分隔线档是有意放宽的 1.3，不是偷偷套用正文的 4.5。"""
    separator_pairs = [
        p for p in BASE_TOKEN_PAIRS if p.foreground.startswith("border")
    ]
    assert separator_pairs
    assert all(p.minimum == SEPARATOR_MINIMUM for p in separator_pairs)


def test_muted_pairs_are_held_to_three_not_the_text_minimum():
    """弱化文字档是 3.0，不是正文的 4.5——muted 系组合本来就卡在两者之间。"""
    muted_pairs = [p for p in BASE_TOKEN_PAIRS if p.foreground == "muted"]
    assert muted_pairs
    assert all(p.minimum == DISABLED_MINIMUM for p in muted_pairs)


def test_error_and_brand_each_have_their_own_registered_combo():
    """error 与 brand 是两个变量、分立登记，永不共用同一条。"""
    error_pairs = [p for p in BASE_TOKEN_PAIRS if p.foreground == "error"]
    brand_pairs = [
        p for p in BASE_TOKEN_PAIRS if p.background in ("brand", "brand-down")
    ]
    assert error_pairs, "缺少 error 前景的组合"
    assert brand_pairs, "缺少 brand 底的组合"
    assert not (set(error_pairs) & set(brand_pairs))


# ---------------------------------------------------------------------------
# 消费者追加自己页面的登记项
# ---------------------------------------------------------------------------


def test_consumers_can_append_their_own_pairs(colors: dict[str, str]):
    """基础表是元组，消费者 `BASE_TOKEN_PAIRS + (自己的登记项,)` 即可追加。

    前景既可以写 token 名，也可以写 `#` 开头的字面色值（基础表自己不用
    字面色——base.css 禁止字面色值，但消费者页面里的固定色允许这样登记）。
    """
    appended = BASE_TOKEN_PAIRS + (
        TokenPair("消费者示例·主文字（bg 底）", "text", "bg", TEXT_MINIMUM),
        TokenPair("消费者示例·字面白（brand 底）", "#ffffff", "brand", TEXT_MINIMUM),
    )
    assert not contrast_failures(colors, appended)


def test_an_appended_unreadable_pair_turns_the_gate_red(colors: dict[str, str]):
    bad = TokenPair("消费者示例·同色对同色", "card", "card", TEXT_MINIMUM)
    failures = contrast_failures(colors, BASE_TOKEN_PAIRS + (bad,))
    assert failures == [bad]


# ---------------------------------------------------------------------------
# 防游离扫描：目录与允许清单都是显式入参
# ---------------------------------------------------------------------------


def test_package_shipped_css_has_no_stray_hex():
    """共享侧一次把关：把允许清单收窄到只剩 tokens.css，连 base.css 也要受检。

    base.css 承诺色彩只经 var(--…) 引用——这条就是盯着它的那双眼睛。
    """
    package_dir = tokens_css_path().parent
    offenders = scan_stray_hex(package_dir, allowed_names=(TOKENS_CSS_NAME,))
    assert not offenders, format_stray_hex(offenders)


def test_scan_catches_hex_in_an_unlisted_file(tmp_path: Path):
    (tmp_path / "app.css").write_text("h1 { color: #fff; }", encoding="utf-8")
    offenders = scan_stray_hex(tmp_path)
    assert list(offenders) == [tmp_path / "app.css"]
    assert offenders[tmp_path / "app.css"] == ["#fff"]


def test_scan_catches_every_hex_shape(tmp_path: Path):
    """3/4/6/8 位形态都要抓到；两位的 `#12` 不是色值、不抓。"""
    (tmp_path / "page.html").write_text(
        "<i style='color:#fff'></i> #ffff #ffffff #ffffff80 第#12条", encoding="utf-8"
    )
    offenders = scan_stray_hex(tmp_path)
    assert offenders[tmp_path / "page.html"] == ["#fff", "#ffff", "#ffffff", "#ffffff80"]


def test_scan_skips_the_three_allowed_copies_by_default(tmp_path: Path):
    """允许清单 = tokens.css 副本 + base.css 副本 + override.css。

    消费者把包里两份 css 拷进自己的静态目录、再放一份改色的 override.css，
    这三份里合法地含着 hex；包内文件的干净由包自己的 CI 把关，不用消费者管。
    """
    assert set(ALLOWED_HEX_FILE_NAMES) == {TOKENS_CSS_NAME, BASE_CSS_NAME, "override.css"}
    for name in ALLOWED_HEX_FILE_NAMES:
        (tmp_path / name).write_text(":root { --brand: #0055aa; }", encoding="utf-8")
    assert scan_stray_hex(tmp_path) == {}


def test_scan_with_empty_allowlist_flags_even_a_tokens_copy(tmp_path: Path):
    """自证：允许清单是显式入参、真的在起作用——清空它，副本立刻被抓。"""
    (tmp_path / TOKENS_CSS_NAME).write_text(":root { --brand: #0055aa; }", encoding="utf-8")
    offenders = scan_stray_hex(tmp_path, allowed_names=())
    assert offenders == {tmp_path / TOKENS_CSS_NAME: ["#0055aa"]}


def test_scan_recurses_and_only_reads_frontend_suffixes(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.js").write_text("el.style.color = '#123456';", encoding="utf-8")
    (tmp_path / "notes.md").write_text("色值示例 #abcdef", encoding="utf-8")
    (tmp_path / "gen.py").write_text("COLOR = '#abcdef'", encoding="utf-8")
    offenders = scan_stray_hex(tmp_path)
    assert list(offenders) == [tmp_path / "sub" / "deep.js"]
