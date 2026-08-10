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
