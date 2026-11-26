"""可访问性闸门：提示条 role、图标按钮名称、回车判断输入法。整份可照抄，零件来自 msui.testing。"""
from __future__ import annotations

from pathlib import Path

from msui import testing as gate

PAGES = Path(__file__).resolve().parent.parent / "pages"


def test_a11y_gate():
    # 扫 pages/ 下自己的 .html / .js（含内联 <script>），msui 落下的资产副本不扫
    problems = gate.a11y_problems(PAGES)
    assert not problems, gate.format_a11y_problems(problems)
