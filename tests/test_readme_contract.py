"""README 是消费者契约：可抄代码块与 examples/ 一字一致，安装行钉当前版本。

五条：
1. README 里每个以 `# examples/...` 或 `<!-- examples/... -->` 标记行开头的
   代码块，标记行之后的内容 == 那个文件的全文——README 里的代码就是从
   examples 抄的，两边一旦漂移当场红；
2. 覆盖清单钉死：app.py / index.html / skeleton.html / app-layout.html /
   widgets.html / test_style_gate.py / app.spec 七份都必须被 README 引用（少引一份 = 契约不完整）；
3. 安装行与「给 AI 的转述块」里的 wheel URL 版本号 == pyproject.toml 的
   version——发新版忘了改 README 当场红，也不许残留旧版本的下载 URL；
4. 示例 app.py 的 MSUI_PINNED（钉版本官方姿势的示范常量）== pyproject 的
   version——示例演的就是「钉住当前版」，发新版忘了跟着改当场红；
5. 片段块（`<!-- examples/... 片段 -->`，票 #27；Python 写 `# examples/... 片段`，
   票 #29）：正文是那个文件里连续的几行（逐行去缩进比对），新部件的每段写法都
   必须挂这个标记。
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
    r"```[a-z]*\n(?:# (examples/[^\s]+)|<!-- (examples/[^\s]+) -->)\n(.*?)```",
    re.DOTALL,
)

# 片段块（票 #27）：第一行 `<!-- examples/... 片段 -->`，正文是那个文件里**连续的
# 一段**——逐行去掉行首缩进后比对（README 里的片段从第 0 列写起，文件里嵌在
# 缩进里；README 列表项里的块整体缩进也一样）。部件写法从完整示例里摘一段讲，摘出来的必须还是示例里那几行。
# Python 片段（票 #29）第一行写 `# examples/... 片段`。
_FRAGMENT_RE = re.compile(
    r"```[a-z]*\n[ \t]*(?:<!-- (examples/[^\s]+) 片段 -->|# (examples/[^\s]+) 片段)\n(.*?)```",
    re.DOTALL,
)

EXPECTED_QUOTED_FILES = {
    "examples/minimal/app.py",
    "examples/minimal/pages/index.html",
    "examples/minimal/pages/skeleton.html",
    "examples/minimal/pages/app-layout.html",
    "examples/minimal/pages/widgets.html",
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


def _fragments() -> list[tuple[str, str]]:
    return [(m.group(1) or m.group(2), m.group(3)) for m in _FRAGMENT_RE.finditer(README)]


def _stripped_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines()]


def _is_contiguous_excerpt(fragment: str, whole: str) -> bool:
    part, lines = _stripped_lines(fragment.strip()), _stripped_lines(whole)
    return bool(part) and any(
        lines[i : i + len(part)] == part for i in range(len(lines) - len(part) + 1)
    )


def test_excerpt_check_is_not_blind():
    """自证：连续几行认得出（缩进不同也认），跳行、改字、空片段都不认。"""
    whole = "<a>\n  <b>1</b>\n  <c>2</c>\n<d>\n"
    assert _is_contiguous_excerpt("<b>1</b>\n<c>2</c>\n", whole)
    assert not _is_contiguous_excerpt("<b>1</b>\n<d>\n", whole)
    assert not _is_contiguous_excerpt("<b>1</b>\n<c>3</c>\n", whole)
    assert not _is_contiguous_excerpt("", whole)


# 票 #27 新部件的每段写法都必须是带片段标记的块（漏标一段，它就能悄悄漂移）。
EXPECTED_FRAGMENT_MARKERS = (
    'class="eyebrow"',
    'class="step cur"',
    'class="kpis"',
    'class="wrap"',
    "data-theme-toggle",
    'src="theme.js"',
    # 票 #29 运行日志区：页面标记、脚本引用、Python 侧建缓冲 / 记行 / 取日志
    'data-runlog="get_log"',
    'src="runlog.js"',
    "RunLog(",
    "start_run(",
    "def get_log",
)


def test_new_widget_snippets_are_marked_excerpts_of_the_example():
    fragments = _fragments()
    for marker in EXPECTED_FRAGMENT_MARKERS:
        assert any(marker in body for _rel, body in fragments), (
            f"README 里含 {marker} 的写法没挂片段标记，测试管不到它"
        )
    for rel, body in fragments:
        whole = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert _is_contiguous_excerpt(body, whole), (
            f"README 里标了 {rel} 片段的这块，在文件里找不到连续的同样几行：\n{body}"
        )


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
    match = re.search(r'^MSUI_PINNED = "([^"]+)"', app, re.MULTILINE)
    assert match, "examples/minimal/app.py 里必须有模块级 MSUI_PINNED 常量"
    assert match.group(1) == _version_from_pyproject()


def test_landed_copies_are_kept_out_of_git_and_out_of_the_bundle_everywhere():
    """copy_assets 落进页面目录的每一份资产，三处都要点名（票 #23 加了第三份
    css，票 #27 加了第一份 js）。

    - 示例 `pages/.gitignore`：副本不入仓；
    - README 里给消费者抄的那段 .gitignore 块：同上，别人照着它写；
    - 示例 app.spec 的 `_is_landed_asset` 过滤：冒烟留在盘上的副本不进产物。
    清单的单一来源是 `resources.ASSET_NAMES`——往包里加资产忘了改这三处当场红。
    """
    from msui.resources import ASSET_NAMES

    expected = set(ASSET_NAMES)
    gitignore = (REPO_ROOT / "examples/minimal/pages/.gitignore").read_text(
        encoding="utf-8"
    )
    listed = {
        line.strip()
        for line in gitignore.splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert listed == expected, f"pages/.gitignore 列的是 {listed}"

    blocks = re.findall(r"```\n((?:[a-z-]+\.(?:css|js)\n)+)```", README)
    assert len(blocks) == 1, "README 里应恰好有一段纯资产文件名的 .gitignore 块"
    assert set(blocks[0].split()) == expected

    spec = (REPO_ROOT / "examples/minimal/app.spec").read_text(encoding="utf-8")
    match = re.search(r"parts\[-1\] in \(([^)]*)\)", spec)
    assert match, "app.spec 里找不到 _is_landed_asset 的文件名清单"
    assert set(re.findall(r'"([^"]+)"', match.group(1))) == expected


def test_doc_writing_example_passes_the_generator_check(tmp_path, capsys):
    """README「文档写法」里那份示例 md（票 #30）照抄就过得了生成器核查——
    写法规范给的样子自己先合规；它一旦缺了例子、漏了理由，这条当场红。"""
    from msui import docgen

    blocks = re.findall(r"```markdown\n<!-- 文档写法示例 -->\n(.*?)```", README, re.DOTALL)
    assert len(blocks) == 1, "README「文档写法」里应恰好有一段挂「文档写法示例」标记的 md"
    sample = blocks[0]
    # 规范里要求的几样，示例里都得有一份
    for piece in ("**例 1", "### 例 2", "> ", "## 请你回复", "<!-- 无需例子：", "现在", "改后"):
        assert piece in sample, f"示例 md 里缺「{piece}」"
    src = tmp_path / "docs"
    src.mkdir()
    (src / "README.md").write_text(sample, encoding="utf-8")
    assert docgen.main([str(src), str(tmp_path / "html"), "--check"]) == 0, capsys.readouterr().out
