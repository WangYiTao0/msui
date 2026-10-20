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
