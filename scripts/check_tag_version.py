"""发布闸门：核对 tag 版本与 pyproject.toml 的 version 逐字符一致。

沿用主仓 MSToolbox build-windows.yml 的做法：CI 在**装任何依赖之前**跑这一步，
tag 打错版本号当场 fail，不浪费后面的构建与发布步骤。
只用标准库（tomllib，3.11+），裸 Python 就能跑。

用法：python scripts/check_tag_version.py v1.2.3 pyproject.toml
pre-release tag（如 v1.2.3-rc1）一样能过，只要求与 pyproject 逐字符相同。
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("用法：check_tag_version.py <tag> <pyproject.toml 路径>", file=sys.stderr)
        return 2

    tag, pyproject_path = sys.argv[1], Path(sys.argv[2])

    if not tag.startswith("v"):
        print(f"tag 必须是 v<版本号> 的形状，实际：{tag!r}", file=sys.stderr)
        return 1

    tag_version = tag[1:]
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    pyproject_version = data["project"]["version"]

    if tag_version != pyproject_version:
        print(
            f"版本不一致：tag 是 {tag_version}，pyproject.toml 是 {pyproject_version}。"
            f"改 pyproject.toml 或删 tag 重打，保持两处一致。",
            file=sys.stderr,
        )
        return 1

    print(f"版本闸门通过：tag {tag} == pyproject {pyproject_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
