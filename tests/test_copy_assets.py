"""copy_assets：把共享样式落到消费者页面目录（出路二的启动时复制）。

盯五件事：
1. 两份 css 都复制进页面目录，内容与包内原件一致；
2. **无条件覆盖**——页面目录里已有旧文件也照覆盖（改了共享包、页面必须跟走）；
3. 复制不动原件——包内那份仍在、内容不变（Python 侧资源读取继续正常）；
4. 复制失败必须响——默认（无后备）直接抛 OSError，不许吞；
5. tempdir 后备是显式开关、默认关；开了才在页面目录写不进时把整个页面
   复制到临时目录再返回那个目录。
"""
from __future__ import annotations

import inspect
import os
import shutil
import sys

import pytest

import msui.resources as resources


def _make_page_dir(tmp_path):
    page_dir = tmp_path / "pages"
    page_dir.mkdir()
    (page_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    return page_dir


def test_copy_assets_copies_both_css_into_page_dir(tmp_path):
    page_dir = _make_page_dir(tmp_path)
    served = resources.copy_assets(page_dir)

    assert served == page_dir
    for name in resources.ASSET_NAMES:
        copied = page_dir / name
        assert copied.is_file(), f"页面目录里缺 {name}"
        original = resources.asset_path(name)
        assert copied.read_text(encoding="utf-8") == original.read_text(
            encoding="utf-8"
        )


def test_copy_assets_overwrites_stale_copies_unconditionally(tmp_path):
    """页面目录里已有旧样式也必须覆盖——if-not-exists 会造成「改了共享包、
    页面还是旧样式」，这条测试钉死禁止那种写法。"""
    page_dir = _make_page_dir(tmp_path)
    stale = ":root { --brand: #000000; } /* 旧版本残留 */"
    for name in resources.ASSET_NAMES:
        (page_dir / name).write_text(stale, encoding="utf-8")

    resources.copy_assets(page_dir)

    for name in resources.ASSET_NAMES:
        text = (page_dir / name).read_text(encoding="utf-8")
        assert text != stale, f"{name} 没被覆盖，页面还端着旧样式"
        assert text == resources.asset_path(name).read_text(encoding="utf-8")


def test_copy_assets_leaves_originals_untouched(tmp_path):
    """复制不动原件——这是定案选「启动时复制」的核心理由：包内资源照常可读。"""
    originals = {
        name: resources.asset_path(name).read_text(encoding="utf-8")
        for name in resources.ASSET_NAMES
    }
    page_dir = _make_page_dir(tmp_path)

    resources.copy_assets(page_dir)

    for name in resources.ASSET_NAMES:
        original = resources.asset_path(name)
        assert original.is_file(), f"原件 {name} 不见了——复制变成了移动"
        assert original.read_text(encoding="utf-8") == originals[name]
        assert original.parent != page_dir
    # Python 侧读取继续正常：解析得到的 tokens 里品牌色还在
    tokens = resources.parse_tokens(
        resources.tokens_css_path().read_text(encoding="utf-8")
    )
    assert tokens["brand"] == "#db021d"


def test_copy_assets_raises_when_copy_fails(tmp_path, monkeypatch):
    """复制失败必须响：默认（无后备）OSError 原样冒泡，不许裸 except 吞掉。"""
    page_dir = _make_page_dir(tmp_path)

    def _boom(src, dst, **kwargs):
        raise OSError("模拟：页面目录写不进")

    monkeypatch.setattr(shutil, "copyfile", _boom)
    with pytest.raises(OSError, match="写不进"):
        resources.copy_assets(page_dir)


def test_copy_assets_raises_when_page_dir_missing(tmp_path):
    """页面目录不存在也是响的失败——不替调用方发明目录。"""
    with pytest.raises(OSError):
        resources.copy_assets(tmp_path / "no-such-dir")


def test_tempdir_fallback_is_explicit_switch_default_off():
    signature = inspect.signature(resources.copy_assets)
    parameter = signature.parameters["tempdir_fallback"]
    assert parameter.default is False
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.skipif(
    sys.platform == "win32", reason="chmod 只读目录在 Windows 上拦不住写入"
)
def test_copy_assets_tempdir_fallback_serves_temp_copy(tmp_path):
    """开关开了、页面目录写不进：整个页面复制到临时目录，返回那个目录。"""
    page_dir = _make_page_dir(tmp_path)
    os.chmod(page_dir, 0o555)  # 可读可进不可写
    try:
        served = resources.copy_assets(page_dir, tempdir_fallback=True)
    finally:
        os.chmod(page_dir, 0o755)

    assert served != page_dir
    assert (served / "index.html").is_file(), "页面文件没跟着进临时目录"
    for name in resources.ASSET_NAMES:
        assert (served / name).is_file(), f"临时目录里缺 {name}"
        assert (served / name).read_text(encoding="utf-8") == resources.asset_path(
            name
        ).read_text(encoding="utf-8")
    shutil.rmtree(served.parent, ignore_errors=True)


@pytest.mark.skipif(
    sys.platform == "win32", reason="chmod 只读目录在 Windows 上拦不住写入"
)
def test_copy_assets_fallback_off_still_raises_on_readonly_dir(tmp_path):
    """默认不后备：同样的只读目录，直接抛——后备绝不许偷偷启用。"""
    page_dir = _make_page_dir(tmp_path)
    os.chmod(page_dir, 0o555)
    try:
        with pytest.raises(OSError):
            resources.copy_assets(page_dir)
    finally:
        os.chmod(page_dir, 0o755)
