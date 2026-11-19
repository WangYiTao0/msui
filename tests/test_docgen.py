"""文档生成器（msui.docgen，票 #30）：只从命令行入口和产物看行为。

全部用本文件里现写的专用测试 md（tmp_path 下），不碰任何真实项目文档。
断言看的是：退出码、输出里点名的问题、产物目录里有没有文件、产物 html 的内容。
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from msui import docgen
from msui.resources import parse_tokens

PKG = Path(docgen.__file__).resolve().parent

# 一份过得了全部核查的说明：文首概述、一节带「例 N」段落、一节带「例」三级标题、
# 一节自动豁免的「请你回复」。
GOOD = """# 示例说明

这份说明讲样例程序怎么算件数，数据取自 2026-11-18 的样例数据文件。

## 1. 怎么数件数

每行算一件。

**例 1：三行数据**

| 输入 | 结果 |
|---|---|
| 3 行 | 3 件 |

## 2. 空行怎么办

### 例 2：空行不算

| 输入 | 结果 |
|---|---|
| 2 行 + 1 空行 | 2 件 |

## 请你回复

1. 空行要不要算？推荐不算。
"""


def _write(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _run(capsys, *argv: str) -> tuple[int, str]:
    code = docgen.main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, out.out + out.err


# ---- 产物：侧栏、锚点、配色 ----


def test_generates_one_page_per_md_with_sidebar_and_anchors(tmp_path, capsys):
    src = _write(tmp_path / "docs", {"README.md": GOOD, "第二篇.md": GOOD.replace("示例说明", "第二篇说明")})
    out = tmp_path / "html"

    code, text = _run(capsys, src, out)

    assert code == 0, text
    assert sorted(p.name for p in out.iterdir()) == ["index.html", "第二篇.html"]
    page = (out / "index.html").read_text(encoding="utf-8")
    nav = re.search(r"<nav[^>]*>(.*?)</nav>", page, re.S).group(1)
    # 站内多页导航：两份文档都在，标题取各自的一级标题；当前页标出来
    assert 'href="%E7%AC%AC%E4%BA%8C%E7%AF%87.html"' in nav
    assert "第二篇说明" in nav and "示例说明" in nav
    assert 'class="cur"' in nav
    # 本页大纲：二级标题链到正文里同名锚点（GitHub 写法：小写、去标点、空格变连字符）
    assert 'href="#1-怎么数件数"' in nav
    assert 'id="1-怎么数件数"' in page
    assert 'id="例-2空行不算"' in page
    assert "<table>" in page


def test_page_inlines_both_token_sets_and_follows_system_scheme(tmp_path, capsys):
    src = _write(tmp_path / "docs", {"README.md": GOOD})
    out = tmp_path / "html"

    code, text = _run(capsys, src, out)

    assert code == 0, text
    page = (out / "index.html").read_text(encoding="utf-8")
    dark = parse_tokens((PKG / "tokens.css").read_text(encoding="utf-8"))
    light = parse_tokens((PKG / "tokens-light.css").read_text(encoding="utf-8"))
    head, _, scheme = page.partition("@media (prefers-color-scheme: light)")
    assert scheme, "没有跟随系统浅色的那段"
    assert f"--win: {dark['win']};" in head
    assert f"--text: {dark['text']};" in head
    assert f"--win: {light['win']};" in scheme
    assert f"--text: {light['text']};" in scheme
    # 样式里不写游离色值：除了 token 声明本身，颜色一律 var(--…)
    style = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
    rules = re.sub(r"--[\w-]+:\s*[^;]+;", "", style)
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", rules)


def test_links_between_docs_point_at_the_generated_pages(tmp_path, capsys):
    other = "# 另一篇\n\n## 目标节\n\n<!-- 无需例子：只是跳转目标 -->\n"
    src = _write(tmp_path / "docs", {"README.md": GOOD + "\n见[另一篇](另一篇.md#目标节)。\n",
                                     "另一篇.md": other})
    out = tmp_path / "html"

    code, text = _run(capsys, src, out)

    assert code == 0, text
    page = (out / "index.html").read_text(encoding="utf-8")
    hrefs = [docgen.unquote(h) for h in re.findall(r'href="([^"]+)"', page)]
    assert "另一篇.html#目标节" in hrefs
    assert 'id="目标节"' in (out / "另一篇.html").read_text(encoding="utf-8")


def test_details_fold_and_blockquote_render(tmp_path, capsys):
    extra = "\n> 补充：空行指整行没有内容。\n\n<details><summary>附录：原始数据</summary>\n\n| a |\n|---|\n| 1 |\n\n</details>\n"
    src = _write(tmp_path / "docs", {"README.md": GOOD + extra})
    out = tmp_path / "html"

    code, text = _run(capsys, src, out)

    assert code == 0, text
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "<blockquote>" in page
    assert "<details><summary>附录：原始数据</summary>" in page


# ---- 核查：不过就点名、退出码非零、不写产物 ----


def _assert_blocked(capsys, tmp_path, files: dict[str, str], *expected: str, extra_args=()) -> str:
    src = _write(tmp_path / "docs", files)
    out = tmp_path / "html"
    code, text = _run(capsys, src, out, *extra_args)
    assert code == 1, text
    assert not out.exists(), "核查没过却写了产物"
    for piece in expected:
        assert piece in text, f"输出里没点到「{piece}」：\n{text}"
    return text


def test_section_without_example_is_named_with_file_and_line(tmp_path, capsys):
    bad = GOOD + "\n## 3. 去重规则\n\n同一编号只算一次。\n"
    text = _assert_blocked(capsys, tmp_path, {"README.md": bad}, "「3. 去重规则」这一节没有例子")
    line = bad.splitlines().index("## 3. 去重规则") + 1
    assert re.search(rf"README\.md:{line}: ", text), text
    # 过了的节不被误点
    assert "怎么数件数" not in text and "请你回复" not in text


def test_exemption_with_reason_passes(tmp_path, capsys):
    ok = GOOD + "\n## 3. 名词\n\n<!-- 无需例子：只解释名词，没有规则 -->\n\n件：一行数据。\n"
    src = _write(tmp_path / "docs", {"README.md": ok})
    code, text = _run(capsys, src, tmp_path / "html")
    assert code == 0, text


def test_exemption_with_empty_reason_is_blocked(tmp_path, capsys):
    bad = GOOD + "\n## 3. 名词\n\n<!-- 无需例子： -->\n\n件：一行数据。\n"
    _assert_blocked(capsys, tmp_path, {"README.md": bad}, "「3. 名词」的豁免注释没写理由", "「3. 名词」这一节没有例子")


def test_auto_exempt_sections_and_preface_pass(tmp_path, capsys):
    doc = ("# 说明\n\n文首概述，没有例子也行。\n\n## 1. 规则\n\n**例 1**：有。\n\n"
           "## 附：原始字段\n\n字段表。\n\n## 5. 请你回复\n\n1. 推荐 A。\n")
    src = _write(tmp_path / "docs", {"README.md": doc})
    code, text = _run(capsys, src, tmp_path / "html")
    assert code == 0, text


def test_example_marker_inside_code_block_does_not_count(tmp_path, capsys):
    bad = GOOD + "\n## 3. 去重\n\n```text\n**例 3** 这是代码\n### 例 4\n```\n"
    _assert_blocked(capsys, tmp_path, {"README.md": bad}, "「3. 去重」这一节没有例子")


def test_employee_names_and_user_paths_are_blocked(tmp_path, capsys):
    bad = GOOD + "\n联系 Synthetic.Person，文件在 C:\\Users\\synthetic\\a.xlsx。\n"
    _assert_blocked(capsys, tmp_path, {"README.md": bad}, "疑似员工姓名或个人路径 Synthetic.Person",
                    "C:\\Users\\synthetic")


def test_names_file_entries_are_blocked(tmp_path, capsys):
    names = tmp_path / "名单.txt"
    names.write_text("# 名单\n张样例\n", encoding="utf-8")
    bad = GOOD + "\n这一版由张样例确认。\n"
    _assert_blocked(capsys, tmp_path, {"README.md": bad}, "张样例", extra_args=("--names", names))


def test_code_symbols_are_not_names(tmp_path, capsys):
    ok = GOOD + "\n用 Table.AddColumn 加列；`Synthetic.Symbol` 用 --allow 放行。\n"
    src = _write(tmp_path / "docs", {"README.md": ok})
    code, text = _run(capsys, src, tmp_path / "html", "--allow", "Synthetic.Symbol")
    assert code == 0, text


def test_broken_link_and_anchor_are_blocked(tmp_path, capsys):
    bad = GOOD + "\n[坏链](不存在.md) [坏锚](#没有这节) [好锚](#1-怎么数件数)\n"
    text = _assert_blocked(capsys, tmp_path, {"README.md": bad},
                           "本地链接指向的文件不存在 不存在.md", "锚点不存在 #没有这节")
    assert "#1-怎么数件数" not in text


def test_unclosed_details_is_blocked(tmp_path, capsys):
    _assert_blocked(capsys, tmp_path, {"README.md": GOOD + "\n<details><summary>附</summary>\n\n没关\n"},
                    "<details> 没有闭合")


def test_check_mode_writes_nothing_even_when_clean(tmp_path, capsys):
    src = _write(tmp_path / "docs", {"README.md": GOOD})
    out = tmp_path / "html"
    code, text = _run(capsys, src, out, "--check")
    assert code == 0, text
    assert not out.exists()


def test_check_mode_fails_on_problems(tmp_path, capsys):
    _assert_blocked(capsys, tmp_path, {"README.md": GOOD + "\n## 3. 漏例子\n\n规则。\n"}, "没有例子",
                    extra_args=("--check",))


def test_one_bad_page_blocks_all_pages(tmp_path, capsys):
    _assert_blocked(capsys, tmp_path, {"README.md": GOOD, "坏.md": "# 坏\n\n## 规则\n\n没例子。\n"},
                    "坏.md:3: ")


# ---- 自证 ----


def test_self_test_passes_and_reports_negatives(capsys):
    code, text = _run(capsys, "--self-test")
    assert code == 0, text
    assert "自证通过" in text


def test_self_test_fails_when_a_guard_is_blind(capsys, monkeypatch):
    """把例子核查弄瞎：自证必须红（它不是永远绿的摆设）。"""
    monkeypatch.setattr(docgen, "_check_examples", lambda md, text: [])
    code, text = _run(capsys, "--self-test")
    assert code == 1
    assert "负样本没拦住（应报「没有例子」）" in text


# ---- d2 ----

D2_DOC = GOOD + "\n## 3. 流程\n\n**例 3**：读表到出数。\n\n```d2\n读表 -> 出数\n```\n"


def test_d2_block_without_d2_installed_fails_clearly(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "空"))
    text = _assert_blocked(capsys, tmp_path, {"README.md": D2_DOC}, "本机没装 d2")
    line = D2_DOC.splitlines().index("```d2") + 1
    assert f"README.md:{line}: " in text


@pytest.mark.skipif(shutil.which("d2") is None, reason="本机没装 d2：d2 渲染只在装了 d2 的机器上测")
def test_d2_block_renders_inline_svg(tmp_path, capsys):
    src = _write(tmp_path / "docs", {"README.md": D2_DOC})
    out = tmp_path / "html"
    code, text = _run(capsys, src, out)
    assert code == 0, text
    page = (out / "index.html").read_text(encoding="utf-8")
    assert '<div class="d2"><svg' in page
    assert "language-d2" not in page


# ---- 打开文档 ----


def test_open_doc_opens_file_url_with_anchor(tmp_path, monkeypatch):
    monkeypatch.setattr(docgen.sys, "platform", "darwin")
    page = tmp_path / "index.html"
    page.write_text("<h2 id='x'>x</h2>", encoding="utf-8")
    opened: list[str] = []

    result = docgen.open_doc(page, "1-怎么数件数", opener=opened.append)

    assert result["opened"] is True
    assert opened == [result["url"]]
    assert opened[0].startswith(page.resolve().as_uri() + "#")
    assert docgen.unquote(docgen.urlsplit(opened[0]).fragment) == "1-怎么数件数"


def test_open_doc_on_windows_goes_through_a_redirect_page_keeping_the_anchor(tmp_path, monkeypatch):
    monkeypatch.setattr(docgen.sys, "platform", "win32")
    monkeypatch.setattr(docgen.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    page = tmp_path / "index.html"
    page.write_text("x", encoding="utf-8")
    opened: list[str] = []

    result = docgen.open_doc(page, "节", opener=opened.append)

    assert result["opened"] is True and "#" in result["url"]
    assert opened[0] != result["url"]
    redirect = Path(docgen.unquote(docgen.urlsplit(opened[0]).path))
    assert result["url"] in redirect.read_text(encoding="utf-8")


def test_open_doc_missing_file_does_not_open(tmp_path):
    opened: list[str] = []
    result = docgen.open_doc(tmp_path / "没有.html", "x", opener=opened.append)
    assert result["opened"] is False and opened == []
    assert "没有.html" in result["message"]


def test_without_markdown_it_the_command_says_how_to_install(tmp_path, capsys, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_markdown_it(name, *args, **kwargs):
        if name.startswith("markdown_it"):
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_markdown_it)
    src = _write(tmp_path / "docs", {"README.md": GOOD})
    code, text = _run(capsys, src, tmp_path / "html")
    assert code == 2
    assert 'pip install "msui[docs]"' in text
    assert not (tmp_path / "html").exists()
