"""README 是消费者契约：可抄代码块与 examples/ 一字一致，安装行钉当前版本。

四条：
1. README 里每个以 `# examples/...` 或 `<!-- examples/... -->` 标记行开头的
   代码块，标记行之后的内容 == 那个文件的全文——README 里的代码就是从
   examples 抄的，两边一旦漂移当场红；
2. 覆盖清单钉死：app.py / index.html / skeleton.html / test_style_gate.py /
   app.spec 五份都必须被 README 引用（少引一份 = 契约不完整）；
3. 安装行与「给 AI 的转述块」里的 wheel URL 版本号 == pyproject.toml 的
   version——发新版忘了改 README 当场红，也不许残留旧版本的下载 URL；
4. 示例 app.py 的 MSUI_PINNED（钉版本官方姿势的示范常量）== pyproject 的
   version——示例演的就是「钉住当前版」，发新版忘了跟着改当场红。
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

# 代码块的第一行是文件标记：`# examples/...`（py/spec）或
# `<!-- examples/... -->`（html）；标记行之后到闭合围栏为止是被抄的正文。
_BLOCK_RE = re.compile(
    r"```[a-z]*\n(?:# (examples/[^\n]+)|<!-- (examples/[^\n]+) -->)\n(.*?)```",
    re.DOTALL,
)

EXPECTED_QUOTED_FILES = {
    "examples/minimal/app.py",
    "examples/minimal/pages/index.html",
    "examples/minimal/pages/skeleton.html",
    "examples/minimal/tests/test_style_gate.py",
    "examples/minimal/app.spec",
}


def _quoted_blocks() -> dict[str, str]:
    blocks: dict[str, str] = {}
    for match in _BLOCK_RE.finditer(README):
        rel = match.group(1) or match.group(2)
        blocks[rel] = match.group(3)
    return blocks


def test_readme_quotes_all_example_files():
    assert set(_quoted_blocks()) == EXPECTED_QUOTED_FILES


def test_readme_blocks_match_example_files_verbatim():
    for rel, block in _quoted_blocks().items():
        actual = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert block == actual, f"README 里的 {rel} 代码块与文件本体不一致"


def _version_from_pyproject() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_readme_install_url_pins_current_version():
    version = _version_from_pyproject()
    url = (
        "msui @ https://github.com/WangYiTao0/msui/releases/download/"
        f"v{version}/msui-{version}-py3-none-any.whl"
    )
    assert README.count(url) >= 2, (
        "README 的安装行与「给 AI 的转述块」都要钉当前版本的 wheel URL"
    )
    # 不许残留旧版本的下载 URL
    stale = set(re.findall(r"releases/download/v(\d+\.\d+\.\d+)", README))
    assert stale == {version}, f"README 里残留了别的版本的下载 URL：{stale}"


def test_example_msui_pinned_matches_current_version():
    """示例 app.py 演的钉版本常量必须钉当前版——README 块一字一致地跟着它。"""
    app = (REPO_ROOT / "examples/minimal/app.py").read_text(encoding="utf-8")
    match = re.search(r'^MSUI_PINNED = "([^"]+)"$', app, re.MULTILINE)
    assert match, "examples/minimal/app.py 里必须有模块级 MSUI_PINNED 常量"
    assert match.group(1) == _version_from_pyproject()
