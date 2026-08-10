"""构建出的 wheel 里确实有 msui 包，且文件名带的版本号来自 pyproject.toml。

防的是打包配置写错（packages 指错路径）时 CI 照样绿、发出去的 wheel 却是
空壳——pip install 成功、import msui 才 ModuleNotFoundError。
"""
from __future__ import annotations

import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _version_from_pyproject() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_wheel_contains_msui_package(tmp_path):
    # --no-isolation：hatchling 已在 dev 环境里，省一次隔离环境搭建
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation",
         "--outdir", str(tmp_path)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )

    version = _version_from_pyproject()
    wheels = list(tmp_path.glob("msui-*.whl"))
    assert len(wheels) == 1, f"应恰好构建出一个 wheel，实际：{wheels}"

    whl = wheels[0]
    # wheel 文件名里的版本号也来自 pyproject（hatchling 保证，这里钉死防漂移）
    assert whl.name == f"msui-{version}-py3-none-any.whl"

    names = zipfile.ZipFile(whl).namelist()
    assert "msui/__init__.py" in names, f"wheel 里没有 msui 包，实际内容：{names}"
