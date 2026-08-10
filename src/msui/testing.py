"""样式闸门的纯函数库：对比度校验 + 防游离色值扫描。**不依赖 pytest。**

`tokens.css` 是唯一色源、`base.css` 只经 `var(--…)` 引用——这两条约定要靠
测试盯着才立得住。本模块把「盯着」所需的全部零件做成可复用的纯函数，消费
者在自己仓里用三五行 pytest 把闸门接上：

    from msui.resources import parse_tokens, tokens_css_path
    from msui import testing as gate

    tokens = parse_tokens(tokens_css_path().read_text(encoding="utf-8"))
    override = parse_tokens(Path("static/override.css").read_text(encoding="utf-8"))
    colors = gate.hex_tokens(gate.merge_tokens(tokens, override))

    def test_readable():
        failures = gate.contrast_failures(colors, gate.BASE_TOKEN_PAIRS + MY_PAIRS)
        assert not failures, gate.format_contrast_failures(failures, colors)

    def test_no_stray_hex():
        offenders = gate.scan_stray_hex(Path("static"))
        assert not offenders, gate.format_stray_hex(offenders)

四个零件：

  1. WCAG 2.x 公式（`relative_luminance` / `contrast_ratio`）随包，消费者
     不用抄公式；
  2. `merge_tokens` 把包内 tokens 与消费者 override **合成一份字典**——
     对比度检查吃的是合成后的结果，override 改了什么、闸门就看见什么；
  3. `TokenPair` + `BASE_TOKEN_PAIRS`：基础登记表覆盖包内 `base.css` 实际
     用到的前景/背景组合；消费者用 `BASE_TOKEN_PAIRS + (自己的登记项,)`
     追加自己页面的组合；
  4. `scan_stray_hex`：扫描给定目录下的前端文件，token 允许清单之外不许
     出现手写十六进制色值——扫描目录与允许清单都是显式入参，不隐式推导。

包自己的 `tests/test_testing.py` 用这套零件对 `tokens.css` + `base.css`
把过一遍闸门（共享侧一次把关），并带全部自证测试。
"""
from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .resources import BASE_CSS_NAME, TOKENS_CSS_NAME

__all__ = [
    "ALLOWED_HEX_FILE_NAMES",
    "BASE_TOKEN_PAIRS",
    "DISABLED_MINIMUM",
    "HEX_COLOR_RE",
    "HEX_LITERAL_RE",
    "NON_HEX_TOKENS",
    "OVERRIDE_CSS_NAME",
    "SCANNED_SUFFIXES",
    "SEPARATOR_MINIMUM",
    "TEXT_MINIMUM",
    "TokenPair",
    "contrast_failures",
    "contrast_ratio",
    "format_contrast_failures",
    "format_stray_hex",
    "hex_tokens",
    "merge_tokens",
    "relative_luminance",
    "scan_stray_hex",
]

# ---------------------------------------------------------------------------
# 阈值档位（WCAG 2.x）
#
# 没有单列「控件 3.0」一档：基础登记表全是文字与分隔线，没有一条图形控件
# 登记项——挂一个没人用的常量只会让人误以为哪里用到了它。消费者的页面真
# 有图形控件（图标、开关这类）要登记时，档位数值就是 3.0，直接写数或自定
# 常量都行。
# ---------------------------------------------------------------------------

TEXT_MINIMUM = 4.5  # 正文文字
DISABLED_MINIMUM = 3.0  # 弱化文字：版本号、占位符这类「看得见就行」
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
# 它们全是 rgba() 半透明晕染：底色、边框、hover 提亮罩这类叠加层，本身不
# 承担「看得清」的职责——可读性由画在它们上面的实色前景承担，那些前景各自
# 的组合已在登记表里。每一条都应能在 tokens.css 里对应变量旁找到说明。
NON_HEX_TOKENS = frozenset(
    {
        "error-bg",  # error 系半透明底
        "error-strip-border",  # error 系半透明边框
        "error-wash",  # error 系 hover 提亮罩
        "warn-bg",  # warn 状态徽章的半透明底
        "info-bg",  # info 状态徽章的半透明底
        "ok-bg",  # ok 状态徽章的半透明底
        "brand-tint",  # brand 系渐变深端
        "brand-tint-weak",  # brand 系渐变浅端
        "brand-tint-border",  # brand 系半透明边框
        "track",  # 进度条轨道的半透明底
        "wash",  # hover 提亮罩
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
    # ---- 主按钮（4.5）：text 画在 brand 底上；hover 态换 brand-down 底 ----
    TokenPair("主按钮文字 text（brand 底）", "text", "brand", TEXT_MINIMUM),
    TokenPair("主按钮文字 text（brand-down 底）", "text", "brand-down", TEXT_MINIMUM),
    # ---- 弱化文字（3.0）：muted 是「看得见就行」档 ----
    TokenPair("弱化文字 muted（card 底）", "muted", "card", DISABLED_MINIMUM),
    TokenPair("弱化文字 muted（card-hover 底）", "muted", "card-hover", DISABLED_MINIMUM),
    TokenPair("弱化文字 muted（win 底）", "muted", "win", DISABLED_MINIMUM),
    # ---- 分隔线（1.3）：纯装饰，只要求还看得见 ----
    TokenPair("分隔线 border（card 底）", "border", "card", SEPARATOR_MINIMUM),
    TokenPair("分隔线 border（win 底）", "border", "win", SEPARATOR_MINIMUM),
    TokenPair("分隔线 border-hover（card-hover 底）", "border-hover", "card-hover", SEPARATOR_MINIMUM),
    TokenPair("分隔线 border-hover（win 底）", "border-hover", "win", SEPARATOR_MINIMUM),
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

# 默认允许含 hex 的文件名：包内两份 css 的**副本**（消费者拷进自己静态目录
# 的那两份——原件的干净由包自己的测试把关，消费者不必重复负责），加上消费
# 者自己的换色 override.css（它的本职就是用新 hex 覆写 token 值）。
ALLOWED_HEX_FILE_NAMES: tuple[str, ...] = (
    TOKENS_CSS_NAME,
    BASE_CSS_NAME,
    OVERRIDE_CSS_NAME,
)


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
