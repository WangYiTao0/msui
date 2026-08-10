"""版本号单一来源 —— 包能从自身报出版本号。

版本号只写在 pyproject.toml 一处。包内运行时通过安装元数据拿到这个号，
不读 pyproject.toml 文件本身（装到用户机器上不带这个文件），也不在包内
再抄一份字面量——两处漂移会出现"装的是 0.2.0、报的是 0.1.0"这种误导。

三条断言：
  - 包报出的版本 == pyproject.toml 里写的版本（本测试自己读 pyproject.toml
    作参照，不算包内第二份字面量）；
  - 已安装场景（测试环境 editable 装着）不抛异常；
  - 未安装场景（importlib.metadata 找不到 distribution）走明确兜底值。
"""
from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path

import msui


def _version_from_pyproject() -> str:
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_package_version_matches_pyproject():
    # 两处一旦漂移，这条必须红
    assert msui.get_version() == _version_from_pyproject()


def test_get_version_when_installed_does_not_raise():
    version = msui.get_version()
    assert version == _version_from_pyproject()


def test_get_version_falls_back_when_not_installed(monkeypatch):
    def _raise_not_found(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", _raise_not_found)

    assert msui.get_version() == "0.0.0+unknown"
