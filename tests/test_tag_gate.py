"""发布闸门 scripts/check_tag_version.py：tag 版本 != pyproject 版本时必须非零退出。

沿用主仓 build-windows.yml 的做法：这个闸门在 CI 装任何依赖之前跑，
tag 打错版本号当场 fail，不浪费后面的构建步骤。它只用标准库（tomllib），
所以真的可以在裸 Python 上跑。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE = REPO_ROOT / "scripts" / "check_tag_version.py"


def _run_gate(tag: str, pyproject: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE), tag, str(pyproject)],
        capture_output=True,
        text=True,
    )


def _write_pyproject(tmp_path: Path, version: str) -> Path:
    p = tmp_path / "pyproject.toml"
    p.write_text(f'[project]\nname = "msui"\nversion = "{version}"\n', encoding="utf-8")
    return p


def test_gate_passes_when_tag_matches(tmp_path):
    result = _run_gate("v1.2.3", _write_pyproject(tmp_path, "1.2.3"))
    assert result.returncode == 0, result.stderr


def test_gate_fails_when_tag_mismatches(tmp_path):
    result = _run_gate("v1.2.3", _write_pyproject(tmp_path, "1.2.4"))
    assert result.returncode != 0
    # 报错里得把两个号都说出来，看日志的人不用再去翻文件
    assert "1.2.3" in result.stderr and "1.2.4" in result.stderr


def test_gate_fails_when_tag_has_no_v_prefix(tmp_path):
    result = _run_gate("1.2.3", _write_pyproject(tmp_path, "1.2.3"))
    assert result.returncode != 0


def test_gate_passes_real_repo_pyproject():
    # 真仓的 pyproject 与「v + 它自己的版本号」必须过闸——发布日不该是第一次跑
    import tomllib

    version = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    result = _run_gate(f"v{version}", REPO_ROOT / "pyproject.toml")
    assert result.returncode == 0, result.stderr
