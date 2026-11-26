"""可访问性检查 msui.testing.a11y_problems（0.14.0 起）的自证测试。

三条规则，都是「静态文本层」的绊线，各自先证明「认得出坏的」再证明「好的不误报」：

1. 提示条 `.notice` 写 role：error 态写 role="alert"，其余写 role="alert" 或
   role="status"——提示条是 JS 改了文字 / 取消 hidden 才出现的，不写 role 读屏
   软件不念；
2. 图标按钮 `button.icon` 有可访问名称（aria-label / aria-labelledby），里面的
   <svg> 写 aria-hidden="true"——读屏念的是动作，不是一串路径；
3. 回车处理判断输入法：`event.key === "Enter"` 附近必须有 `isComposing`——中文
   输入法按回车是「确认候选词」，不判断就会提前提交。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from msui import testing as gate
from msui.resources import ASSET_NAMES, asset_path

REPO_ROOT = Path(__file__).resolve().parent.parent

ICON = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8"/></svg>'


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------- 提示条 role


@pytest.mark.parametrize(
    "markup",
    [
        '<p class="notice error" role="alert" hidden></p>',
        '<p class="notice ok" role="status" hidden>已保存</p>',
        '<p class="notice warn" role="alert">注意</p>',
        '<div class="notice info" role="status">进行中</div>',
        '<p class="notice" role="status"></p>',
    ],
)
def test_notice_with_a_fitting_role_passes(tmp_path, markup):
    write(tmp_path, "index.html", markup)
    assert gate.a11y_problems(tmp_path) == []


@pytest.mark.parametrize(
    ("markup", "needle"),
    [
        ('<p class="notice error" hidden></p>', 'role="alert"'),
        ('<p class="notice ok">已保存</p>', 'role="status"'),
        ('<p class="notice error" role="status"></p>', 'role="alert"'),
        ('<p class="notice info" role="note"></p>', 'role="status"'),
    ],
)
def test_notice_without_a_fitting_role_is_reported_with_file_and_line(tmp_path, markup, needle):
    write(tmp_path, "page.html", "<main>\n  <h1>x</h1>\n  " + markup + "\n</main>\n")
    problems = gate.a11y_problems(tmp_path)
    assert len(problems) == 1, problems
    assert problems[0].startswith("page.html:3:"), problems
    assert needle in problems[0]


def test_a_class_that_merely_contains_notice_is_not_a_notice(tmp_path):
    write(tmp_path, "index.html", '<p class="notices-list">x</p><p class="my-notice">y</p>')
    assert gate.a11y_problems(tmp_path) == []


# ---------------------------------------------------------------- 图标按钮


def test_icon_button_with_label_and_hidden_svg_passes(tmp_path):
    write(
        tmp_path,
        "index.html",
        f'<button class="icon" type="button" aria-label="清除">{ICON}</button>'
        f'<span id="t">上移</span><button class="icon" aria-labelledby="t">{ICON}</button>',
    )
    assert gate.a11y_problems(tmp_path) == []


@pytest.mark.parametrize(
    ("markup", "needle"),
    [
        (f'<button class="icon" type="button">{ICON}</button>', "aria-label"),
        (f'<button class="icon" aria-label="  ">{ICON}</button>', "aria-label"),
        (f'<button class="icon" title="清除">{ICON}</button>', "aria-label"),
        ('<button class="icon" aria-label="清除"><svg viewBox="0 0 16 16"><path d="M1 1"/></svg></button>', "aria-hidden"),
    ],
)
def test_icon_button_missing_a_name_or_hiding_is_reported(tmp_path, markup, needle):
    write(tmp_path, "index.html", markup)
    problems = gate.a11y_problems(tmp_path)
    assert len(problems) == 1, problems
    assert needle in problems[0]


def test_svg_outside_an_icon_button_is_not_checked(tmp_path):
    write(tmp_path, "index.html", '<label class="search"><svg viewBox="0 0 1 1"></svg><input></label><button>文字<svg></svg></button>')
    assert gate.a11y_problems(tmp_path) == []


def test_the_empty_state_icon_class_is_not_an_icon_button(tmp_path):
    write(tmp_path, "index.html", '<div class="empty"><div class="icon">○</div></div>')
    assert gate.a11y_problems(tmp_path) == []


# ---------------------------------------------------------------- 回车与输入法

GUARDED = [
    'input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) save(); });',
    "q.addEventListener('keydown', function (event) {\n  if (event.isComposing || event.keyCode === 229) return;\n  if (event.key === 'Enter') go();\n});",
    'el.onkeydown = (e) => {\n  if (e.isComposing) return;\n  switch (e.key) {\n    case "Enter": go(); break;\n  }\n};',
]

UNGUARDED = [
    '$("dir-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("dir-save").click(); });',
    "box.addEventListener('keyup', e => e.key == 'Enter' && go());",
    'if ("Enter" === event.key) submit();',
    'switch (e.key) {\n  case "Enter":\n    go();\n}',
    'if (event.key !== "Enter") return;\nsend();',
]


@pytest.mark.parametrize("script", GUARDED)
def test_enter_handler_that_checks_ime_composition_passes(tmp_path, script):
    write(tmp_path, "app.js", script)
    assert gate.a11y_problems(tmp_path) == []


@pytest.mark.parametrize("script", UNGUARDED)
def test_enter_handler_without_ime_check_is_reported(tmp_path, script):
    write(tmp_path, "app.js", "// 头\n" + script)
    problems = gate.a11y_problems(tmp_path)
    assert len(problems) == 1, problems
    assert problems[0].startswith("app.js:"), problems
    assert "isComposing" in problems[0]


def test_inline_script_in_html_is_scanned_with_real_line_numbers(tmp_path):
    write(
        tmp_path,
        "index.html",
        '<!DOCTYPE html>\n<body>\n<script>\nconst a = 1;\nq.onkeydown = (e) => { if (e.key === "Enter") go(); };\n</script>\n</body>\n',
    )
    problems = gate.a11y_problems(tmp_path)
    assert len(problems) == 1, problems
    assert problems[0].startswith("index.html:5:"), problems


def test_the_guard_must_be_near_not_anywhere_in_the_file(tmp_path):
    far = "if (e.isComposing) return;\n" + "\n".join(f"const v{i} = {i};" for i in range(20))
    write(tmp_path, "app.js", far + '\nif (e.key === "Enter") go();\n')
    assert len(gate.a11y_problems(tmp_path)) == 1


def test_words_mentioning_enter_in_prose_are_not_handlers(tmp_path):
    write(tmp_path, "app.js", '// 按 Enter 保存\nconst label = "Enter 键";\n')
    write(tmp_path, "index.html", "<p>按 Enter 或空格切换</p>")
    assert gate.a11y_problems(tmp_path) == []


def test_keycode_13_counts_as_an_enter_handler(tmp_path):
    write(tmp_path, "a.js", "if (e.keyCode === 13) go();\n")
    write(tmp_path, "b.js", "if (e.isComposing) return;\nif (e.which == 13) go();\n")
    assert [p.split(":")[0] for p in gate.a11y_problems(tmp_path)] == ["a.js"]


def test_a_commented_out_enter_handler_is_not_reported(tmp_path):
    write(tmp_path, "app.js", '// if (e.key === "Enter") go();\n  // case "Enter":\n')
    assert gate.a11y_problems(tmp_path) == []


def test_a_commented_out_guard_does_not_count(tmp_path):
    write(tmp_path, "app.js", '// if (e.isComposing) return;\nif (e.key === "Enter") go();\n')
    assert len(gate.a11y_problems(tmp_path)) == 1


def test_script_tag_spanning_lines_reports_the_real_line(tmp_path):
    write(tmp_path, "a.html", '<p>x</p>\n<script\n  type="module">\nif (e.key === "Enter") go();\n</script>\n')
    problems = gate.a11y_problems(tmp_path)
    assert len(problems) == 1 and problems[0].startswith("a.html:4:"), problems


def test_line_separator_characters_do_not_shift_line_numbers(tmp_path):
    write(tmp_path, "a.js", 'const s = "a\u2028b";\nif (e.key === "Enter") go();\n')
    problems = gate.a11y_problems(tmp_path)
    assert len(problems) == 1 and problems[0].startswith("a.js:2:"), problems


def test_an_unclosed_script_is_still_scanned(tmp_path):
    write(tmp_path, "a.html", '<body>\n<script>\nif (e.key === "Enter") go();\n')
    problems = gate.a11y_problems(tmp_path)
    assert len(problems) == 1 and problems[0].startswith("a.html:3:"), problems


def test_role_and_aria_hidden_values_are_case_insensitive(tmp_path):
    write(
        tmp_path,
        "a.html",
        '<p class="notice error" role="Alert"></p>'
        '<button class="icon" aria-label="x"><svg aria-hidden="TRUE"></svg></button>',
    )
    assert gate.a11y_problems(tmp_path) == []


# ---------------------------------------------------------------- 扫描范围


def test_a_file_that_is_not_utf8_is_reported_not_raised(tmp_path):
    (tmp_path / "gbk.js").write_bytes("// 中文\n".encode("gbk"))
    problems = gate.a11y_problems(tmp_path)
    assert len(problems) == 1 and "UTF-8" in problems[0], problems


def test_third_party_scripts_can_be_skipped_by_name(tmp_path):
    write(tmp_path, "vendor/lib.min.js", 'if(e.key==="Enter")go()')
    assert len(gate.a11y_problems(tmp_path)) == 1
    assert gate.a11y_problems(tmp_path, skipped_names=(*ASSET_NAMES, "lib.min.js")) == []


def test_landed_msui_assets_are_skipped(tmp_path):
    for name in ASSET_NAMES:
        write(tmp_path, name, 'if (e.key === "Enter") go();\n<p class="notice error"></p>')
    assert gate.a11y_problems(tmp_path) == []


def test_subdirectories_are_scanned_and_results_are_sorted(tmp_path):
    write(tmp_path, "b.js", 'if (e.key === "Enter") go();')
    write(tmp_path, "docs/a.html", '<p class="notice error"></p>')
    problems = gate.a11y_problems(tmp_path)
    assert [p.split(":")[0] for p in problems] == ["b.js", "docs/a.html"]


def test_a_missing_directory_is_a_problem_not_a_silent_pass(tmp_path):
    problems = gate.a11y_problems(tmp_path / "nope")
    assert len(problems) == 1 and "不存在" in problems[0]


def test_format_a11y_problems_lists_every_line():
    text = gate.format_a11y_problems(["a.html:1: x", "b.js:2: y"])
    assert "a.html:1: x" in text and "b.js:2: y" in text
    assert gate.format_a11y_problems([]) == ""


# ---------------------------------------------------------------- 包自己先过


def test_the_packaged_runlog_script_checks_ime_composition():
    """runlog.js 落进每个消费者的 pages/，它自己的回车处理也得过同一条规则。"""
    text = asset_path("runlog.js").read_text(encoding="utf-8")
    assert gate._ime_enter_problems(text, "runlog.js") == []


@pytest.mark.parametrize("pages", ["examples/minimal/pages", "tests/smoke/pages"])
def test_the_packages_own_pages_pass(pages):
    problems = gate.a11y_problems(REPO_ROOT / pages)
    assert problems == [], gate.format_a11y_problems(problems)
