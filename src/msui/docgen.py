"""文档生成器：把一个目录下的 md 生成成和程序同一家配色的单页 html（0.12.0 起）。

用法（小程序仓根下；生成器是可选依赖组，只在生成文档时装）::

    pip install "msui[docs]"
    msui-docs docs pages/docs            # 生成
    msui-docs docs pages/docs --check    # 只核查，不写文件
    msui-docs --self-test               # 自证：各道核查对正负样本都判对

``msui-docs`` 与 ``python -m msui.docgen`` 等价。

产物：源目录里每份 ``*.md``（不进子目录）一页 html；``README.md`` / ``index.md`` 出成
``index.html``，其余同名。左侧目录 = 站内多页导航 + 本页大纲（二、三级标题）；配色内嵌
msui 深浅两套 token 值、跟随系统 ``prefers-color-scheme``（文档在系统浏览器里打开，读不到
程序的主题偏好）。支持表格、引用块、``<details>`` 折叠、标题锚点（GitHub 写法），流程图写成
```` ```d2 ```` 代码块、生成时调本机 ``d2`` 出静态 SVG 嵌进页面。

**核查任一项不过就一份产物都不写、退出码 1**，逐条列出文件和行号：

- 姓名：``名.姓`` 形态的英文姓名、``C:\\Users\\<人名>`` 路径（宿主平台接入契约：产物不含员工
  姓名和个人路径），以及 ``--names`` 名单文件里的每个名字；
- 本地链接指向的文件存在，带 ``#锚`` 的锚点存在；``<details>`` 成对、id 不重复；
- 例子：每个二级节至少有一个「例」——``### 例 N…`` / ``### 例：…`` 三级标题（「例外」「例如」
  不算），或以 ``**例 N`` 开头的段落。
  确实不需要例子的节写一行 ``<!-- 无需例子：理由 -->``，理由不能空。「请你回复」「附」开头
  的节和第一个二级标题之前的文首概述自动豁免。
- 有 d2 流程图而本机没装 d2。

页面里「打开说明文档」用 :func:`open_doc`：系统浏览器打开某份产物并跳到指定锚点。它不依赖
markdown-it-py，程序运行时可以直接用。
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import webbrowser
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote, unquote, urlsplit, urlunsplit

__all__ = [
    "EXEMPT_LABEL",
    "MissingDependency",
    "Page",
    "build",
    "check",
    "find_pages",
    "github_slug",
    "main",
    "open_doc",
    "self_test",
]

PKG_DIR = Path(__file__).resolve().parent

# 豁免注释：<!-- 无需例子：理由 -->（中英文冒号都认）。
EXEMPT_LABEL = "无需例子"
_EXEMPT_RE = re.compile(r"<!--\s*" + EXEMPT_LABEL + r"\s*[：:](.*?)-->", re.S)
# 自动豁免的二级节：标题去掉前面的编号后以这些字开头。
_AUTO_EXEMPT_PREFIXES = ("请你回复", "附")
_NUMBER_PREFIX_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*[.、．]?|第\s*[\d一二三四五六七八九十百]+\s*[节章部分])\s*[：:、]?\s*")
_EXAMPLE_PARA_RE = re.compile(r"^\*\*例\s*\d+")
# 三级标题「例 3：…」「例：…」算例子；「例外情况」「例如…」不算。
_EXAMPLE_H3_RE = re.compile(r"^例\s*(?:\d|[：:])")

_INSTALL_HINT = '文档生成器要 markdown-it-py：pip install "msui[docs]"'
_D2_HINT = "本机没装 d2，流程图出不了（装法见 https://d2lang.com ；macOS：brew install d2）"


class MissingDependency(RuntimeError):
    """没装可选依赖组 docs。"""


@dataclass(frozen=True)
class Page:
    """一份源 md 与它的产物。"""

    src: Path
    out_name: str
    title: str


# ---------------------------------------------------------------- markdown


def _markdown():
    try:
        from markdown_it import MarkdownIt
    except ModuleNotFoundError as exc:
        raise MissingDependency(_INSTALL_HINT) from exc
    return MarkdownIt("commonmark", {"html": True}).enable("table").enable("strikethrough")


def _plain(inline_html: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", inline_html)).strip()


def github_slug(text: str) -> str:
    """GitHub 的标题锚点写法：小写、去掉字母数字下划线连字符空格以外的字符、空格变连字符。"""
    plain = _plain(text).lower()
    plain = re.sub(r"[^\w\- ]", "", plain)
    return plain.replace(" ", "-")


def _render(md, text: str) -> tuple[str, list[tuple[int, str, str]]]:
    """md → html，给标题加 GitHub 写法的 id（重名按 GitHub 规则补 -1、-2）；回 (html, 大纲)。"""
    body = md.render(text)
    used = set(_HtmlInfo(body).ids)
    outline: list[tuple[int, str, str]] = []

    def add_id(m: re.Match) -> str:
        level, inner = int(m.group(1)), m.group(2)
        base = github_slug(inner) or "section"
        anchor, n = base, 0
        while anchor in used:
            n += 1
            anchor = f"{base}-{n}"
        used.add(anchor)
        if level in (2, 3):
            outline.append((level, anchor, _plain(inner)))
        return f'<h{level} id="{html.escape(anchor, quote=True)}">{inner}</h{level}>'

    return re.sub(r"<h([1-6])>(.*?)</h\1>", add_id, body, flags=re.S), outline


class _HtmlInfo(HTMLParser):
    """从渲染后的 html 收 id、链接和 details 配对——代码块里的示例不会被当成链接。"""

    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.duplicate_ids: set[str] = set()
        self.links: list[str] = []
        self.problems: list[str] = []
        self._details = 0
        self.feed(text)
        self.close()
        if self._details:
            self.problems.append("<details> 没有闭合")

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if ident := attr.get("id"):
            if ident in self.ids:
                self.duplicate_ids.add(ident)
            self.ids.add(ident)
        if tag == "a" and attr.get("name"):
            self.ids.add(attr["name"])
        if tag in ("a", "img", "source", "video", "audio", "iframe"):
            for key in ("href", "src"):
                if attr.get(key):
                    self.links.append(attr[key])
        if tag == "details":
            self._details += 1

    def handle_endtag(self, tag):
        if tag == "details":
            self._details -= 1
            if self._details < 0:
                self.problems.append("多出一个 </details>")
                self._details = 0


def _local_target(link: str, base_file: Path) -> tuple[Path, str] | None:
    """本地链接 → (目标文件, 锚)；外链、mailto 这类回 None。"""
    parts = urlsplit(link)
    if parts.scheme or parts.netloc:
        return None
    target = (base_file.parent / unquote(parts.path)).resolve() if parts.path else base_file.resolve()
    return target, unquote(parts.fragment)


# ---------------------------------------------------------------- 找页


def find_pages(src_dir: Path) -> list[Page]:
    """源目录下每份 md 一页（不进子目录）；README.md / index.md 出成 index.html 并排第一。"""
    src_dir = Path(src_dir)
    pages: list[Page] = []
    for path in sorted(src_dir.glob("*.md")):
        is_index = path.name.lower() in ("readme.md", "index.md")
        out_name = "index.html" if is_index else path.stem + ".html"
        if is_index and any(p.out_name == "index.html" for p in pages):
            out_name = path.stem + ".html"  # README.md 与 index.md 同在时只让一个当首页
        page = Page(path.resolve(), out_name, _first_h1(path.read_text(encoding="utf-8")) or path.stem)
        if out_name == "index.html":
            pages.insert(0, page)
        else:
            pages.append(page)
    return pages


def _first_h1(text: str) -> str:
    """第一个一级标题的文字；按 markdown 解析，代码块里的 `# 注释` 不算。"""
    tokens = _markdown().parse(text)
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open" and tok.tag == "h1":
            return _plain(tokens[i + 1].content)
    return ""


# ---------------------------------------------------------------- 核查

_NAME_RE = re.compile(r"\b[A-Z][A-Za-z]+\.[A-Z][A-Za-z0-9]*\b")
# 「名.姓」形态里的已知代码前缀（Power Query 的 Table.AddColumn 这类），不算姓名。
_CODE_PREFIXES = frozenset({
    "Table", "Text", "List", "Record", "Number", "Date", "DateTime", "DateTimeZone", "Time",
    "Excel", "Folder", "File", "Csv", "Json", "Xml", "Value", "Splitter", "Combiner", "Type",
    "Duration", "Character", "Order", "Comparer", "Function", "Lines", "Binary", "Logical",
    "JoinKind", "JoinAlgorithm", "Occurrence", "RoundingMode", "Replacer", "ExtraValues",
    "TextEncoding", "Precision", "Day", "RelativePosition", "MissingField", "QuoteStyle",
    "GroupKind", "Byte", "Percentage", "Currency", "Guid", "Uri", "Sql", "Odbc", "OData",
    "Web", "Path", "Enum", "System", "Microsoft", "Windows",
})
_USER_PATH_RE = re.compile(r"[A-Za-z]:\\+Users\\+([^\\/\s\"'<>`]+)", re.I)
# 路径里不是人名的用户目录（公共、默认、省略号写法）；带 <> 的占位写法本来就匹配不上路径正则。
_GENERIC_USERS = frozenset({"public", "default", "..."})


def _scan_names(text: str, names: Iterable[str], allow: Iterable[str]) -> list[tuple[int, str]]:
    allowed = set(allow)
    hits: list[tuple[int, str]] = []
    listed = [(n, re.compile(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])") if n.isascii() else None)
              for n in names if n]
    for lineno, line in enumerate(text.splitlines(), 1):
        found: set[str] = set()
        for m in _NAME_RE.finditer(line):
            word = m.group(0)
            if word.split(".")[0] not in _CODE_PREFIXES and word not in allowed:
                found.add(word)
        for m in _USER_PATH_RE.finditer(line):
            if m.group(1).lower() not in _GENERIC_USERS and not m.group(1).startswith("%"):
                found.add(m.group(0))
        for name, word_re in listed:
            if (word_re.search(line) if word_re else name in line):
                found.add(name)
        hits.extend((lineno, word) for word in sorted(found))
    return hits


def _check_examples(md, text: str) -> list[tuple[int, str]]:
    """每个二级节要有例子；回 [(行号, 问题)]。"""
    problems: list[tuple[int, str]] = []
    tokens = md.parse(text)
    sections: list[dict] = []
    for i, tok in enumerate(tokens):
        line = tok.map[0] + 1 if tok.map else 0
        if tok.type == "heading_open" and tok.tag == "h2":
            sections.append({"title": tokens[i + 1].content.strip(), "line": line,
                             "example": False, "exempt": None})
            continue
        if not sections:
            continue  # 文首概述
        cur = sections[-1]
        if tok.type == "heading_open" and tok.tag == "h3":
            if _EXAMPLE_H3_RE.match(_strip_number(tokens[i + 1].content)):
                cur["example"] = True
        elif tok.type == "paragraph_open" and i + 1 < len(tokens):
            if _EXAMPLE_PARA_RE.match(tokens[i + 1].content.lstrip()):
                cur["example"] = True
        if tok.type in ("html_block", "inline"):
            for m in _EXEMPT_RE.finditer(tok.content):
                reason = m.group(1).strip()
                if reason:
                    cur["exempt"] = cur["exempt"] or reason
                else:
                    problems.append((line, f"「{cur['title']}」的豁免注释没写理由（写成 <!-- {EXEMPT_LABEL}：理由 -->）"))
    for sec in sections:
        title = _strip_number(sec["title"])
        if sec["example"] or sec["exempt"] or title.startswith(_AUTO_EXEMPT_PREFIXES):
            continue
        problems.append((sec["line"], f"「{sec['title']}」这一节没有例子（加「### 例 N：…」三级标题或以「**例 N**」开头的段落；"
                                      f"确实不需要就在节内写 <!-- {EXEMPT_LABEL}：理由 -->）"))
    return problems


def _strip_number(title: str) -> str:
    return _NUMBER_PREFIX_RE.sub("", _plain(title), count=1)


def _d2_blocks(md, text: str) -> list[int]:
    return [tok.map[0] + 1 for tok in md.parse(text)
            if tok.type == "fence" and tok.info.strip().split(" ")[0] == "d2" and tok.map]


def check(pages: list[Page], *, names: Iterable[str] = (), allow: Iterable[str] = ()) -> list[str]:
    """核查一批页；回问题清单（空 = 全过）。每条以「文件:行号:」或「文件:」开头。"""
    md = _markdown()
    names, allow = list(names), list(allow)
    problems: list[str] = []
    cache: dict[Path, str] = {}

    def rendered(path: Path) -> str:
        if path not in cache:
            cache[path] = _render(md, path.read_text(encoding="utf-8"))[0]
        return cache[path]

    for page in pages:
        where = page.src
        text = page.src.read_text(encoding="utf-8")
        for lineno, word in _scan_names(text, names, allow):
            problems.append(f"{where}:{lineno}: 疑似员工姓名或个人路径 {word}（文档会随程序外发）")
        for lineno, msg in _check_examples(md, text):
            problems.append(f"{where}:{lineno}: {msg}")
        if shutil.which("d2") is None:
            for lineno in _d2_blocks(md, text):
                problems.append(f"{where}:{lineno}: 有 d2 流程图，但{_D2_HINT}")
        body = rendered(page.src)
        info = _HtmlInfo(body)
        problems.extend(f"{where}: {p}" for p in info.problems)
        if info.duplicate_ids:
            problems.append(f"{where}: id 重复 {', '.join(sorted(info.duplicate_ids))}")
        for link in sorted(set(info.links)):
            local = _local_target(link, page.src)
            if local is None:
                continue
            target, anchor = local
            if not target.exists():
                problems.append(f"{where}:{_line_of(text, link)}: 本地链接指向的文件不存在 {unquote(link)}")
                continue
            if not anchor or target.suffix.lower() not in (".md", ".html", ".htm"):
                continue
            target_html = rendered(target) if target.suffix.lower() == ".md" else target.read_text(encoding="utf-8")
            if anchor not in _HtmlInfo(target_html).ids:
                problems.append(f"{where}:{_line_of(text, link)}: 锚点不存在 {unquote(link)}")
    return problems


def _line_of(text: str, link: str) -> int:
    for needle in (link, unquote(link)):
        for lineno, line in enumerate(text.splitlines(), 1):
            if needle in line:
                return lineno
    return 0


# ---------------------------------------------------------------- 产物


def _token_css() -> str:
    from msui.resources import parse_tokens

    dark = parse_tokens((PKG_DIR / "tokens.css").read_text(encoding="utf-8"))
    light = parse_tokens((PKG_DIR / "tokens-light.css").read_text(encoding="utf-8"))

    def decl(tokens: dict[str, str]) -> str:
        return "".join(f"--{k}: {v};" for k, v in tokens.items())

    return f":root{{{decl(dark)}}}\n@media (prefers-color-scheme: light){{:root{{{decl(light)}}}}}\n"


_CSS = """
*{box-sizing:border-box}
body{margin:0;font:15px/1.7 "Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;color:var(--text);background:var(--win)}
nav{position:fixed;top:0;left:0;bottom:0;width:270px;overflow:auto;background:var(--card);border-right:1px solid var(--border);padding:var(--space-4) var(--space-3);font-size:13.5px}
nav a{display:block;padding:3px 8px;border-radius:5px;color:var(--text);text-decoration:none}
nav a:hover{background:var(--card-hover)}
nav a.cur{background:var(--brand);color:var(--on-brand)}
nav .ol a{padding-left:20px;color:var(--text-dim);font-size:12.5px}
nav .ol a.l3{padding-left:32px}
main{margin:var(--space-5) var(--space-5) var(--space-6) calc(270px + var(--space-5));padding:var(--space-4) 40px 80px;max-width:1280px;overflow-wrap:anywhere;min-width:0;background:var(--card);border:1px solid var(--border);border-radius:10px}
h1{font-size:26px;border-bottom:1px solid var(--border);padding-bottom:8px}
h2{font-size:21px;margin-top:40px;border-bottom:1px solid var(--border);padding-bottom:4px}
h3{font-size:17px;margin-top:28px}
a{color:var(--info)}
code{font-family:var(--font-mono);background:var(--win);padding:1px 5px;border-radius:4px;font-size:.88em}
pre{background:var(--win);border:1px solid var(--border);padding:12px 14px;border-radius:6px;overflow:auto;line-height:1.45}
pre code{background:none;padding:0}
table{border-collapse:collapse;margin:12px 0;font-size:14px;display:block;overflow:auto;max-width:100%}
th,td{border:1px solid var(--border);padding:5px 10px;vertical-align:top}
th{background:var(--win)}
blockquote{margin:12px 0;padding:6px 14px;border-left:4px solid var(--border-hover);color:var(--text-dim);background:var(--win)}
details{margin:8px 0;border:1px solid var(--border);border-radius:6px;padding:4px 12px;background:var(--win)}
summary{cursor:pointer;color:var(--text-dim)}
.d2{border:1px solid var(--border);border-radius:6px;padding:12px;margin:12px 0;overflow:auto;text-align:center}
.d2 svg{max-width:100%;height:auto}
main img{max-width:100%;height:auto}
:target{scroll-margin-top:16px;background:var(--warn-bg)}
footer{color:var(--muted);font-size:13px}
@media(max-width:760px){nav{position:relative;width:100%;max-height:42vh;border-right:0;border-bottom:1px solid var(--border)}main{margin:0;border-radius:0;padding:18px 16px 60px}}
"""


def _sidebar(current: Page, outline: list[tuple[int, str, str]], pages: list[Page]) -> str:
    parts = []
    for page in pages:
        cls = ' class="cur" aria-current="page"' if page is current else ""
        parts.append(f'<a href="{quote(page.out_name)}"{cls}>{html.escape(page.title)}</a>')
        if page is current and outline:
            parts.append('<div class="ol">')
            parts += [f'<a class="l{lv}" href="#{html.escape(a, quote=True)}">{html.escape(t)}</a>'
                      for lv, a, t in outline]
            parts.append("</div>")
    return "\n".join(parts)


def _rewrite_links(body: str, page: Page, out_dir: Path, md_to_html: dict[Path, str]) -> str:
    """md 之间的链接改指产物；指向别的本地文件的按产物位置重算相对路径。"""
    def swap(m: re.Match) -> str:
        attr, link = m.group(1), html.unescape(m.group(3))
        local = _local_target(link, page.src)
        if local is None or link.startswith("#"):
            return m.group(0)
        target, _ = local
        parts = urlsplit(link)
        path = md_to_html.get(target) or os.path.relpath(target, out_dir.resolve()).replace(os.sep, "/")
        new = urlunsplit(("", "", quote(path, safe="/._-"), parts.query, parts.fragment))
        return f'{attr}="{html.escape(new, quote=True)}"'
    # 代码块里的示例（<pre>…</pre>）原样保留，只改真链接。
    pieces = re.split(r"(<pre[\s>].*?</pre>)", body, flags=re.S)
    return "".join(piece if piece.startswith("<pre") else
                   re.sub(r'''\b(href|src)=(["'])(.*?)\2''', swap, piece) for piece in pieces)


def _d2_svg(source: str) -> str:
    result = subprocess.run(["d2", "--layout", "elk", "--pad", "16", "-", "-"],
                            input=source, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "d2 出错")
    return f'<div class="d2">{re.sub(r"^<[?]xml[^>]*>", "", result.stdout.strip())}</div>'


def _assemble(pages: list[Page], out_dir: Path) -> tuple[dict[str, str], list[str]]:
    md = _markdown()
    md_to_html = {p.src: p.out_name for p in pages}
    token_css = _token_css()
    written: dict[str, str] = {}
    problems: list[str] = []
    for page in pages:
        body, outline = _render(md, page.src.read_text(encoding="utf-8"))
        body = _rewrite_links(body, page, out_dir, md_to_html)

        def draw(m: re.Match) -> str:
            try:
                return _d2_svg(html.unescape(m.group(1)))
            except (ValueError, OSError) as exc:
                problems.append(f"{page.src}: d2 流程图出不了：{exc}")
                return m.group(0)
        body = re.sub(r'<pre><code class="language-d2">(.*?)</code></pre>', draw, body, flags=re.S)
        written[page.out_name] = (
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{html.escape(page.title)}</title><style>{token_css}{_CSS}</style></head>"
            f'<body><nav aria-label="文档目录">{_sidebar(page, outline, pages)}</nav><main>{body}'
            f"<footer><hr>由 {html.escape(page.src.name)} 生成。请改 md 后重新生成，不要手改本页。</footer>"
            "</main></body></html>")
    problems += _check_output(written, out_dir)
    return written, problems


def _check_output(written: dict[str, str], out_dir: Path) -> list[str]:
    """连侧栏和改写后的链接一起核对；还没写盘的页从本批产物里读。"""
    out_dir = out_dir.resolve()
    planned = {(out_dir / name).resolve(): text for name, text in written.items()}
    problems = []
    for path, text in planned.items():
        for link in sorted(set(_HtmlInfo(text).links)):
            local = _local_target(link, path)
            if local is None:
                continue
            target, anchor = local
            if target not in planned and not target.exists():
                problems.append(f"{path.name}: 产物里的链接指向不存在的文件 {unquote(link)}")
                continue
            if anchor and target in planned and anchor not in _HtmlInfo(planned[target]).ids:
                problems.append(f"{path.name}: 产物里的锚点不存在 {unquote(link)}")
    return problems


def build(src_dir: Path, out_dir: Path, *, check_only: bool = False,
          names: Iterable[str] = (), allow: Iterable[str] = (),
          echo: Callable[[str], None] = print) -> int:
    """核查 → 全部出好 → 再写盘；任何一步有问题就一份不写、回 1。"""
    src_dir, out_dir = Path(src_dir), Path(out_dir)
    pages = find_pages(src_dir)
    if not pages:
        echo(f"⛔ {src_dir} 下没有 md")
        return 1
    problems = check(pages, names=names, allow=allow)
    if not problems and not check_only:
        written, problems = _assemble(pages, out_dir)
    if problems:
        for p in problems:
            echo(f"⛔ {p}")
        echo(f"⛔ {len(problems)} 项没过；没有写任何产物")
        return 1
    echo(f"✓ {len(pages)} 份：例子 / 姓名 / 链接 / 锚点核查通过")
    if check_only:
        echo("✓ 只核查（--check），没有写文件")
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in written.items():
        (out_dir / name).write_text(text, encoding="utf-8")
        echo(f"✓ {out_dir / name}")
    return 0


# ---------------------------------------------------------------- 自证

_SELF_GOOD = """# 自证样本

文首概述：说明讲什么、数据取自哪里。

## 1. 规则一

**例 1：样本**

| 输入 | 结果 |
|---|---|
| 1 | 1 |

[本页锚点](#1-规则一) [另一页](other.md#目标节) [外链](https://example.invalid/x#y)

```text
代码块里的 [链接](missing.md) 不算链接
```

## 2. 规则二

### 例 2：三级标题也算

<details><summary>附录</summary>

折叠内容

</details>

## 3. 概念说明

<!-- 无需例子：只解释名词，没有规则 -->

## 请你回复

1. 选 A 还是 B？推荐 A。
"""

_SELF_OTHER = "# 另一页\n\n## 目标节\n\n<!-- 无需例子：自证用 -->\n"

# (要命中的问题字样, 往正样本末尾追加的扰动)
_SELF_NEGATIVES = (
    ("没有例子", "\n## 4. 漏了例子的节\n\n只有规则。\n"),
    ("没写理由", "\n## 4. 空理由\n\n<!-- 无需例子： -->\n"),
    ("疑似员工姓名", "\n见 Synthetic.Person 的说明。\n"),
    ("疑似员工姓名", "\n路径 C:\\Users\\synthetic\\x.txt\n"),
    ("文件不存在", "\n[坏链](missing.md)\n"),
    ("锚点不存在", "\n[坏锚](other.md#没有这节)\n"),
    ("没有闭合", "\n<details><summary>没关</summary>\n"),
    ("id 重复", '\n<a id="same"></a><a id="same"></a>\n'),
    ("没装 d2", "\n```d2\na -> b\n```\n"),
)


def self_test(echo: Callable[[str], None] = print) -> int:
    """临时目录里跑正负对照：正样本全过，每个负样本都被拦下；不碰真实文档。"""
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="msui-docgen-self-test-") as tmp:
        root = Path(tmp)
        (root / "other.md").write_text(_SELF_OTHER, encoding="utf-8")
        sample = root / "README.md"

        def run(text: str) -> list[str]:
            sample.write_text(text, encoding="utf-8")
            return check(find_pages(root))

        if got := run(_SELF_GOOD):
            failures.append(f"正样本被误拦：{got}")
        for expect, extra in _SELF_NEGATIVES:
            if expect == "没装 d2":
                saved_path = os.environ.get("PATH", "")
                os.environ["PATH"] = str(root / "no-such-bin")  # 模拟本机没装 d2
                try:
                    got = run(_SELF_GOOD + extra)
                finally:
                    os.environ["PATH"] = saved_path
            else:
                got = run(_SELF_GOOD + extra)
            if not any(expect in p for p in got):
                failures.append(f"负样本没拦住（应报「{expect}」）：{extra.strip()}")
        if got := run(_SELF_GOOD):
            failures.append(f"还原后正样本被误拦：{got}")
    if failures:
        for f in failures:
            echo(f"⛔ 自证失败：{f}")
        return 1
    echo(f"✓ 自证通过：正样本全过，{len(_SELF_NEGATIVES)} 个负样本"
         "（缺例子 / 空理由豁免 / 姓名 / 个人路径 / 断链 / 坏锚点 / details 没闭合 / id 重复 / 没装 d2）全部拦下")
    return 0


# ---------------------------------------------------------------- 打开文档


def open_doc(path: str | os.PathLike, anchor: str = "", *,
             opener: Callable[[str], object] | None = None) -> dict:
    """用系统浏览器打开一份生成好的文档，并跳到 ``anchor``（标题锚点，不带 #）。

    回 ``{"opened": bool, "url": str, "message": str}``，``message`` 是给用户看的一句话；
    文件不在不抛、不拿别的页顶上，``opened`` 为 False。Windows 上把 ``file:`` 地址交给
    系统时 ``#锚`` 常被丢掉，所以带锚点时先写一张临时跳转页、打开它再跳过去。
    ``opener`` 默认 :func:`webbrowser.open`，测试里换成假浏览器。
    """
    target = Path(path).resolve()
    if not target.is_file():
        return {"opened": False, "url": "",
                "message": f"没找到文档 {target.name}（{target.parent}），没打开。请维护者重新生成文档或重新打包。"}
    url = target.as_uri() + ("#" + quote(anchor, safe="") if anchor else "")
    launch = url
    if anchor and sys.platform == "win32":
        launch = _redirect_page(url).as_uri()
    (opener or webbrowser.open)(launch)
    return {"opened": True, "url": url, "message": f"已用浏览器打开 {target.name}"}


def _redirect_page(url: str) -> Path:
    folder = Path(tempfile.gettempdir()) / "msui-open-doc"
    folder.mkdir(parents=True, exist_ok=True)
    # 每次一张新跳转页：连点两份文档时，前一次的浏览器还没读到跳转页也不会被后一次改掉。
    fd, name = tempfile.mkstemp(prefix="open-", suffix=".html", dir=folder)
    os.close(fd)
    page = Path(name)
    page.write_text('<!doctype html><meta charset="utf-8">'
                    f"<script>location.replace({json.dumps(url)})</script>", encoding="utf-8")
    return page


# ---------------------------------------------------------------- 命令行


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="msui-docs", description="把目录下的 md 生成成统一样式的单页 html（核查不过不写产物）。")
    parser.add_argument("src", nargs="?", help="源目录（放 md 的地方，比如 docs）")
    parser.add_argument("out", nargs="?", help="产物目录（比如 pages/docs）")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="只核查，不写文件")
    mode.add_argument("--self-test", action="store_true", help="自证：各道核查对正负样本都判对")
    parser.add_argument("--names", type=Path, help="姓名名单文件：一行一个，# 开头是注释")
    parser.add_argument("--allow", action="append", default=[], metavar="词",
                        help="「名.姓」形态但其实是代码符号的词，可重复")
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            return self_test()
        if not args.src or not args.out:
            parser.error("要给源目录和产物目录（或用 --self-test）")
        names: list[str] = []
        if args.names:
            names = [ln.strip() for ln in args.names.read_text(encoding="utf-8").splitlines()
                     if ln.strip() and not ln.lstrip().startswith("#")]
        return build(Path(args.src), Path(args.out), check_only=args.check, names=names, allow=args.allow)
    except MissingDependency as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
