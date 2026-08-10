# msui

小程序共享 UI 运行时与样式（pywebview + WebView2）：WebView2 检测引导、一行开窗、
共享 tokens/base 样式与样式闸门、js_api 桥通用件、自带 PyInstaller hook。

设计与切票见 spec：[WangYiTao0/MSToolbox#107](https://github.com/WangYiTao0/MSToolbox/issues/107)。

本 README 就是消费者契约：下面五件事按顺序做，一个新的小程序仓从零到跑起来。
所有代码块与 `examples/minimal/` 里的完整示例一字一致（有测试盯着不许漂移），
放心整段照抄。

## 1. 装

requirements 里写一行钉版本的 wheel URL，无需任何凭据；**升级 = 只改这一行里的
两处版本号**：

```
msui @ https://github.com/WangYiTao0/msui/releases/download/v0.2.0/msui-0.2.0-py3-none-any.whl
```

## 2. 最小启动

页面（HTML/CSS/JS）放自己仓的 `pages/` 目录；启动三步——定位页面目录、
`copy_assets` 落共享样式、`run` 开窗：

```python
# examples/minimal/app.py
"""msui 最小消费者：页面归自己，共享样式由 msui 启动时落进来。

三步：定位页面目录 → copy_assets 落共享样式 → run 开窗。
环境变量 APP_SMOKE=1 时隐藏开窗、就绪即关——给 CI/无人值守冒烟用，
自己的仓不需要这条冒烟缝的话，把 smoke 两行删掉即可。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from msui.resources import copy_assets
from msui.shell import run


def page_dir() -> Path:
    """页面目录：冻结态在 _MEIPASS/pages（app.spec 收进去的），源码态在本文件旁。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "pages"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / "pages"


def main() -> None:
    serve_dir = copy_assets(page_dir())  # 每次启动覆盖落样式，页面永远跟着装的这版 msui 走
    smoke = os.environ.get("APP_SMOKE") == "1"
    run(
        serve_dir / "index.html",
        title="示例小程序",
        hidden=smoke,
        on_ready=(lambda window: window.destroy()) if smoke else None,
    )


if __name__ == "__main__":
    main()
```

要点：

- `copy_assets` **无条件覆盖**地把 `tokens.css` + `base.css` 落进页面目录并返回
  该开窗的目录——开窗一律用返回值，别写死 `page_dir`；
- 这两份 css 不入仓、不手改（`pages/.gitignore` 把它们排除掉）；
- `run(...)` 还收 `js_api=`（后端桥对象）、`width/height/min_size`、`icon=`、
  `storage_dir=` + `version=`（持久化与按版本清缓存）等关键字参数，按需加。

## 3. 页面写语义 HTML

写裸 `button` / `input` / `table` / `a` / `h1` 就得到统一长相；任何颜色只经
`var(--token)` 取用，**不许手写十六进制色值**（第 5 步的闸门盯着）：

```html
<!-- examples/minimal/pages/index.html -->
<!DOCTYPE html>
<!--
  语义 HTML 约定：写裸 button / input / table 就得到统一长相；任何颜色只经
  var(--token) 取用，不手写十六进制色值（闸门测试盯着）。
  tokens.css / base.css 不入仓、不手改——启动时由 msui.resources.copy_assets
  落进本目录（无条件覆盖，头部带 msui 版本横幅）。
  要换色时才加 override.css：放本目录、只覆写同名 token 变量值，
  并在 base.css 之后加一行 <link rel="stylesheet" href="override.css">。
-->
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>示例小程序</title>
  <link rel="stylesheet" href="tokens.css">
  <link rel="stylesheet" href="base.css">
</head>
<body>
  <h1>示例小程序</h1>
  <p>下面全是裸标签：没有写任何一行自定义样式，长相来自共享的 base.css。</p>
  <div class="card">
    <h2>操作区</h2>
    <input placeholder="输入点什么">
    <button class="primary">主操作</button>
    <button>次要操作</button>
  </div>
  <table>
    <thead><tr><th>名称</th><th>状态</th></tr></thead>
    <tbody>
      <tr><td>任务一</td><td>已完成</td></tr>
      <tr><td>任务二</td><td>进行中</td></tr>
    </tbody>
  </table>
  <small>底部弱化文字，带一个<a href="#">链接</a>。</small>
</body>
</html>
```

## 4. override.css（默认不用）

默认零配置、不建这个文件。真要换色（比如另一套品牌色）时：

- 在 `pages/` 里建 `override.css`，内容只有一段 `:root { --brand: …; }`——
  **只覆写 tokens.css 里已有的同名变量值**，不写选择器样式；
- 页面里在 `base.css` **之后**加 `<link rel="stylesheet" href="override.css">`；
- 防游离扫描的允许清单已含 `override.css`（改色值就是它的本职），闸门的对比度
  检查吃的是合成后的结果——override 改了什么、闸门就按什么算，压不住红。

## 5. 闸门测试

自己仓里放一份下面的文件，pytest 就有两条样式闸门：配色对比度（WCAG 档位）
与防游离色值扫描：

```python
# examples/minimal/tests/test_style_gate.py
"""样式闸门：对比度 + 防游离色值。整份可照抄，零件全部来自 msui.testing。"""
from __future__ import annotations

from pathlib import Path

from msui import testing as gate
from msui.resources import parse_tokens, tokens_css_path

PAGES = Path(__file__).resolve().parent.parent / "pages"
OVERRIDE = PAGES / gate.OVERRIDE_CSS_NAME  # 默认不存在；要换色时才加

# 页面自己的前景/背景组合往这里追加登记：gate.TokenPair(说明, 前景, 背景, 档位)
MY_PAIRS: tuple[gate.TokenPair, ...] = ()


def _colors() -> dict[str, str]:
    tokens = parse_tokens(tokens_css_path().read_text(encoding="utf-8"))
    if OVERRIDE.is_file():
        tokens = gate.merge_tokens(
            tokens, parse_tokens(OVERRIDE.read_text(encoding="utf-8"))
        )
    return gate.hex_tokens(tokens)


def test_contrast_gate():
    colors = _colors()
    failures = gate.contrast_failures(colors, gate.BASE_TOKEN_PAIRS + MY_PAIRS)
    assert not failures, gate.format_contrast_failures(failures, colors)


def test_no_stray_hex():
    offenders = gate.scan_stray_hex(PAGES)
    assert not offenders, gate.format_stray_hex(offenders)
```

## 打包成冻结产物（PyInstaller）

spec 对 msui **零资源配置**——样式与版本元数据由包自带的 hook 自动收齐，
`datas` 只写自己的页面目录：

```python
# examples/minimal/app.spec
# -*- mode: python ; coding: utf-8 -*-
# 最小消费者的 PyInstaller spec。关键点：对 msui 的资源与元数据**零配置**——
# tokens.css / base.css / dist-info 全由 msui 包自带的 pyinstaller40 hook 收齐。
# datas 只声明自己持有的页面目录。
import os

a = Analysis(
    [os.path.join(SPECPATH, "app.py")],
    pathex=[],
    binaries=[],
    datas=[(os.path.join(SPECPATH, "pages"), "pages")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="app",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # 真实小程序是窗口程序；冒烟只看退出码，不需要控制台
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="app",
)
```

打包与冒烟（不上屏）：

```
pyinstaller examples/minimal/app.spec --noconfirm --distpath dist --workpath build
APP_SMOKE=1 ./dist/app/app
```

## 版本标记：产物里读得出带的是哪版 msui

`copy_assets` 落出去的每份 css 第一行是版本横幅 `/* msui X.Y.Z */`，值取包
自身安装元数据（单一来源，无第二份版本号）：

- **产物文件系统**：`head -1 pages/tokens.css` 直接读出；
- **页面 devtools**：Sources 面板打开 tokens.css，第一行就是。

横幅是 css 注释：tokens 解析整块剔注释、横幅里没有色值，样式闸门不受影响。

## 给 AI 的转述块

给一个要新建/改造小程序仓的 AI 当引导词，整段粘贴即可：

```text
本项目界面使用 msui（共享 UI 运行时与样式，pywebview + WebView2）。约定如下：
1. 安装：requirements 里写一行钉版本 wheel URL（升级 = 只改版本号）：
   msui @ https://github.com/WangYiTao0/msui/releases/download/v0.2.0/msui-0.2.0-py3-none-any.whl
2. 页面（HTML/CSS/JS）放本仓 pages/ 目录。启动三步：page_dir() 定位页面目录
   （冻结态 sys._MEIPASS/pages，源码态在启动文件旁）→
   serve_dir = msui.resources.copy_assets(page_dir()) →
   msui.shell.run(serve_dir / "index.html", title="应用名")。开窗一律用
   copy_assets 的返回值。
3. 页面 <head> 依次相对引用 tokens.css、base.css。这两份不入仓、不手改，
   由 copy_assets 每次启动无条件覆盖落下（pages/.gitignore 排除它们）。
4. HTML 直接写语义化标签（button/input/table/a/h1…），不写自定义配色；任何
   颜色只允许 var(--token) 引用，禁止手写十六进制色值。
5. 换色（默认不需要）：pages/ 里加 override.css，只覆写 :root 里同名 token
   变量值，并在 base.css 之后 <link> 它。
6. 测试加两条样式闸门（照抄 msui README 的 test_style_gate.py）：
   contrast_failures 对比度 + scan_stray_hex 防游离色值。
7. PyInstaller spec 里对 msui 零资源配置（包自带 hook 收齐样式与元数据），
   datas 只写自己的 ("pages", "pages")。
8. 版本核对：copy_assets 落下的 css 第一行是 /* msui X.Y.Z */，据此核对产物
   带的 msui 版本。
```

## 发布（维护者）

版本号只写在 `pyproject.toml` 一处。发布：

```
git tag v<版本号> && git push origin v<版本号>
```

CI 在装依赖之前核对 tag 与 pyproject 版本一致（不一致当场 fail），跑测试，
构建 wheel，用自带 GITHUB_TOKEN 发到本仓 Release——零 PAT。发完后把上面
第 1 步安装行里的版本号改成新版。
