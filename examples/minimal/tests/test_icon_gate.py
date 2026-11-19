"""图标闸门：exe 图标（ico 四档、spec 挂上）与工具列表图标（toml 的 icon、256×256 PNG）。

整份可照抄；缺什么，失败信息逐条写清楚。
"""
from __future__ import annotations

from pathlib import Path

from msui import testing as gate

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_icons_present_and_valid():
    problems = gate.icon_problems(REPO_ROOT)
    assert not problems, "\n".join(problems)
