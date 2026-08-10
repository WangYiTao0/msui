"""公开面清理守卫：README 与全部代码/注释里不许出现内部痕迹。

形态断言 + allowlist，不靠人眼通读：

- 内部 spec 指针（私仓名/票号）只允许 README 里那一行（票面要求保留的
  spec 指针），别处一律不许出现；
- 公司名、个人账号、个人邮箱这类痕迹在任何被 git 跟踪的文本文件里一律
  不许出现。

守卫自身必须写出这些字样才能搜它们，所以扫描时跳过本文件。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()

# 公司名 / 个人账号 / 个人邮箱——公开面零出现（大小写不敏感）。
FORBIDDEN_PATTERNS = (
    re.compile(r"milwaukee", re.IGNORECASE),
    re.compile(r"mitumao", re.IGNORECASE),
    re.compile(r"as5818956", re.IGNORECASE),
    re.compile(r"@gmail\.com", re.IGNORECASE),
    re.compile(r"parallels", re.IGNORECASE),
)

# 内部私仓名：只允许 README 的 spec 指针那一行出现。
INTERNAL_REPO = "MSToolbox"


def _tracked_text_files() -> list[Path]:
    # -co --exclude-standard：已跟踪 + 未跟踪但不被忽略的文件都算公开面——
    # 只扫已跟踪的话，还没 git add 的新文件会漏检（假绿）。
    out = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    files = []
    for line in out.splitlines():
        path = REPO_ROOT / line
        if path == SELF or not path.is_file():
            continue
        files.append(path)
    return files


def test_tracked_file_listing_is_sane():
    """守卫的地基自证：清单必须非空且含 README——空清单会让下面两条假绿。"""
    files = _tracked_text_files()
    assert len(files) > 10
    assert REPO_ROOT / "README.md" in files


def test_no_company_or_personal_traces():
    for path in _tracked_text_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in FORBIDDEN_PATTERNS:
            assert not pattern.search(text), (
                f"{path.relative_to(REPO_ROOT)} 出现了不该进公开面的字样"
                f"（形态 {pattern.pattern}）"
            )


def test_internal_spec_pointer_only_in_readme_single_line():
    for path in _tracked_text_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        hit_lines = [line for line in text.splitlines() if INTERNAL_REPO in line]
        if path == REPO_ROOT / "README.md":
            assert len(hit_lines) == 1, (
                f"README 里内部 spec 指针只许一行，实际 {len(hit_lines)} 行：{hit_lines}"
            )
            assert "issues/107" in hit_lines[0], "README 那一行必须就是 spec 指针"
        else:
            assert not hit_lines, (
                f"{path.relative_to(REPO_ROOT)} 出现内部仓指针：{hit_lines}"
            )
