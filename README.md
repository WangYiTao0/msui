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
msui @ https://github.com/WangYiTao0/msui/releases/download/v0.4.0/msui-0.4.0-py3-none-any.whl
```

另外两个工具的去处按宿主平台的接入契约分工：**`pyinstaller` 也进
`requirements.txt`**（平台 CI 的 Install deps 步只装 requirements.txt，
打包就要用它——这是接入契约的要求，不是本仓的偏好）；`pytest` 不进
requirements——平台 CI 在测试步内现装，本机开发时装一次：

```
pip install pytest
```

## 2. 最小启动

页面（HTML/CSS/JS）放自己仓的 `pages/` 目录；启动三步——定位页面目录、
`copy_assets` 落共享样式、`run` 开窗：

```python
# examples/minimal/app.py
"""msui 最小消费者：页面归自己，共享样式由 msui 启动时落进来。

三步：定位页面目录 → copy_assets 落共享样式 → run 开窗。
页面要调 Python 时把 js_api 对象递给 run（方法包 Serializer：连点丢弃、
不排队），页面那半边的写法见 pages/index.html 尾部的 <script>。
环境变量 APP_SMOKE=1 时隐藏开窗、SmokeDriver 自动驾驶一轮（等桥往返、
核对样式真的生效、横幅钉住版本）后自关——给 CI/无人值守冒烟用；自己的仓
不需要冒烟的话，把 make_smoke_script 和 driver 相关几行删掉即可。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from msui.bridge import Serializer
from msui.resources import copy_assets
from msui.shell import run
from msui.testing import SmokeDriver

# 本仓钉死的 msui 版本，与 requirements 里 wheel URL 的版本号一致，升级
# msui 时两处一起改。冒烟据此断言横幅——钉死常量证明「产物带的确实是钉的
# 这一版」；改读 importlib.metadata 只是回显装了哪版、永远绿，证明不了钉住。
MSUI_PINNED = "0.4.0"


class Api:
    """js_api 桥对象：业务留在 Python，页面只管调用与显示。

    pywebview 对每次前端调用各开一个后台线程（官方文档明说 not
    thread-safe），方法一律包在 Serializer 里：抢不到锁立即回
    {"busy": True, ...}，绝不排队——连点五下不会攒成一队。
    """

    def __init__(self) -> None:
        self._serial = Serializer()

    def ping(self) -> dict:
        """页面调一次拿一句应答：{"busy": False, "data": "pong 来自 Python"}。"""
        return self._serial.run(lambda: "pong 来自 Python")


def page_dir() -> Path:
    """页面目录：冻结态在 _MEIPASS/pages（app.spec 收进去的），源码态在本文件旁。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "pages"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / "pages"


def make_smoke_script(serve_dir: Path):
    """造冒烟脚本（跑在 pywebview 后台线程）：桥往返、样式生效、版式地基、横幅钉版。

    失败收集、finally 销毁窗口、超时兜底都由 SmokeDriver 骨架代办。页面探针
    一律写成 null-safe（先判 querySelector 结果再取样式）：元素缺席时报出的
    是「missing」而不是烧满轮询预算后的一串异常文本。
    """

    def smoke_script(drive: SmokeDriver, window) -> None:
        # 桥通：页面在 pywebviewready 后自动 ping 一次，回显来自 Python 的应答
        got = drive.wait_js(
            window, "document.getElementById('pong').textContent", "pong 来自 Python"
        )
        drive.check(got == "pong 来自 Python", f"桥往返回显不对：{got!r}")
        # 样式吃进去了：主按钮实测背景色 == --brand token 解出的 rgb
        drive.check_token_style(window, "button.primary", "backgroundColor", "brand")
        # 版式地基生效：内容不贴窗框（body 非零内边距）、大读数居中吃 48px 档
        pad = drive.wait_js(window, "getComputedStyle(document.body).paddingLeft", "24px")
        drive.check(pad == "24px", f"body 左内边距该是 24px（--space-5），实测 {pad!r}")
        readout = drive.wait_js(
            window,
            "(() => { const el = document.querySelector('.display');"
            " if (!el) return 'missing'; const d = getComputedStyle(el);"
            " return d.textAlign + ' ' + d.fontSize; })()",
            "center 48px",
        )
        drive.check(readout == "center 48px", f".display 该居中吃 48px 档，实测 {readout!r}")
        # 横幅钉版：落地 css 第一行 == "/* msui <钉的版本> */"。横幅只证明
        # css 落了地，「页面吃进去了」由上面 check_token_style 证明，两条各管一半。
        banner = (serve_dir / "tokens.css").read_text(encoding="utf-8").splitlines()[0]
        drive.check(
            banner == f"/* msui {MSUI_PINNED} */",
            f"tokens.css 横幅该是 '/* msui {MSUI_PINNED} */'，实测 {banner!r}",
        )

    return smoke_script


def main() -> None:
    serve_dir = copy_assets(page_dir())  # 每次启动覆盖落样式，页面永远跟着装的这版 msui 走
    smoke = os.environ.get("APP_SMOKE") == "1"
    driver = SmokeDriver(make_smoke_script(serve_dir)) if smoke else None
    run(
        serve_dir / "index.html",
        js_api=Api(),
        title="示例小程序",
        hidden=driver is not None,
        on_ready=driver,
    )
    if driver is not None:
        driver.exit()  # 有失败：逐条打印后退出码 1；全绿：打印「冒烟通过」


if __name__ == "__main__":
    main()
```

要点：

- `copy_assets` **无条件覆盖**地把 `tokens.css` + `base.css` 落进页面目录并返回
  该开窗的目录——开窗一律用返回值，别写死 `page_dir`；
- 这两份 css 不入仓、不手改（`pages/.gitignore` 把它们排除掉）；
- 钉版本的官方姿势就是上面的 `MSUI_PINNED` 常量 + 横幅断言：**钉死常量证明
  「产物带的确实是钉的这一版」，改读 `importlib.metadata` 只是回显装了哪版、
  永远绿**——升级 msui 时改两处（requirements 的 wheel URL + 这个常量），
  冒烟红了就是有一处忘了改；
- `run(...)` 还收 `width/height/min_size`、`icon=`、`storage_dir=` +
  `version=`（持久化与按版本清缓存）等关键字参数，按需加。

### 桥的页面侧：三件事

上面 Python 那半边只是把 `js_api=Api()` 递给 `run`、方法包上
`msui.bridge.Serializer`；页面那半边（完整代码在下一节 index.html 尾部的
`<script>` 里，可整段照抄）只有三件事：

1. **等 `pywebviewready` 再调**——`window.pywebview` 是窗口起来后才注入的，
   页面脚本一执行就去调必然 undefined；把首次调用挂在
   `window.addEventListener("pywebviewready", …)` 上。
2. **调用返回 Promise**——`window.pywebview.api.ping()` 这样调，`await` 拿到
   的就是 Python 方法的返回值（必须 JSON 可序列化）。Python 侧抛异常会变成
   这个 Promise 的 reject，前端 try/catch 兜底显示。
3. **忙碌信封就地丢弃**——方法包了 `Serializer` 时，应答统一是
   `{"busy": false, "data": …}` 信封；拿到 `busy: true` 表示上一次调用还在
   处理中，**就地 `return` 丢弃本次、绝不排队**（排队会把「连点五下」攒成
   执行五次）。

## 3. 页面写语义 HTML

新页面不从空白起步——先抄这份**标准单列页骨架**。容器约定：**body 就是
容器**（边距、内容列宽 `--content-max`、垂直节奏全由 base.css 落在 body 上，
不存在也不需要 `.page` 之类的容器类；裸语义 HTML 零 class 就有边距与节奏）：

```html
<!-- examples/minimal/pages/skeleton.html -->
<!DOCTYPE html>
<!--
  标准单列页骨架：新页面从这几行起步，不写一行版式 CSS。
  容器约定：**body 就是容器**——边距、内容列宽（--content-max）、垂直节奏
  全由 base.css 落在 body 上；不存在也不需要 .page 之类的容器类，裸语义
  HTML 零 class 就有边距与节奏。.display 挂在主角读数上（增强，不是必需），
  没有主角读数的页面删掉那一行即可。
-->
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>应用名</title>
  <link rel="stylesheet" href="tokens.css">
  <link rel="stylesheet" href="base.css">
</head>
<body>
  <h1>应用名</h1>
  <p>一句话说明这个小工具是干什么的。</p>
  <output class="display">0</output>
  <div class="card">
    <button class="primary">主操作</button>
    <button>次要操作</button>
  </div>
</body>
</html>
```

写裸 `button` / `input` / `table` / `a` / `h1` 就得到统一长相；任何颜色只经
`var(--token)` 取用，**不许手写十六进制色值**（第 5 步的闸门盯着）。完整
示例（骨架长开之后的样子，带桥调用）：

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
  <p>下面全是裸标签：没有写任何一行自定义样式，长相与版式（边距、垂直节奏、
    居中的大读数）全来自共享的 base.css。</p>
  <output class="display">42</output>
  <div class="card">
    <h2>操作区</h2>
    <input placeholder="输入点什么">
    <button class="primary">主操作</button>
    <button>次要操作</button>
  </div>
  <div class="card">
    <h2>桥演示</h2>
    <p>点按钮经 js_api 桥调 Python，应答回显在这里：
      <output id="pong">（等待 pywebviewready）</output></p>
    <button id="ping">调一下 Python</button>
  </div>
  <table>
    <thead><tr><th>名称</th><th>状态</th></tr></thead>
    <tbody>
      <tr><td>任务一</td><td>已完成</td></tr>
      <tr><td>任务二</td><td>进行中</td></tr>
    </tbody>
  </table>
  <small>底部弱化文字，带一个<a href="#">链接</a>。</small>
  <script>
    // 桥的页面侧三件事（详见 README「桥的页面侧」一节）：
    // 1. pywebviewready 之后才允许调用（js_api 注入完成的信号）；
    // 2. window.pywebview.api.xxx() 返回 Promise，await 拿 Python 返回值；
    // 3. 应答是 Serializer 信封，busy=true 表示上一次还在处理——就地丢弃。
    const pongEl = document.getElementById("pong");
    async function ping() {
      const reply = await window.pywebview.api.ping();
      if (reply.busy) return; // 忙碌信封：丢弃本次，不排队
      pongEl.textContent = reply.data;
    }
    document.getElementById("ping").addEventListener("click", ping);
    window.addEventListener("pywebviewready", ping);
  </script>
</body>
</html>
```

展示型大读数（计数器、倒计时这类页面的主角数字）给承载元素挂 `.display`
类：成块居中、字号走 tokens 的 `--font-display` 档（48px）、数字等宽不晃动、
上下自带一档内衬，照样零自定义样式。

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

# 开发机上冒烟落地过的 tokens.css / base.css 副本（gitignored、但在盘上）
# 会被 pages/ 整目录收集顺手带进产物——纯冗余：运行时 copy_assets 每次启动
# 都无条件覆盖，产物里那两份副本永远不会被用到。按目的地路径剔掉；CI 的
# 干净 checkout 本来就没有它们，此过滤不改变 CI 产物。
def _is_landed_css(dest: str) -> bool:
    parts = dest.replace("\\", "/").split("/")
    return parts[0] == "pages" and parts[-1] in ("tokens.css", "base.css")

a.datas = [entry for entry in a.datas if not _is_landed_css(entry[0])]

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

打包与冒烟（不上屏）。打包命令两平台一样，冒烟按平台各一行：

```
pyinstaller examples/minimal/app.spec --noconfirm --distpath dist --workpath build
```

```powershell
# Windows（PowerShell）——正式目标平台
$env:APP_SMOKE = "1"; .\dist\app\app.exe
```

```sh
# macOS / Linux——开发机预演用
APP_SMOKE=1 ./dist/app/app
```

冒烟的自动驾驶骨架是 `msui.testing.SmokeDriver`（上面 app.py 的 APP_SMOKE
分支就是全部用法），它替你扛下四件容易踩坑的事：`on_ready` 跑在 pywebview
后台线程、**异常不会变成非零退出码**，所以失败一律收集、`run()` 返回后
`driver.exit()` 统一判定；桥往返是异步的，用 `wait_js` 轮询等到位；窗口
销毁在 finally 里，脚本怎么炸都不挂死；外加 watchdog 硬闹钟兜底（默认
120 秒，到点 `os._exit(2)`）。样式生效断言用 `check_token_style`（见下节）。

`wait_js` 两条行为要知道：页面探针表达式抛异常（典型：`querySelector` 返回
null 被直接 `getComputedStyle`）时**不中断整场**——异常文本当结果值返回，
那条 check 正常报「实测=<异常文本>」，剩余断言照跑；整个冒烟脚本共用一个
超时预算，**注定等不到的期望会烧满剩余预算才放行**（失败路径变慢是设计
使然，不为失败开小灶）——所以探针尽量写成 null-safe（照上面 `.display`
那段先判元素再取样式），元素缺席时报出的是 `missing` 而不是一串异常文本。

msui 落进来的两份样式副本要挡在 git 外——`pages/.gitignore` 写这两行
（仓里的唯一样式来源是 msui 包，副本入了仓就是漂移源）：

```
tokens.css
base.css
```

## 版本标记：产物里读得出带的是哪版 msui

`copy_assets` 落出去的每份 css 第一行是版本横幅 `/* msui X.Y.Z */`，值取包
自身安装元数据（单一来源，无第二份版本号）：

- **产物文件系统**：`head -1 pages/tokens.css` 直接读出；
- **页面 devtools**：Sources 面板打开 tokens.css，第一行就是。

横幅是 css 注释：tokens 解析整块剔注释、横幅里没有色值，样式闸门不受影响。

两级证明要分清：**横幅只证明 css 落了地**（文件在、版本对），不证明页面
把它吃进去了（`<link>` 被删、路径写错时横幅照样在）。「页面真的吃进去了」
用冒烟里的 `SmokeDriver.check_token_style` 断言：把某个 token 解成 rgb、与
元素实测 computedStyle 比对——砍掉 base.css 的 `<link>` 时它必红。两条各管
一半，都要有。

## 给 AI 的转述块

给一个要新建/改造小程序仓的 AI 当引导词，整段粘贴即可：

```text
本项目界面使用 msui（共享 UI 运行时与样式，pywebview + WebView2）。约定如下：
1. 安装：requirements 里写一行钉版本 wheel URL（升级 = 只改版本号）：
   msui @ https://github.com/WangYiTao0/msui/releases/download/v0.4.0/msui-0.4.0-py3-none-any.whl
   另加一行 pyinstaller（宿主平台接入契约要求它进 requirements，CI 打包
   要用）；pytest 不进 requirements，CI 测试步内现装。
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
8. 版本核对：copy_assets 落下的 css 第一行是 /* msui X.Y.Z */。冒烟里定义
   常量 MSUI_PINNED（与 requirements 的 wheel URL 版本一致，升级时两处一起
   改）并断言横幅 == "/* msui <MSUI_PINNED> */"——钉死常量证明产物带的是
   钉的这一版，不改读 importlib.metadata（那只是回显、永远绿）。
9. 页面调 Python（js_api 桥）：Python 侧对象方法包 msui.bridge.Serializer
   （忙碌信封，连点丢弃不排队）；页面侧等 pywebviewready 事件后经
   window.pywebview.api.xxx() 调用（返回 Promise），应答 busy=true 就地丢弃。
10. 冒烟自动驾驶用 msui.testing.SmokeDriver（照抄 msui README §2 的
    APP_SMOKE 分支）：失败收集与退出码判定、finally 销毁窗口、watchdog
    超时兜底都由它代办；样式生效断言用它的 check_token_style（token 解成
    rgb 与元素实测 computedStyle 比对）。
11. 展示型大读数（计数器主角数字这类）给元素挂 .display 类：成块居中、
    字号走 --font-display 档（48px），不自己写字号、不自己居中。
12. 版式零决策：body 就是容器——边距、内容列宽、垂直节奏由 base.css 落在
    body 上，没有 .page 容器类；新页面从 msui README §3 的「标准单列页
    骨架」可抄块起步，不写任何版式 CSS，间距要自取时用 --space-1…6 档。
```

## 发布（维护者）

版本号只写在 `pyproject.toml` 一处。发布：

```
git tag v<版本号> && git push origin v<版本号>
```

CI 在装依赖之前核对 tag 与 pyproject 版本一致（不一致当场 fail），跑测试，
构建 wheel，用自带 GITHUB_TOKEN 发到本仓 Release——零 PAT。发完后把上面
第 1 步安装行里的版本号改成新版。
