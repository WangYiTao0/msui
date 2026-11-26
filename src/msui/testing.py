"""消费者的测试零件：样式闸门纯函数 + 冒烟自动驾驶骨架。**不依赖 pytest。**

四块内容：样式闸门（对比度校验 + 防游离色值扫描，本文件主体）、可访问性检查
:func:`a11y_problems`（0.14.0 起，见该节注释）、图标检查
:func:`icon_problems`（0.13.0 起，见该节注释）与
:class:`SmokeDriver`（APP_SMOKE 冒烟的自动驾驶骨架，见类 docstring）。

`tokens.css` 是唯一色源、`base.css` 只经 `var(--…)` 引用——这两条约定要靠
测试盯着才立得住。本模块把「盯着」所需的全部零件做成可复用的纯函数，消费
者在自己仓里用三五行 pytest 把闸门接上：

    from msui import testing as gate

    override = Path("static/override.css").read_text(encoding="utf-8")

    @pytest.mark.parametrize("theme", gate.THEMES)   # 深色、浅色各一遍
    def test_readable(theme):
        colors = gate.theme_colors(theme, override)
        failures = gate.contrast_failures(colors, gate.BASE_TOKEN_PAIRS + MY_PAIRS)
        assert not failures, gate.format_contrast_failures(failures, colors)

    def test_no_stray_hex():
        offenders = gate.scan_stray_hex(Path("static"))
        assert not offenders, gate.format_stray_hex(offenders)

五个零件：

  1. WCAG 2.x 公式（`relative_luminance` / `contrast_ratio`）随包，消费者
     不用抄公式；
  2. `merge_tokens` 把包内 tokens 与消费者 override **合成一份字典**——
     对比度检查吃的是合成后的结果，override 改了什么、闸门就看见什么；
     `theme_colors(theme, override_css)` 按浏览器层叠把深色 / 浅色各合成
     一份，消费者自己的登记项两个主题都过；
  3. `TokenPair` + `BASE_TOKEN_PAIRS`：基础登记表覆盖包内 `base.css` 实际
     用到的前景/背景组合；消费者用 `BASE_TOKEN_PAIRS + (自己的登记项,)`
     追加自己页面的组合；
  4. `scan_stray_hex`：扫描给定目录下的前端文件，token 允许清单之外不许
     出现手写十六进制色值——扫描目录与允许清单都是显式入参，不隐式推导；
  5. `scan_base_redefinitions`：消费者自己的样式（pages/layout.css 等任意
     .css、html 内联 <style>）只许加新选择器，不许重定义 base.css 已有的。

包自己的 `tests/test_testing.py` 用这套零件对 `tokens.css` + `base.css`
把过一遍闸门（共享侧一次把关），并带全部自证测试。
"""
from __future__ import annotations

import ast
import json
import os
import re
import struct
import sys
import threading
import time
import tomllib
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .resources import (
    ASSET_NAMES,
    TOKENS_LIGHT_CSS_NAME,
    asset_path,
    base_css_path,
    parse_tokens,
    tokens_css_path,
)

__all__ = [
    "ALLOWED_HEX_FILE_NAMES",
    "BASE_TOKEN_PAIRS",
    "CONTROL_MINIMUM",
    "DISABLED_MINIMUM",
    "HEX_COLOR_RE",
    "HEX_LITERAL_RE",
    "ICON_PNG_MAX_BYTES",
    "ICON_PNG_SIZE",
    "ICO_SIZES",
    "LAYOUT_CSS_NAME",
    "NON_HEX_TOKENS",
    "OVERRIDE_CSS_NAME",
    "SCANNED_SUFFIXES",
    "SEPARATOR_MINIMUM",
    "SmokeDriver",
    "TEXT_MINIMUM",
    "THEMES",
    "TokenPair",
    "a11y_problems",
    "contrast_failures",
    "contrast_ratio",
    "format_a11y_problems",
    "format_base_redefinitions",
    "format_contrast_failures",
    "format_stray_hex",
    "hex_tokens",
    "icon_problems",
    "merge_tokens",
    "redefined_base_selectors",
    "relative_luminance",
    "scan_base_redefinitions",
    "scan_stray_hex",
    "theme_colors",
]

# ---------------------------------------------------------------------------
# 阈值档位（WCAG 2.x）
#
# 「控件 3.0」这一档真有人用：base.css 里主按钮的填充/描边（--brand 对卡片底、
# 窗底）与 <progress> 的填充（--brand 对轨道）都挂在它上面。它与
# DISABLED_MINIMUM 数值相同、含义不同：一个是「弱化文字还看得见」，一个是
# 「图形控件的形状分得出来」（WCAG 1.4.11），各自独立，谁改档位都不该顺手动到
# 另一个。
# ---------------------------------------------------------------------------

TEXT_MINIMUM = 4.5  # 正文文字
DISABLED_MINIMUM = 3.0  # 弱化文字：版本号、占位符这类「看得见就行」
CONTROL_MINIMUM = 3.0  # 图形控件：进度条填充、图标、开关这类非文字的形状
SEPARATOR_MINIMUM = 1.3  # 纯装饰分隔线：只要求还看得见


# ---------------------------------------------------------------------------
# WCAG 2.x 公式
# ---------------------------------------------------------------------------


def relative_luminance(color: str) -> float:
    """`#rrggbb` → WCAG 2.x 相对亮度（0 = 纯黑，1 = 纯白）。

    每个通道先归一化到 0–1，再按 WCAG 的分段公式做 gamma 展开
    （≤0.03928 走线性段，否则走 2.4 次幂段），最后按人眼对三色的敏感度
    加权（绿最重）。只认六位十六进制——别的形态直接报错，不猜。
    """
    value = color.lstrip("#")
    if len(value) != 6 or color.count("#") > 1 or not color.startswith("#"):
        raise ValueError(f"颜色要写成 #rrggbb 六位十六进制，收到的是 {color!r}")
    channels = []
    for index in (0, 2, 4):
        raw = int(value[index : index + 2], 16) / 255
        channels.append(raw / 12.92 if raw <= 0.03928 else ((raw + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(one: str, other: str) -> float:
    """两个颜色的对比度，1.0（同色）到 21.0（纯黑对纯白）。谁前谁后结果一样。"""
    first, second = relative_luminance(one), relative_luminance(other)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


# ---------------------------------------------------------------------------
# tokens + override 的合成
# ---------------------------------------------------------------------------


def merge_tokens(
    base: Mapping[str, str], override: Mapping[str, str]
) -> dict[str, str]:
    """把包内 tokens 与消费者 override 合成一份字典，override 同名胜出。

    对比度检查（`hex_tokens` → `contrast_failures`）吃的是这份**合成后**的
    结果——override 改了哪个变量、闸门就按改后的值算，不会拿包内默认值糊弄
    出一个假绿。override 里的新增变量（消费者页面自己的 token）也一并进来，
    好让追加的登记项能按名字引用它们。两个入参都不被改动。
    """
    return {**base, **override}


# ---------------------------------------------------------------------------
# 非十六进制 token 白名单
# ---------------------------------------------------------------------------

# 只匹配「整个值就是一个六位 hex」——对比度公式只吃这种形态。
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# tokens.css 里值不是纯 `#rrggbb` 的变量，在这里显式登记、跳过对比度断言。
# 两类：rgba() 半透明晕染（底色、边框、hover 提亮罩、模态遮罩这类叠加层，本身
# 不承担「看得清」的职责——可读性由画在它们上面的实色前景承担，那些前景各自的
# 组合已在登记表里）；以及压根不是颜色的量值 token（字号档、字体族、宽度档）。
# 每一条都应能在 tokens.css 里对应变量旁找到说明。
NON_HEX_TOKENS = frozenset(
    {
        "font-display",  # 展示型大读数的字号档——量值，不是颜色
        "font-mono",  # 日志区的等宽字体族——字体族，不是颜色
        "space-1",  # 间距体系：4px 基线的六档——量值，不是颜色
        "space-2",
        "space-3",
        "space-4",
        "space-5",
        "space-6",
        "content-max",  # 内容列宽（body 即容器的 max-width）——量值，不是颜色
        "field-label",  # 表单行的标签列宽（.field 的对齐基准）——量值，不是颜色
        "rail-width",  # 应用式版式左栏 .rail 的宽——量值，不是颜色
        "measure",  # 应用式主区说明段的行长——量值，不是颜色（0.14.0）
        "motion-fast",  # 动效节奏：即时反馈时长——量值，不是颜色（0.14.0）
        "motion-enter",  # 动效节奏：进场时长
        "motion-stagger",  # 动效节奏：进场错峰间隔
        "motion-loop",  # 动效节奏：持续动画一圈
        "ease-enter",  # 动效节奏：进场缓动曲线
        "error-bg",  # error 系半透明底
        "error-strip-border",  # error 系半透明边框
        "error-wash",  # error 系 hover 提亮罩
        "warn-bg",  # warn 状态徽章 / .notice.warn 的半透明底
        "info-bg",  # info 状态徽章 / .notice.info 的半透明底
        "ok-bg",  # ok 状态徽章 / .notice.ok 的半透明底
        "brand-tint",  # brand 系渐变深端
        "brand-tint-weak",  # brand 系渐变浅端
        "brand-tint-border",  # brand 系半透明边框
        # 注意：--track（进度条轨道）**不在**这里。它曾经是半透明提亮罩，现在
        # 是实色凹陷底，正常参与对比度断言——它与 --brand 填充直接相邻，控件档
        # 3.0 就卡在那一对上，白名单一放它进来那条闸门就形同虚设。
        "wash",  # hover 提亮罩 / 中性提示条底
        "scrim",  # 模态对话框 ::backdrop 的半透明遮罩
    }
)


def hex_tokens(
    all_tokens: Mapping[str, str], *, non_hex: Collection[str] = NON_HEX_TOKENS
) -> dict[str, str]:
    """合成后的 token 字典里，剔除白名单后剩下的纯色变量。

    白名单之外的每个值都必须是合法 `#rrggbb`——写坏的色值（漏一位、多个
    空格、rgba 忘了登记）在这里当场报错，不会被闸门悄悄放过。消费者的
    override 若带自己的非 hex 变量，用 `non_hex=` 显式登记进来。
    """
    result: dict[str, str] = {}
    for name, value in all_tokens.items():
        if name in non_hex:
            continue
        if not HEX_COLOR_RE.match(value):
            raise ValueError(
                f"变量 --{name} 的值 {value!r} 既不是合法的 #rrggbb，也不在"
                f"非十六进制白名单里——要么改成合法色值，要么显式登记进白名单"
            )
        result[name] = value
    return result


# ---------------------------------------------------------------------------
# 按主题合成：深色 / 浅色各算一份（消费者的 MY_PAIRS 两个主题都要过）
# ---------------------------------------------------------------------------

# 闸门要跑的主题。深色是默认；浅色 = tokens-light.css 的
# `:root[data-theme="light"]` 覆写，页面打开开关才生效。
THEMES: tuple[str, ...] = ("dark", "light")

_LIGHT_THEME_SELECTOR = ':root[data-theme="light"]'

_BLOCK_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _split_override(override_css: str) -> tuple[str, str]:
    """把 override 文本按规则块拆成（`:root` 层生效的块, 浅色层生效的块）。

    选择器列表里有 `:root[data-theme="light"]` 的块进第二份；有别的选择器
    （`:root` 本身）的块进第一份。两个主题都要换色时写的
    `:root, :root[data-theme="light"] { … }` 两份都进。
    """
    light_key = _normalize_selector(_LIGHT_THEME_SELECTOR)
    plain: list[str] = []
    light: list[str] = []
    for head, block in _BLOCK_RE.findall(_CSS_COMMENT_RE.sub("", override_css)):
        selectors = {_normalize_selector(part) for part in head.split(",") if part.strip()}
        if light_key in selectors:
            light.append(block)
        if selectors - {light_key}:
            plain.append(block)
    return "\n".join(plain), "\n".join(light)


def theme_colors(
    theme: str,
    override_css: str | None = None,
    *,
    non_hex: Collection[str] = NON_HEX_TOKENS,
) -> dict[str, str]:
    """某个主题下页面**实际生效**的纯色 token，直接喂给 `contrast_failures`。

    `theme` 取 `THEMES` 之一；`override_css` 是消费者 override.css 的文本（没有
    就传 None）。合成顺序照浏览器层叠来——tokens.css 的 `:root` 与
    override.css 的 `:root` 同特异性、后加载者胜；tokens-light.css 的
    `:root[data-theme="light"]` 更具体，浅色下压过 override 里只写在 `:root` 的
    同名变量（README §4 讲过的那条坑），override 里同样挂了浅色选择器的块
    再压回来：

    - dark：tokens.css → override 里挂在 `:root` 上的块；
    - light：tokens.css → override 里挂在 `:root` 上的块 → tokens-light.css →
      override 里挂在 `:root[data-theme="light"]` 上的块。

    这样浅色下闸门算的就是浅色下真正画出来的颜色：override 换了品牌色却忘了
    给浅色也写一份，红的是浅色那一遍，而不是被一个不生效的值糊成假绿。
    """
    if theme not in THEMES:
        raise ValueError(f"未知主题 {theme!r}，只认 {THEMES}")
    tokens = parse_tokens(tokens_css_path().read_text(encoding="utf-8"))
    plain_css, light_css = _split_override(override_css or "")
    merged = merge_tokens(tokens, parse_tokens(plain_css))
    if theme == "light":
        light = parse_tokens(asset_path(TOKENS_LIGHT_CSS_NAME).read_text(encoding="utf-8"))
        merged = merge_tokens(merge_tokens(merged, light), parse_tokens(light_css))
    return hex_tokens(merged, non_hex=non_hex)


# ---------------------------------------------------------------------------
# 组合登记表：base.css 实际画出的前景/背景组合
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenPair:
    """一条登记：`what` 是给人看的话——红了报的是这句，不是两串十六进制。

    `foreground` / `background` 写 token 名（不带 `--`），或以 `#` 开头的
    字面色值（基础表自己不用字面色，消费者页面的固定色允许这样登记）。
    """

    what: str
    foreground: str
    background: str
    minimum: float

    def _resolve(self, name: str, colors: Mapping[str, str]) -> str:
        return name if name.startswith("#") else colors[name]

    def ratio(self, colors: Mapping[str, str]) -> float:
        return contrast_ratio(
            self._resolve(self.foreground, colors), self._resolve(self.background, colors)
        )

    def passes(self, colors: Mapping[str, str]) -> bool:
        # 四舍五入到两位再比：避免浮点毛刺把恰好卡在边界的组合误判。
        return round(self.ratio(colors), 2) >= self.minimum


# 基础登记表：覆盖 base.css 里实际出现的组合，措辞停留在 token 层面。
# 卡片上的前景一律登记「card 底」与「card-hover 底」两条——卡随时可能正被
# 悬停，hover 瞬间也不许变得看不清。error 与 brand 是两个变量、分立登记，
# 永不共用同一条。`bg`（窗口外的舞台底）上 base.css 不画任何前景，所以基础
# 表没有它的条目——消费者在舞台底上画字时自己追加。
#
# 二级表面（模态对话框、内联提示条、日志区）为什么没有新增条目：它们画字的
# 底最终还是这几种实色。对话框的底是 --card（遮罩 --scrim 铺在它**下面**，
# 不参与对话框内的对比度）；提示条四个状态的 --*-bg 与中性档的 --wash 都是
# 半透明晕染，按上面白名单里的同一条惯例，承担「看得清」的是透出来的 card /
# win 实色底，而 error / warn / info / ok / text-dim 对这两个底的组合上面全
# 都登记着；日志区的底是 --win、字是 --text-dim，同样已在表内。
# 换句话说这三样是**复用**登记项而不是绕过闸门——真新添一种实色底（比如给
# 日志区换个自己的底色）时，就得在这里加条目。
#
# 票 #27 的步骤卡 / 读数卡 / 小标题同样全是复用：步骤卡的字画在 win（左栏）或
# card（当前态）上，编号圆圈的底是 win、边是 border-hover / brand，完成态是
# brand 块上的 on-brand 数字；**等待态改用 --muted 前景、不用 opacity**，正是为了
# 让它落在「muted × win / card」这两条已登记的弱化档上（半透明的字闸门算不出来）；
# 读数卡的警示数字是 warn × card。tests/test_layout.py 的 WIDGET_PAIRS 逐条核对
# 「规则里真用了这个前景 + 这一对在本表里」。
#
# 票 #29 的运行日志区同样全是复用、没有新组合：滚动区自己铺 --win 实色底，时间
# muted、等级 info / warn / error、正文 text、组头名称 text、状态字（已停止 text-dim）、
# 结果 text-dim / error 全画在 win 上；失败行 / 失败组的 --error-bg 与组头悬停的
# --wash 是半透明晕染，透出来的还是 win；外框 --border 挨着 card 或 win。
# 注意这是**按 .notice 惯例只算 win**，没算叠色后的实际底：审查实测浅色下 error 字
# 叠在 --error-bg 上只有 4.29（< 4.5），悬停叠 --wash 3.86；深色下 muted 时间叠色后
# 3.34 / 2.80。本票不改样式，修复另开票跟进。
BASE_TOKEN_PAIRS: tuple[TokenPair, ...] = (
    # ---- 正文（4.5）：card 底 + card-hover 底 ----
    TokenPair("主文字 text（card 底）", "text", "card", TEXT_MINIMUM),
    TokenPair("主文字 text（card-hover 底）", "text", "card-hover", TEXT_MINIMUM),
    TokenPair("次要文字 text-dim（card 底）", "text-dim", "card", TEXT_MINIMUM),
    TokenPair("次要文字 text-dim（card-hover 底）", "text-dim", "card-hover", TEXT_MINIMUM),
    TokenPair("状态色 warn 文字（card 底）", "warn", "card", TEXT_MINIMUM),
    TokenPair("状态色 warn 文字（card-hover 底）", "warn", "card-hover", TEXT_MINIMUM),
    TokenPair("状态色 info 文字（card 底）", "info", "card", TEXT_MINIMUM),
    TokenPair("状态色 info 文字（card-hover 底）", "info", "card-hover", TEXT_MINIMUM),
    TokenPair("状态色 ok 文字（card 底）", "ok", "card", TEXT_MINIMUM),
    TokenPair("状态色 ok 文字（card-hover 底）", "ok", "card-hover", TEXT_MINIMUM),
    TokenPair("状态色 error 文字（card 底）", "error", "card", TEXT_MINIMUM),
    TokenPair("状态色 error 文字（card-hover 底）", "error", "card-hover", TEXT_MINIMUM),
    # ---- 正文（4.5）：win 底 ----
    TokenPair("主文字 text（win 底）", "text", "win", TEXT_MINIMUM),
    TokenPair("次要文字 text-dim（win 底）", "text-dim", "win", TEXT_MINIMUM),
    TokenPair("状态色 warn 文字（win 底）", "warn", "win", TEXT_MINIMUM),
    TokenPair("状态色 info 文字/链接（win 底）", "info", "win", TEXT_MINIMUM),
    TokenPair("状态色 ok 文字（win 底）", "ok", "win", TEXT_MINIMUM),
    TokenPair("状态色 error 文字（win 底）", "error", "win", TEXT_MINIMUM),
    # ---- 主按钮（4.5）：on-brand 画在 brand 底上；hover 态换 brand-down 底 ----
    # 主按钮文字从前借道 --text，深色下没差别；浅色主题里 --text 变黑，于是
    # 单列 --on-brand。登记的是页面上真实存在的那一对——--text 已不画在品牌底上，
    # 所以那两条随之换成 on-brand，不并存（并存等于登记一对不存在的组合）。
    TokenPair("主按钮文字 on-brand（brand 底）", "on-brand", "brand", TEXT_MINIMUM),
    TokenPair("主按钮文字 on-brand（brand-down 底）", "on-brand", "brand-down", TEXT_MINIMUM),
    # ---- 图形控件（3.0）：brand 这块颜色四周挨着的每一种底 ----
    # 一个前景可以同时有好几条真实相邻关系，各自单独登记；判断标准是「页面上
    # 这两块颜色是不是边挨边」，不是「哪条数字最紧」。brand 有三条：
    #
    #   · 主按钮的填充与 1px 描边都是 --brand（base.css 的
    #     `button.primary { background: var(--brand); border-color: var(--brand) }`），
    #     按钮四周就是卡片底或窗底，所以 brand vs card、brand vs win 两条都在。
    #     按钮的**形状边界**靠这两条撑着，WCAG 1.4.11 要的就是它。
    #   · 进度条填充画在轨道上，所以还有 brand vs track 一条。
    #
    # 前一版这三条只留了 track：当时前两条的**描述**写错了（写成「进度条填充」，
    # 而它们实际描述的是主按钮），修的人把标签当成了内容，连颜色组合一起删掉。
    # 颜色组合本身一直是页面上真实存在的——错的是标签，不是颜色。
    # 而且删掉的恰恰是紧的那两条：track(#0b0b0d) 比 card(#1a1a1f) 更暗，
    # brand vs card 永远比 brand vs track 更紧，只留 track 等于闸门在放水
    # （实测把 --brand 调成 #c00219：card 2.69、win 2.86 双双掉档，track 还有
    # 3.06 挂着过关，全表报「无，全绿」）。
    #
    # 对照：次要按钮的边界走 --border-hover，vs card-hover / vs win 两条都登记
    # 着（见下面分隔线那一节）；主按钮不该比它少。
    TokenPair("主按钮填充/边界 brand（card 底）", "brand", "card", CONTROL_MINIMUM),
    TokenPair("主按钮填充/边界 brand（win 底）", "brand", "win", CONTROL_MINIMUM),
    # 进度条填充紧挨着的是轨道，不是轨道下面的 card / win —— 轨道挡在中间。
    # 轨道还是半透明提亮罩的那阵子，brand 对轨道只有 2.56:1，过不了控件档；
    # 现在轨道是实色凹陷底，实测 3.78:1（数字与取值理由见 tokens.css 的
    # --track 注释）。
    TokenPair("进度条填充 brand（track 底）", "brand", "track", CONTROL_MINIMUM),
    # 开关关态的滑块画在凹陷槽 --track 上：「现在是关」靠的就是这颗滑块，所以
    # 它按控件档登记。参考实现的「--on-brand 滑块 × --border-hover 轨道」浅色
    # 下只有 1.97:1，过不了这一档，于是关态改成与进度条同一套凹陷槽。
    TokenPair("开关关态滑块 text-dim（track 底）", "text-dim", "track", CONTROL_MINIMUM),
    # ---- 弱化文字（3.0）：muted 是「看得见就行」档 ----
    TokenPair("弱化文字 muted（card 底）", "muted", "card", DISABLED_MINIMUM),
    TokenPair("弱化文字 muted（card-hover 底）", "muted", "card-hover", DISABLED_MINIMUM),
    TokenPair("弱化文字 muted（win 底）", "muted", "win", DISABLED_MINIMUM),
    # ---- 分隔线（1.3）：纯装饰，只要求还看得见 ----
    TokenPair("分隔线 border（card 底）", "border", "card", SEPARATOR_MINIMUM),
    TokenPair("分隔线 border（win 底）", "border", "win", SEPARATOR_MINIMUM),
    # 进度条的描边：凹陷式轨道自己陷进底色里（对 card 只有 1.13:1，够不到这一
    # 档），「这里有一条槽」改由这圈 1px --border 画出来。它两边各挨一种颜色，
    # 所以两边都要登记：外侧对卡片那条就是上面那一条，内侧对轨道是下面这条。
    TokenPair("进度条描边 border（track 底）", "border", "track", SEPARATOR_MINIMUM),
    TokenPair("分隔线 border-hover（card-hover 底）", "border-hover", "card-hover", SEPARATOR_MINIMUM),
    TokenPair("分隔线 border-hover（win 底）", "border-hover", "win", SEPARATOR_MINIMUM),
    # 筛选片当前项、搜索框获焦、开关关态悬停：--border-hover 这圈边直接画在
    # 卡片底上（不是 card-hover），开关的那圈内侧还挨着凹陷槽 --track。
    TokenPair("分隔线 border-hover（card 底）", "border-hover", "card", SEPARATOR_MINIMUM),
    TokenPair("开关描边 border-hover（track 底）", "border-hover", "track", SEPARATOR_MINIMUM),
)


def contrast_failures(
    colors: Mapping[str, str], pairs: Iterable[TokenPair] = BASE_TOKEN_PAIRS
) -> list[TokenPair]:
    """挑出对比度不达标的组合。全达标就是空列表——测试直接断言这一点。"""
    return [pair for pair in pairs if not pair.passes(colors)]


def format_contrast_failures(
    failures: Iterable[TokenPair], colors: Mapping[str, str]
) -> str:
    """把失败清单排成人话：登记名 + 实际比值 + 档位下限，照着改 token 值即可。"""
    lines = [
        f"  {pair.what}：{pair.foreground} 画在 {pair.background} 上"
        f" 只有 {pair.ratio(colors):.2f}:1，要求 {pair.minimum}:1"
        for pair in failures
    ]
    if not lines:
        return ""
    return "配色对比度不达标：\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# 防游离扫描：允许清单之外不许手写十六进制色值
# ---------------------------------------------------------------------------

# `#fff` / `#ffff` / `#ffffff` / `#ffffff80`（带 alpha）都要抓到，所以是
# 3–8 位的宽形态；`\b` 挡住「第#12条」这类两位数字引用。
HEX_LITERAL_RE = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b")

SCANNED_SUFFIXES = (".html", ".css", ".js")

OVERRIDE_CSS_NAME = "override.css"

# 默认允许含 hex 的文件名：包内落地资产的**副本**（copy_assets 落进消费者
# 页面目录的那几份，即 ASSET_NAMES——由它派生，新增落地资产不必在这里散改；
# 原件的干净由包自己的测试把关，消费者不必重复负责），加上消费者自己的换色
# override.css（它的本职就是用新 hex 覆写 token 值）。
ALLOWED_HEX_FILE_NAMES: tuple[str, ...] = (*ASSET_NAMES, OVERRIDE_CSS_NAME)


def scan_stray_hex(
    scan_dir: Path,
    *,
    allowed_names: Collection[str] = ALLOWED_HEX_FILE_NAMES,
    suffixes: Collection[str] = SCANNED_SUFFIXES,
) -> dict[Path, list[str]]:
    """递归扫 `scan_dir` 下的前端文件，返回 `{文件路径: [游离 hex, …]}`。

    改色永远只有一处要改——token 文件（或 override）之外出现手写 hex 就算
    违规。空字典 = 干净，测试直接断言这一点。扫描目录与允许清单都由调用方
    显式给出：这里不猜「前端文件在哪」，也不隐式豁免任何路径。
    """
    offenders: dict[Path, list[str]] = {}
    for path in sorted(scan_dir.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if path.name in allowed_names:
            continue
        matches = HEX_LITERAL_RE.findall(path.read_text(encoding="utf-8"))
        if matches:
            offenders[path] = matches
    return offenders


def format_stray_hex(offenders: Mapping[Path, list[str]]) -> str:
    """把违规清单排成人话：哪个文件、写了哪些字面色值。"""
    if not offenders:
        return ""
    return "以下文件出现手写十六进制色值，应改用 token 变量：\n" + "\n".join(
        f"  {path}: {matches}" for path, matches in offenders.items()
    )


# ---------------------------------------------------------------------------
# 自己的版式（layout.css）：不许重定义 base.css 已有的选择器
#
# 契约给消费者开的口子：只有自己要的版式与专属部件写进 pages/layout.css
# （<link> 在 base.css 之后）。口子的边界是「只许加、不许改」——base.css 里
# 已有的选择器（button、.seg button、.chip.on……）在消费者文件里再写一遍，
# 就是悄悄改共享部件的长相，一家人变两家。这里按**整条选择器**比对（空白、
# 组合符两侧空格、属性值引号先归一），不按类名：`.empty .icon` 与
# `button.icon` 是两条不同的选择器，`.icon` 单写不算重定义。它是一根绊线，
# 不是证明——`.nav button` 这类带自己前缀的后代选择器照样能改到按钮，那
# 属于 code review 的事。
# ---------------------------------------------------------------------------

LAYOUT_CSS_NAME = "layout.css"

_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_KEYFRAMES_RE = re.compile(r"@keyframes[^{]*\{(?:[^{}]*\{[^}]*\})*\s*\}")
_RULE_HEAD_RE = re.compile(r"([^{};]+)\{[^{}]*\}")


def _normalize_selector(selector: str) -> str:
    selector = re.sub(r"\s*([>+~])\s*", r"\1", selector.strip())
    selector = re.sub(r"\s+", " ", selector)
    return selector.replace('"', "").replace("'", "")


def _css_selectors(css: str, *, normalize: bool = True) -> list[str]:
    """每一条规则的每一个选择器（逗号拆开），含 @media 里嵌着的。

    先剥注释（注释里常逐字写着选择器）；@keyframes 里的 from / to / 百分比
    不是选择器，整段剔掉；@ 开头的规则头（@media 本身、@font-face）不算。
    `normalize=True`（默认）把空白、组合符两侧空格、属性值引号归一，供重定义
    比对用；`False` 只去首尾空白、保留源码写法（包自己的版式测试按原文断言）。
    """
    body = _KEYFRAMES_RE.sub("", _CSS_COMMENT_RE.sub("", css))
    clean = _normalize_selector if normalize else str.strip
    found: list[str] = []
    for head in _RULE_HEAD_RE.findall(body):
        head = head.strip()
        if head.startswith("@"):
            continue
        found.extend(clean(part) for part in head.split(",") if part.strip())
    return found


def redefined_base_selectors(css: str, *, base_css: str | None = None) -> list[str]:
    """`css` 里与 base.css 已有选择器重名的那些（按出现顺序、去重）。空 = 干净。

    `base_css` 默认读包内 base.css——消费者装的是哪一版 msui，就按哪一版的
    选择器清单比对；显式传入只为自证测试。
    """
    if base_css is None:
        base_css = base_css_path().read_text(encoding="utf-8")
    taken = set(_css_selectors(base_css))
    hits: list[str] = []
    for selector in _css_selectors(css):
        if selector in taken and selector not in hits:
            hits.append(selector)
    return hits


_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)


def scan_base_redefinitions(
    scan_dir: Path,
    *,
    skipped_names: Collection[str] = ASSET_NAMES,
    base_css: str | None = None,
) -> dict[Path, list[str]]:
    """递归扫 `scan_dir`，返回 `{文件路径: [重定义了的 base.css 选择器, …]}`。

    受检的是消费者**自己的**样式：每一份 .css（layout.css 或任意名，含
    override.css——它本该只有 `:root`）与每份 .html 里的内联 `<style>` 块。
    跳过的只有 copy_assets 落下的包内副本（`skipped_names`，默认
    ASSET_NAMES）。空字典 = 干净。
    """
    offenders: dict[Path, list[str]] = {}
    for path in sorted(scan_dir.rglob("*")):
        if not path.is_file() or path.name in skipped_names:
            continue
        if path.suffix == ".css":
            css = path.read_text(encoding="utf-8")
        elif path.suffix == ".html":
            html = _HTML_COMMENT_RE.sub("", path.read_text(encoding="utf-8"))
            css = "\n".join(_STYLE_BLOCK_RE.findall(html))
        else:
            continue
        hits = redefined_base_selectors(css, base_css=base_css)
        if hits:
            offenders[path] = hits
    return offenders


def format_base_redefinitions(offenders: Mapping[Path, list[str]]) -> str:
    """把违规清单排成人话：哪个文件、重定义了哪些共享选择器、该怎么办。"""
    if not offenders:
        return ""
    return (
        "以下文件重定义了 base.css 已有的选择器（会悄悄改掉共享部件的长相）：\n"
        + "\n".join(f"  {path}: {hits}" for path, hits in offenders.items())
        + "\n换个自己的类名写；别的小程序也会要的改动，开票回 msui。"
    )


# ---------------------------------------------------------------------------
# 可访问性检查（0.14.0 起）：三根静态绊线
#
# 扫页面目录下的 .html 与 .js（含 html 里的内联 <script>），跳过 copy_assets
# 落下的 msui 资产副本（原件由包自己的测试把关）。三条规则：
#   1. 提示条 .notice 写 role——它是 JS 改字 / 取消 hidden 才出现的，不写 role
#      读屏软件不念：error 态写 role="alert"，其余写 role="status"（要打断也可
#      以写 alert）；
#   2. 图标按钮 button.icon 有可访问名称（aria-label / aria-labelledby；title
#      不算——它只在悬停时出现、读屏也不保证念），里面的 <svg> 写
#      aria-hidden="true"；
#   3. 回车处理判断输入法——中文输入法里按回车是「确认候选词」，keydown 的
#      key 照样是 "Enter"。比较 key 与 "Enter"（或 keyCode / which 与 13）的那一
#      行，往上 6 行、往下 2 行内要出现 isComposing。这是按行距的近似：守卫写在
#      很远的地方也算没写；整行是 // 注释的不算。
# 只看静态文本，认不出的写法会漏：JS 运行时才拼出来的提示条 / 按钮、
# ["Enter", " "].includes(e.key)、解构出来的 key、e.code、html 的 onkeydown 属性。
# 这些属于 code review。role / aria-hidden 的取值按浏览器的口径不分大小写。
# ---------------------------------------------------------------------------

_A11Y_SUFFIXES = (".html", ".js")
_IME_GUARD_BEFORE = 6
_IME_GUARD_AFTER = 2
_ENTER_RE = re.compile(
    r"""\.key\s*(?:===?|!==?)\s*["']Enter["']"""
    r"""|["']Enter["']\s*(?:===?|!==?)\s*[\w$.]*\.key\b"""
    r"""|\bcase\s+["']Enter["']\s*:"""
    r"""|\.(?:keyCode|which)\s*(?:===?|!==?)\s*13\b"""
)


def a11y_problems(
    pages_dir: Path | str, *, skipped_names: Collection[str] = ASSET_NAMES
) -> list[str]:
    """扫页面目录，回可访问性问题清单（``相对路径:行号: 怎么改``），空 = 全过。

    ``skipped_names`` 是不扫的文件名：默认是 msui 落下的资产副本；页面里放了
    改不了的第三方脚本时，把它的文件名加进来（``(*gate.ASSET_NAMES, "x.min.js")``）。
    接进测试::

        def test_a11y_gate():
            problems = gate.a11y_problems(PAGES)
            assert not problems, gate.format_a11y_problems(problems)
    """
    root = Path(pages_dir)
    if not root.is_dir():
        return [f"{root}: 页面目录不存在"]
    problems: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in _A11Y_SUFFIXES:
            continue
        if path.name in skipped_names:
            continue
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(f"{rel}: 不是 UTF-8 编码，读不了——另存为 UTF-8（页面文件一律 UTF-8）")
            continue
        if path.suffix == ".js":
            problems += _ime_enter_problems(text, rel)
        else:
            checker = _A11yHtmlChecker(rel)
            checker.feed(text)
            checker.close()
            problems += checker.problems
    return problems


def format_a11y_problems(problems: Iterable[str]) -> str:
    """把问题清单排成人话，一条一行。"""
    problems = list(problems)
    if not problems:
        return ""
    return "以下位置不满足 msui 的可访问性约定（README「可访问性」一节）：\n" + "\n".join(
        f"  {p}" for p in problems
    )


def _ime_enter_problems(text: str, rel: str, first_line: int = 1) -> list[str]:
    """一段 JS 文本里，比较 key 与 "Enter" 却不判断输入法的行。"""
    # 按 "\n" 切，不用 splitlines()：后者把 U+2028 这类字符也当换行，行号会偏。
    lines = text.split("\n")
    problems = []
    for i, line in enumerate(lines):
        if line.lstrip().startswith("//") or not _ENTER_RE.search(line):
            continue
        window = lines[max(0, i - _IME_GUARD_BEFORE) : i + _IME_GUARD_AFTER + 1]
        if any("isComposing" in near and not near.lstrip().startswith("//") for near in window):
            continue
        problems.append(
            f"{rel}:{first_line + i}: 回车处理没判断输入法——在同一个处理函数开头写 "
            "`if (event.isComposing || event.keyCode === 229) return;`"
            "（中文输入法按回车是确认候选词，不判断会提前提交）"
        )
    return problems


class _A11yHtmlChecker(HTMLParser):
    """逐个标签看提示条 role、图标按钮名称与 svg 隐藏；内联脚本转给回车规则。"""

    def __init__(self, rel: str) -> None:
        super().__init__(convert_charrefs=True)
        self.rel = rel
        self.problems: list[str] = []
        self._icon_button_depth = 0  # 当前在几层 button.icon 里（正常只会是 0 / 1）
        self._script_line: int | None = None
        self._script_parts: list[str] = []

    def _where(self) -> str:
        return f"{self.rel}:{self.getpos()[0]}"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check(tag, dict(attrs))
        if tag == "button" and "icon" in self._classes(dict(attrs)):
            self._icon_button_depth += 1
        elif tag == "script" and not dict(attrs).get("src"):
            self._script_line = 0  # 正文第一段到来时再取行号：开始标签可能跨行
            self._script_parts = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check(tag, dict(attrs))

    def handle_endtag(self, tag: str) -> None:
        if tag == "button" and self._icon_button_depth:
            self._icon_button_depth -= 1
        elif tag == "script" and self._script_line is not None:
            self.problems += _ime_enter_problems(
                "".join(self._script_parts), self.rel, self._script_line
            )
            self._script_line = None

    def close(self) -> None:
        super().close()
        if self._script_line is not None:  # <script> 没闭合：剩下的正文照样扫
            self.handle_endtag("script")

    def handle_data(self, data: str) -> None:
        if self._script_line is not None:
            if not self._script_parts:
                self._script_line = self.getpos()[0]
            self._script_parts.append(data)

    @staticmethod
    def _classes(attrs: Mapping[str, str | None]) -> list[str]:
        return (attrs.get("class") or "").split()

    def _check(self, tag: str, attrs: Mapping[str, str | None]) -> None:
        classes = self._classes(attrs)
        role = (attrs.get("role") or "").strip().lower()
        if "notice" in classes:
            if "error" in classes and role != "alert":
                self.problems.append(
                    f'{self._where()}: 错误提示条 .notice.error 要写 role="alert"（出现时读屏软件立刻念）'
                )
            elif "error" not in classes and role not in ("alert", "status"):
                self.problems.append(
                    f'{self._where()}: 提示条 .notice 要写 role="status"（要打断用户时写 role="alert"）'
                )
        if tag == "button" and "icon" in classes:
            named = (attrs.get("aria-label") or "").strip() or (
                attrs.get("aria-labelledby") or ""
            ).strip()
            if not named:
                self.problems.append(
                    f"{self._where()}: 图标按钮 button.icon 要写 aria-label（写明动作，如「清除」；title 不算）"
                )
        hidden = (attrs.get("aria-hidden") or "").strip().lower()
        if tag == "svg" and self._icon_button_depth and hidden != "true":
            self.problems.append(
                f'{self._where()}: 图标按钮里的 <svg> 要写 aria-hidden="true"（读屏念按钮的 aria-label，不念图形）'
            )


# ---------------------------------------------------------------------------
# 图标检查（0.13.0 起）：每个小程序仓必须有图标
#
# 两样文件由同一份生成脚本（README「图标」一节）产出，各有去处：
#   - assets/icon.ico：exe 图标（任务栏、标题栏、资源管理器），四档；PyInstaller
#     spec 的 EXE(...) 用 icon= 挂上；
#   - miniprog.toml 的 icon 指向的 PNG：宿主平台总程序的工具列表显示它，随发版
#     上传。规格（256×256、≤ 64 KB）与宿主平台接入契约一致，改规格两边一起改。
# 只读文件头和 ico 目录，不依赖 Pillow；spec 用 ast 读，不执行它。
# ---------------------------------------------------------------------------

_MINIPROG_TOML_NAME = "miniprog.toml"
ICON_PNG_SIZE = 256  # 边长（像素），正方形
ICON_PNG_MAX_BYTES = 64 * 1024
ICO_SIZES = (256, 48, 32, 16)
_DEFAULT_ICO = "assets/icon.ico"  # spec 没写 icon= 时，ico 按约定位置查

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def icon_problems(repo_root: Path | str) -> list[str]:
    """检查一个小程序仓的图标是否齐全、合规；回问题清单，空 = 全过。

    检查三处文件：``miniprog.toml`` 的 ``icon``（仓内 PNG、256×256、≤ 64 KB）、
    仓根 ``*.spec`` 的 ``EXE(...)`` 写了 ``icon=``、它指向的 ``.ico``（含
    256/48/32/16 四档）。每条问题是一句能直接照着改的话，接进测试::

        problems = gate.icon_problems(REPO_ROOT)
        assert not problems, "\\n".join(problems)
    """
    root = Path(repo_root).resolve()
    return _toml_icon_problems(root) + _spec_and_ico_problems(root)


def _toml_icon_problems(root: Path) -> list[str]:
    toml_path = root / _MINIPROG_TOML_NAME
    if not toml_path.is_file():
        return [f"{_MINIPROG_TOML_NAME} 不存在（仓根要有这份接入文件，并写 icon = \"assets/icon.png\"）"]
    try:
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        return [f"{_MINIPROG_TOML_NAME} 读不了：{exc}"]
    icon = data.get("icon")
    if not icon:
        return [f"{_MINIPROG_TOML_NAME} 没写 icon（写一行 icon = \"assets/icon.png\"，指向仓内的 256×256 PNG）"]
    if not isinstance(icon, str):
        return [f"{_MINIPROG_TOML_NAME} 的 icon 要写成字符串路径，现在是 {icon!r}"]
    png = (root / icon).resolve()
    if Path(icon).is_absolute() or not png.is_relative_to(root):
        return [f"{_MINIPROG_TOML_NAME} 的 icon = \"{icon}\" 要写仓内的相对路径（发版时从仓里取这个文件）"]
    if not png.is_file():
        return [f"{_MINIPROG_TOML_NAME} 的 icon 指向的 {icon} 不存在（跑一遍 assets/make_icon.py 生成）"]
    return [f"{icon}：{p}" for p in _png_problems(png.read_bytes())]


def _png_problems(data: bytes) -> list[str]:
    if len(data) < 24 or not data.startswith(_PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return ["不是 PNG 文件（要 256×256、带透明的 PNG）"]
    width, height = struct.unpack(">II", data[16:24])
    problems = []
    if (width, height) != (ICON_PNG_SIZE, ICON_PNG_SIZE):
        problems.append(f"尺寸是 {width}×{height}，要 {ICON_PNG_SIZE}×{ICON_PNG_SIZE}")
    if len(data) > ICON_PNG_MAX_BYTES:
        problems.append(f"{len(data) / 1024:.1f} KB，超过 {ICON_PNG_MAX_BYTES // 1024} KB 上限"
                        "（简笔符号的图标远用不到这么大，保存时开 optimize）")
    return problems


def _spec_and_ico_problems(root: Path) -> list[str]:
    specs = sorted(root.glob("*.spec"))
    problems: list[str] = []
    if not specs:
        problems.append("仓根没有 PyInstaller .spec（exe 图标要在 spec 的 EXE(...) 里用 icon= 挂上）")
    ico_paths: set[str] = set()
    for spec in specs:
        try:
            tree = ast.parse(spec.read_text(encoding="utf-8"), filename=str(spec))
        except SyntaxError as exc:
            problems.append(f"{spec.name} 读不了：{exc}")
            continue
        exes = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", None)) == "EXE"]
        if not exes:
            problems.append(f"{spec.name} 里没找到 EXE(...)")
            continue
        for exe in exes:
            icon = next((kw.value for kw in exe.keywords if kw.arg == "icon"), None)
            if icon is None or (isinstance(icon, ast.Constant) and icon.value is None):
                problems.append(f"{spec.name} 的 EXE(...) 没写 icon=（加一行 "
                                'icon=os.path.join(SPECPATH, "assets", "icon.ico")）')
                continue
            rel = _spec_icon_path(icon, tree)
            if rel is None:
                problems.append(f"{spec.name} 的 icon= 读不出指向哪个文件（照约定写 "
                                'icon=os.path.join(SPECPATH, "assets", "icon.ico")）')
                continue
            if Path(rel).is_absolute() or ":" in rel or not (root / rel).resolve().is_relative_to(root):
                problems.append(f"{spec.name} 的 icon= 要指向仓内的 ico（写成 "
                                f'os.path.join(SPECPATH, "assets", "icon.ico")），现在是 {rel}')
                continue
            ico_paths.add(rel)
    # spec 没写 icon= 时 ico 照样要在约定位置、四档齐全——两件事分开报。
    for rel in sorted(ico_paths or {_DEFAULT_ICO}):
        ico = root / rel
        if not ico.is_file():
            problems.append(f"exe 图标 {rel} 不存在（跑一遍 assets/make_icon.py 生成）")
        else:
            problems.extend(f"{rel}：{p}" for p in _ico_problems(ico.read_bytes()))
    return problems


def _spec_icon_path(icon: ast.expr, tree: ast.Module) -> str | None:
    """读 spec 里 icon= 指向的仓内相对路径；读不出回 None。

    只认约定写法：字符串常量依次拼成路径——``os.path.join(SPECPATH, "assets",
    "icon.ico")``、``"assets/icon.ico"``（反斜杠也认）、``f"{SPECPATH}/assets/icon.ico"``；
    ``icon=ICON`` 这种变量追到 spec 顶层对它的唯一一次赋值。表达式不是单个字面量时
    （开头是 SPECPATH 这类），去掉拼出来的前导 ``/``——它本来接在仓根后面。
    """
    if isinstance(icon, ast.Name):
        assigned = [node.value for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(tg, ast.Name) and tg.id == icon.id for tg in node.targets)]
        if len(assigned) != 1:
            return None
        icon = assigned[0]
    parts = [n.value for n in ast.walk(icon) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    if not parts:
        return None
    rel = re.sub(r"/+", "/", "/".join(parts).replace("\\", "/"))
    return rel if isinstance(icon, ast.Constant) else rel.lstrip("/")


def _ico_problems(data: bytes) -> list[str]:
    if len(data) < 6 or struct.unpack("<HH", data[:4]) != (0, 1):
        return ["不是 ico 文件"]
    (count,) = struct.unpack("<H", data[4:6])
    sizes = set()
    for i in range(count):
        entry = data[6 + 16 * i: 6 + 16 * (i + 1)]
        if len(entry) < 16:
            return ["ico 目录不完整（文件被截断了）"]
        width, height = entry[0] or 256, entry[1] or 256
        if width == height:
            sizes.add(width)
    missing = [s for s in ICO_SIZES if s not in sizes]
    if missing:
        return [f"缺 {'、'.join(map(str, missing))} 档（要 {'/'.join(map(str, ICO_SIZES))} 四档）"]
    return []


# ---------------------------------------------------------------------------
# 冒烟自动驾驶骨架
# ---------------------------------------------------------------------------


class SmokeDriver:
    """APP_SMOKE 冒烟的自动驾驶骨架：当 ``on_ready`` 钩子递给 ``run``。

    第一个真实消费者踩出来的三条纪律，骨架各自代办、消费者不用重新发明：

    - ``on_ready`` 跑在 pywebview 的**后台线程**，里面抛异常不会变成进程的
      非零退出码——所以失败一律收集进 :attr:`failures`，``run()`` 返回后在
      主线程调 :meth:`exit` 统一判定退出码；
    - 桥往返是异步的，断言前用 :meth:`wait_js` 轮询等到位，不 sleep 一个
      拍脑袋的秒数；
    - 窗口销毁在 ``finally`` 里，冒烟脚本怎么炸都会销毁——不销毁的话
      ``run()`` 永不返回，进程挂死连失败都报不出来。

    超时兜底两层：``timeout`` 是 :meth:`wait_js` 的轮询预算（秒，整个脚本
    共用一个截止时刻，从 ``on_ready`` 触发起算）；``watchdog`` 是硬闹钟——
    构造时启动、:meth:`exit` 解除，到点直接 ``os._exit(2)``，防 GUI 主循环
    挂死时连退出码都没有（daemon 定时器，不阻塞正常退出）。

    用法（完整可跑的样子见 examples/minimal/app.py 的 APP_SMOKE 分支）::

        driver = SmokeDriver(smoke_script) if smoke else None
        run(page, hidden=driver is not None, on_ready=driver)
        if driver is not None:
            driver.exit()   # 有失败：逐条打印后 sys.exit(1)；全绿：打印「冒烟通过」

    ``script(driver, window)`` 是消费者自己的冒烟脚本，用 :meth:`wait_js` /
    :meth:`check` / :meth:`check_token_style` 驱动页面断言。
    """

    def __init__(
        self,
        script: Callable[["SmokeDriver", Any], None],
        *,
        timeout: float = 15.0,
        watchdog: float = 120.0,
    ) -> None:
        self._script = script
        self._timeout = timeout
        self._deadline: float | None = None
        self._ran = False
        self.failures: list[str] = []
        self._watchdog = threading.Timer(watchdog, self._abort)
        self._watchdog.daemon = True
        self._watchdog.start()

    @staticmethod
    def _abort() -> None:
        # 走到这儿说明主循环或 destroy 挂死了：正常退出路径已不可用，
        # os._exit 是唯一还能把非零退出码带出去的口。
        print("冒烟失败：watchdog 超时，进程疑似挂死", flush=True)
        os._exit(2)

    def __call__(self, window: Any) -> None:
        """``on_ready`` 钩子本体（pywebview 后台线程）：跑脚本，finally 销毁窗口。"""
        self._ran = True  # exit() 据此分辨「跑了全绿」与「压根没跑」
        self._deadline = time.monotonic() + self._timeout
        try:
            self._script(self, window)
        except Exception as exc:  # 后台线程的异常不自带退出码，收集是唯一出路
            self.fail(f"冒烟脚本异常：{exc!r}")
        finally:
            window.destroy()

    def fail(self, message: str) -> None:
        """记一条失败。不抛、不打断脚本——能查多少条查多少条。"""
        self.failures.append(message)

    def check(self, ok: bool, message: str) -> bool:
        """ok 为假时记失败；返回 ok 本身，方便脚本里串条件。"""
        if not ok:
            self.fail(message)
        return ok

    @staticmethod
    def _evaluate(window: Any, script: str) -> str:
        """``evaluate_js`` 一拍：页面探针抛 JavascriptException 时把异常文本
        当结果值返回，别的异常照旧穿透。

        按**异常类名字符串**识别而不 ``import webview``：msui.testing 承诺
        不依赖 pywebview 也能用于纯逻辑测试（本文件顶层没有 webview 依赖，
        这里也不能引入——哪怕延迟 import，没装 pywebview 的环境一异常就
        ImportError，反而把归因砸了）。pywebview 的 JavascriptException
        直接继承 Exception、类名稳定，名字就是充分判据。
        """
        try:
            return window.evaluate_js(script)
        except Exception as exc:
            if type(exc).__name__ != "JavascriptException":
                raise
            return f"JavascriptException: {exc}"

    def wait_js(
        self, window: Any, script: str, expected: str, *, interval: float = 0.2
    ) -> str:
        """轮询 ``evaluate_js`` 直到结果 == expected 或超时；返回最后一次结果。

        截止时刻整个冒烟脚本共用一个（``on_ready`` 触发时定下）——前一步
        等掉的时间不会给后一步续命。反过来说，**注定等不到的期望会烧满
        剩余预算才放行**（失败路径变慢是设计使然：共享截止时刻不为失败
        开小灶）。判定交还调用方：拿返回值自己 check，错的时候失败信息里
        才有「实际是什么」。

        页面探针表达式抛异常（典型：``querySelector`` 返回 null 被直接
        ``getComputedStyle``）时，pywebview 重抛 JavascriptException——这里
        把异常文本当结果值继续轮询（元素晚些出现照样等得到），超时后返回
        它，让调用方的 check 正常报「实测=<异常文本>」：单条归因、不中断
        整场、不丢剩余断言。
        """
        if self._deadline is None:  # 脚本外直接调用（罕见）：就地起一个预算
            self._deadline = time.monotonic() + self._timeout
        result = self._evaluate(window, script)
        while result != expected and time.monotonic() < self._deadline:
            time.sleep(interval)
            result = self._evaluate(window, script)
        return result

    def check_token_style(
        self, window: Any, selector: str, css_property: str, token: str
    ) -> bool:
        """断言「页面真的吃进了共享样式」：selector 命中元素的实测
        ``computedStyle[css_property]`` == token 解出的 rgb。

        版本横幅只证明 css 落了地；这一条证明页面把它**吃进去了**——探针
        元素把 ``var(--token)`` 的值解成 rgb（浏览器代为归一化，两边同一
        口径），与元素实测值比对。砍掉 base.css 的 ``<link>`` 时必红
        （第一个消费者用 mutation 验证过的配方）。

        在页面就绪断言（如 :meth:`wait_js` 等桥往返）之后调用——样式检查
        本身不轮询。
        """
        js = (
            "(() => {\n"
            f"  const el = document.querySelector({json.dumps(selector)});\n"
            "  if (!el) return '|missing';\n"
            "  const value = getComputedStyle(document.documentElement)\n"
            f"    .getPropertyValue({json.dumps('--' + token)}).trim();\n"
            "  const probe = document.createElement('div');\n"
            "  probe.style.color = value || 'transparent';\n"
            "  document.body.appendChild(probe);\n"
            "  const expected = getComputedStyle(probe).color;\n"
            "  probe.remove();\n"
            f"  return getComputedStyle(el)[{json.dumps(css_property)}] + '|' + expected;\n"
            "})()"
        )
        outcome = window.evaluate_js(js)
        actual, _, expected = (outcome or "|").partition("|")
        if expected == "missing":
            return self.check(False, f"元素 {selector} 不存在，样式断言没做成")
        return self.check(
            bool(expected) and actual == expected,
            f"{selector} 的 {css_property} 实测 {actual!r}"
            f" != --{token} 解出的 {expected!r}",
        )

    def exit(self) -> None:
        """``run()`` 返回后在主线程调用：解除 watchdog，统一判定退出码。

        有失败：逐条打印后 ``sys.exit(1)``；全绿：打印「冒烟通过」正常返回。
        print 一律 flush——冻结产物 stdout 重定向到 CI 日志时是块缓冲，
        不 flush 顺序会乱。

        「脚本压根没跑过」单独判一条：它与「跑了全绿」在 failures 上是同一个
        形状（空清单），不分开就等于任何让 ``run()`` 提前返回的路径都会静静
        报「冒烟通过」——单实例守卫拦下第二实例（票 12）、开窗直接失败，都是
        这样的路径。核实动作自己失败时必须看得出来。
        """
        self._watchdog.cancel()
        if not self._ran:
            self.fail("冒烟脚本从未跑过（on_ready 没被触发：窗口没开起来？被守卫拦下了？）")
        if self.failures:
            for line in self.failures:
                print(f"冒烟失败：{line}", flush=True)
            sys.exit(1)
        print("冒烟通过", flush=True)
