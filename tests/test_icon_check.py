"""图标检查函数 msui.testing.icon_problems（票 #32）：只用 tmp_path 下现搭的夹具仓。

夹具里的 PNG / ico 用标准库按文件格式现造（不依赖 Pillow），每条测试只弄坏一样，
断言问题清单点到那一样、而且只点到那一样。
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

from msui import testing as gate

SPEC_OK = '''import os
exe = EXE(
    pyz,
    name="app",
    icon=os.path.join(SPECPATH, "assets", "icon.ico"),
)
'''


def _png(width: int = 256, height: int = 256, *, pad: int = 0) -> bytes:
    """最小的真 PNG：签名 + IHDR（RGBA）+ 一块 IDAT + 可选填充块 + IEND。"""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00\x00" * width for _ in range(height))
    body = chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9))
    if pad:
        body += chunk(b"tEXt", b"pad\x00" + b"x" * pad)
    return b"\x89PNG\r\n\x1a\n" + body + chunk(b"IEND", b"")


def _ico(sizes=(256, 48, 32, 16)) -> bytes:
    """ico 目录：每档一条 16 字节目录项（256 记作 0），图像数据给几个占位字节。"""
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, data = b"", b""
    for size in sizes:
        blob = b"\x00" * 8
        byte = 0 if size == 256 else size
        entries += struct.pack("<BBBBHHII", byte, byte, 0, 0, 1, 32, len(blob), offset + len(data))
        data += blob
    return header + entries + data


def _repo(root: Path, *, toml='icon = "assets/icon.png"\n', png: bytes | None = None,
          ico: bytes | None = None, spec: str | None = SPEC_OK) -> Path:
    (root / "assets").mkdir(parents=True)
    if toml is not None:
        (root / "miniprog.toml").write_text('id = "demo"\n' + toml, encoding="utf-8")
    (root / "assets" / "icon.png").write_bytes(_png() if png is None else png)
    (root / "assets" / "icon.ico").write_bytes(_ico() if ico is None else ico)
    if spec is not None:
        (root / "app.spec").write_text(spec, encoding="utf-8")
    return root


def _only(problems: list[str], *pieces: str) -> None:
    assert len(problems) == 1, problems
    for piece in pieces:
        assert piece in problems[0], problems


def test_complete_repo_passes(tmp_path):
    assert gate.icon_problems(_repo(tmp_path)) == []


def test_png_missing(tmp_path):
    root = _repo(tmp_path)
    (root / "assets" / "icon.png").unlink()
    _only(gate.icon_problems(root), "assets/icon.png", "不存在")


def test_png_wrong_size(tmp_path):
    _only(gate.icon_problems(_repo(tmp_path, png=_png(128, 128))), "128×128", "256×256")


def test_png_not_square_256(tmp_path):
    _only(gate.icon_problems(_repo(tmp_path, png=_png(256, 128))), "256×128")


def test_png_too_large(tmp_path):
    big = _png(pad=70 * 1024)
    _only(gate.icon_problems(_repo(tmp_path, png=big)), "超过", "64 KB")


def test_png_at_exactly_the_limit_passes(tmp_path):
    base = _png()
    pad = gate.ICON_PNG_MAX_BYTES - len(_png(pad=1)) + 1
    exact = _png(pad=pad)
    assert len(exact) == gate.ICON_PNG_MAX_BYTES and len(base) < len(exact)
    assert gate.icon_problems(_repo(tmp_path, png=exact)) == []


def test_png_that_is_not_a_png(tmp_path):
    _only(gate.icon_problems(_repo(tmp_path, png=b"GIF89a" + b"\x00" * 40)), "不是 PNG")


def test_ico_missing_sizes(tmp_path):
    _only(gate.icon_problems(_repo(tmp_path, ico=_ico((256, 32)))), "缺 48、16 档")


def test_ico_missing(tmp_path):
    root = _repo(tmp_path)
    (root / "assets" / "icon.ico").unlink()
    _only(gate.icon_problems(root), "assets/icon.ico", "不存在")


def test_ico_that_is_not_an_ico(tmp_path):
    _only(gate.icon_problems(_repo(tmp_path, ico=_png())), "不是 ico")


def test_spec_without_icon(tmp_path):
    spec = 'exe = EXE(pyz, name="app")\n'
    problems = gate.icon_problems(_repo(tmp_path, spec=spec))
    _only(problems, "app.spec", "EXE(", "没写 icon=")


def test_spec_icon_pointing_elsewhere_is_followed(tmp_path):
    spec = 'exe = EXE(pyz, icon="assets/other.ico")\n'
    root = _repo(tmp_path, spec=spec)
    _only(gate.icon_problems(root), "assets/other.ico", "不存在")
    (root / "assets" / "other.ico").write_bytes(_ico())
    assert gate.icon_problems(root) == []


def test_no_spec_at_all(tmp_path):
    _only(gate.icon_problems(_repo(tmp_path, spec=None)), ".spec")


def test_no_spec_still_checks_the_ico_at_the_usual_place(tmp_path):
    problems = gate.icon_problems(_repo(tmp_path, spec=None, ico=_ico((256, 48, 32))))
    assert len(problems) == 2 and any("assets/icon.ico：缺 16 档" in p for p in problems), problems


def test_toml_without_icon(tmp_path):
    _only(gate.icon_problems(_repo(tmp_path, toml="")), "miniprog.toml", "没写 icon")


def test_toml_icon_pointing_to_missing_file(tmp_path):
    problems = gate.icon_problems(_repo(tmp_path, toml='icon = "assets/nope.png"\n'))
    _only(problems, "assets/nope.png", "不存在")


def test_toml_icon_outside_the_repo(tmp_path):
    problems = gate.icon_problems(_repo(tmp_path / "repo", toml='icon = "../icon.png"\n'))
    _only(problems, "../icon.png", "仓内")


def test_toml_missing(tmp_path):
    _only(gate.icon_problems(_repo(tmp_path, toml=None)), "miniprog.toml", "不存在")


def test_several_problems_are_all_listed(tmp_path):
    root = _repo(tmp_path, toml="", ico=_ico((256,)), spec='exe = EXE(pyz)\n')
    problems = gate.icon_problems(root)
    assert len(problems) == 3, problems
    assert any("没写 icon" in p and "miniprog.toml" in p for p in problems)
    assert any("缺 48、32、16 档" in p for p in problems)
    assert any("没写 icon=" in p for p in problems)


def test_truncated_png_is_reported_not_raised(tmp_path):
    _only(gate.icon_problems(_repo(tmp_path, png=_png()[:20])), "不是 PNG")


def test_spec_icon_with_backslashes_is_understood(tmp_path):
    spec = 'exe = EXE(pyz, icon="assets\\\\icon.ico")\n'
    assert gate.icon_problems(_repo(tmp_path, spec=spec)) == []


def test_spec_icon_outside_the_repo_is_reported(tmp_path):
    for icon in ('"C:/icons/icon.ico"', '"/abs/icon.ico"', '"../icon.ico"'):
        root = _repo(tmp_path / icon.strip('"').replace("/", "_").replace(":", ""), spec=f"exe = EXE(pyz, icon={icon})\n")
        _only(gate.icon_problems(root), "icon= 要指向仓内的 ico")


def test_spec_icon_written_as_fstring_is_understood(tmp_path):
    spec = 'exe = EXE(pyz, icon=f"{SPECPATH}/assets/icon.ico")\n'
    assert gate.icon_problems(_repo(tmp_path, spec=spec)) == []


def test_spec_icon_through_a_variable_is_followed(tmp_path):
    spec = 'import os\nICON = os.path.join(SPECPATH, "assets", "real.ico")\nexe = EXE(pyz, icon=ICON)\n'
    root = _repo(tmp_path, spec=spec)
    _only(gate.icon_problems(root), "assets/real.ico", "不存在")
    (root / "assets" / "real.ico").write_bytes(_ico())
    assert gate.icon_problems(root) == []


def test_spec_icon_that_cannot_be_read_is_reported(tmp_path):
    spec = 'exe = EXE(pyz, icon=pick_icon())\n'
    _only(gate.icon_problems(_repo(tmp_path, spec=spec)), "读不出")


def test_spec_icon_joined_outside_the_repo_is_reported(tmp_path):
    spec = 'import os\nexe = EXE(pyz, icon=os.path.join(SPECPATH, "..", "shared.ico"))\n'
    _only(gate.icon_problems(_repo(tmp_path / "repo", spec=spec)), "icon= 要指向仓内的 ico")
