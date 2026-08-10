"""包自带的 PyInstaller hook：下游 spec 一行资源配置都不写也能收齐包资源。

盯三件事：
1. pyproject 里登记了 `pyinstaller40` entry point（PyInstaller 靠它发现 hook 目录）；
2. `get_hook_dirs()` 返回的目录真实存在、里面有 `hook-msui.py`；
3. hook 的 `datas` 赋值**在 AST 层面**由 `collect_data_files("msui")` 与
   `copy_metadata("msui")` 两个调用组成——用 AST 而不是正则，防「匹配到的
   是注释不是代码」那类假绿（注释里怎么写都不影响本测试）。
"""
from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from msui import _pyinstaller

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_declares_pyinstaller40_entry_point():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    entry_points = data["project"]["entry-points"]
    assert entry_points["pyinstaller40"]["hook-dirs"] == (
        "msui._pyinstaller:get_hook_dirs"
    )


def test_get_hook_dirs_returns_existing_dir_with_hook():
    dirs = _pyinstaller.get_hook_dirs()
    assert len(dirs) == 1
    hook_dir = Path(dirs[0])
    assert hook_dir.is_dir()
    assert (hook_dir / "hook-msui.py").is_file()


def test_hook_datas_combines_collect_data_files_and_copy_metadata():
    hook_dir = Path(_pyinstaller.get_hook_dirs()[0])
    tree = ast.parse((hook_dir / "hook-msui.py").read_text(encoding="utf-8"))

    datas_assigns = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "datas"
            for target in node.targets
        )
    ]
    assert len(datas_assigns) == 1, "hook 里应恰好有一处 `datas = ...` 赋值"

    calls = [
        node for node in ast.walk(datas_assigns[0].value) if isinstance(node, ast.Call)
    ]
    called = {
        call.func.id if isinstance(call.func, ast.Name) else call.func.attr
        for call in calls
    }
    assert called == {"collect_data_files", "copy_metadata"}, (
        f"datas 应由 collect_data_files + copy_metadata 组成，实际调用：{called}"
    )
    for call in calls:
        args = [a.value for a in call.args if isinstance(a, ast.Constant)]
        assert args == ["msui"], f"hook 调用的目标包应是 'msui'，实际：{args}"
