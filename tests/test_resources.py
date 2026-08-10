"""样式资产与两态资源定位的测试。

盯三件事：
1. dev / frozen 两态定位都指对地方（frozen 优先，缺文件退回包目录）；
2. tokens.css 结构不漂（品牌色默认红 #db021d、核心变量齐全）；
3. base.css 色彩只许 var(--xxx) 引用——写死字面色值当场红。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import msui.resources as resources

PKG_DIR = Path(resources.__file__).resolve().parent


# ---------------------------------------------------------------------------
# 两态资源定位（dev / frozen）
# ---------------------------------------------------------------------------


def test_asset_paths_point_into_package_when_running_from_source():
    """源码运行：两份 css 都在 msui 包目录里，且文件真实存在。"""
    assert resources.tokens_css_path() == PKG_DIR / "tokens.css"
    assert resources.base_css_path() == PKG_DIR / "base.css"
    # 定位函数指对了但文件没提交，一样是坏的
    assert resources.tokens_css_path().is_file()
    assert resources.base_css_path().is_file()


def test_asset_paths_prefer_meipass_when_frozen(monkeypatch, tmp_path):
    """冻结产物：`sys._MEIPASS/msui/` 里的那份优先。"""
    bundle = tmp_path / "msui"
    bundle.mkdir(parents=True)
    (bundle / "tokens.css").write_text(":root {}", encoding="utf-8")
    (bundle / "base.css").write_text("body {}", encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert resources.tokens_css_path() == bundle / "tokens.css"
    assert resources.base_css_path() == bundle / "base.css"


def test_asset_paths_fall_back_to_package_when_meipass_lacks_file(monkeypatch, tmp_path):
    """_MEIPASS 存在但没收到这份文件时退回包目录，而不是指向一个不存在的路径。"""
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert resources.tokens_css_path() == PKG_DIR / "tokens.css"
    assert resources.base_css_path() == PKG_DIR / "base.css"


def test_bundle_dir_is_package_relative():
    """BUNDLE_DIR 是包相对目录 "msui"——datas 目的地与运行时查找同出这一处。"""
    assert resources.BUNDLE_DIR == "msui"


def test_asset_datas_targets_bundle_dir():
    """PyInstaller datas 条目：每个资产一条，目的地都是 BUNDLE_DIR，源文件真实存在。"""
    datas = resources.asset_datas()
    assert len(datas) == len(resources.ASSET_NAMES)
    for src, dest in datas:
        assert dest == resources.BUNDLE_DIR
        assert Path(src).is_file()
    # 逐文件列名的单一来源：两份 css 都必须登记在 ASSET_NAMES 里
    assert set(resources.ASSET_NAMES) == {"tokens.css", "base.css"}


# ---------------------------------------------------------------------------
# parse_tokens
# ---------------------------------------------------------------------------


def test_parse_tokens_reads_root_variables():
    css = ":root {\n  --brand: #db021d; /* 同行注释 */\n  --wash: rgba(255, 255, 255, 0.06);\n}"
    assert resources.parse_tokens(css) == {
        "brand": "#db021d",
        "wash": "rgba(255, 255, 255, 0.06)",
    }


def test_parse_tokens_scans_declarations_outside_root_too():
    """实现扫的是全文任何位置的 `--x: y;` 声明，不限于 `:root` 块。

    docstring 里承诺了这个口径，这条测试钉住实现与承诺一致——谁改了行为
    （比如真的只解析 :root 块）必须连着改 docstring 和这条测试。
    """
    css = ".theme-alt { --brand: #123456; }"
    assert resources.parse_tokens(css) == {"brand": "#123456"}


def test_parse_tokens_ignores_multiline_comments():
    css = "/* --fake: #000000;\n 跨行注释里的声明不算 */\n:root { --ok: #86efac; }"
    assert resources.parse_tokens(css) == {"ok": "#86efac"}


# ---------------------------------------------------------------------------
# tokens.css：结构与默认值不漂
# ---------------------------------------------------------------------------


def test_tokens_css_keeps_brand_red_default():
    """品牌色默认值是红 #db021d；核心变量必须齐全（结构不变的抽查锚点）。"""
    tokens = resources.parse_tokens(
        resources.tokens_css_path().read_text(encoding="utf-8")
    )
    assert tokens["brand"] == "#db021d"
    for name in (
        "bg", "win", "card", "card-hover",
        "border", "border-hover",
        "text", "text-dim", "muted",
        "brand-down", "warn", "info", "ok", "error",
    ):
        assert name in tokens, f"tokens.css 缺变量 --{name}"


# ---------------------------------------------------------------------------
# base.css：色彩只许 var(--xxx)
# ---------------------------------------------------------------------------

_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
# 字面色值：十六进制（#fff / #db021d / #rrggbbaa）或 rgb()/rgba()/hsl()/hsla() 函数
_LITERAL_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(")


def test_base_css_only_uses_token_variables_for_color():
    """base.css 里不许写死色值——色彩一律 var(--xxx) 引 tokens.css。

    扫描先剔掉注释（注释里解释色值不算违规），再找十六进制与 rgb/hsl 函数字面量。
    改色只能改 tokens.css 这一处，base.css 写死一个就当场红。
    """
    text = _CSS_COMMENT_RE.sub(
        "", (PKG_DIR / "base.css").read_text(encoding="utf-8")
    )
    hits = _LITERAL_COLOR_RE.findall(text)
    assert hits == [], f"base.css 出现字面色值（应改用 var(--xxx)）：{hits}"
