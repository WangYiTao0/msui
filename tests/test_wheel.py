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

    # 两份样式资产也必须进 wheel。hatchling 把包目录里的非 .py 文件一并收进
    # wheel 是实测行为、不是官方文档承诺——所以这里真构建一次、解包断言钉死，
    # 换构建后端或改打包配置时资产悄悄掉出去会当场红。
    assert "msui/tokens.css" in names, f"wheel 里没有 tokens.css，实际内容：{names}"
    assert "msui/base.css" in names, f"wheel 里没有 base.css，实际内容：{names}"
