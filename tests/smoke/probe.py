"""冻结产物冒烟探针——最小消费者，走全链路：

装包 → `copy_assets` 把共享样式落到自己的页面目录 → 页面同目录相对路径
引用 → `msui.shell.run(hidden=True)` 真开窗（dogfooding，全程不上屏）→
`evaluate_js` 读 getComputedStyle 核对共享样式生效 → 销毁窗口退出。

同时钉死两条待验条款（在 Windows CI 的冻结产物里跑出答案）：

  ① 页面目录可写性——含窗口开着（css 已被 WebView2 加载）时的覆盖写；
  ② 冻结产物里 msui 版本元数据正确——不许是 0.0.0+unknown（macOS 曾观察到
     不写 copy-metadata 也拿到版本，那是未解之谜，不许依赖；这里以环境变量
     MSUI_EXPECTED_VERSION 给出的期望值硬性核对）。

输出约定：最后一行 ``SMOKE-RESULT {json}``（全部读数），失败清单非空则
退出码 1；watchdog 超时直接 os._exit(2)。所有 print 均 flush——冻结产物
stdout 重定向到 CI 日志时是块缓冲，不 flush 顺序会乱。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

import msui
from msui import resources
from msui.shell import run

TIMEOUT_SECONDS = 120
EXPECTED_VERSION_ENV = "MSUI_EXPECTED_VERSION"

# 期望读数——来源见注释；getComputedStyle 的色值序列化按 CSSOM 规范是
# "rgb(r, g, b)"，这里同时容忍 "rgba(r, g, b, 1)" 写法（去空白后比较）。
EXPECTED_BODY_BG = "#141417"  # tokens.css --win，经 base.css `body { background: var(--win) }`
EXPECTED_LINK_COLOR = "#60a5fa"  # tokens.css --info，经 base.css `a { color: var(--info) }`
EXPECTED_CONTROL_COLOR = "rgb(7, 130, 89)"  # 对照组 same.css 直写

results: dict[str, object] = {
    "frozen": bool(getattr(sys, "frozen", False)),
    "platform": sys.platform,
}
failures: list[str] = []


def check(name: str, ok: bool, detail: object) -> None:
    results[name] = detail
    if not ok:
        failures.append(f"{name}: {detail}")


def page_dir() -> Path:
    """探针自己的页面目录（消费者持有页面——出路二的前提）。

    冻结态在 `sys._MEIPASS/pages`（spec 里 `("pages", "pages")` 收进去的），
    源码态就是本文件旁边的 pages/。
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "pages"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / "pages"


def _norm_color(value: object) -> str:
    """把 getComputedStyle 色值归一成 'r,g,b' 便于比较。"""
    text = str(value).strip().lower().replace(" ", "")
    for prefix in ("rgba(", "rgb("):
        if text.startswith(prefix):
            channels = text[len(prefix):].rstrip(")").split(",")
            return ",".join(channels[:3])
    return text


def _hex_to_channels(hex_color: str) -> str:
    raw = hex_color.lstrip("#")
    return ",".join(str(int(raw[i : i + 2], 16)) for i in (0, 2, 4))


def on_ready(window) -> None:  # noqa: ANN001 - pywebview Window，探针不引类型
    try:
        for _ in range(200):
            if window.evaluate_js("document.readyState") == "complete":
                break
            time.sleep(0.1)
        else:
            failures.append("page_load: readyState 一直没到 complete")

        body_bg = window.evaluate_js(
            "getComputedStyle(document.body).backgroundColor"
        )
        link_color = window.evaluate_js(
            "getComputedStyle(document.getElementById('probe-link')).color"
        )
        control_color = window.evaluate_js(
            "getComputedStyle(document.getElementById('control')).color"
        )
        check(
            "computed_body_bg",
            _norm_color(body_bg) == _hex_to_channels(EXPECTED_BODY_BG),
            body_bg,
        )
        check(
            "computed_link_color",
            _norm_color(link_color) == _hex_to_channels(EXPECTED_LINK_COLOR),
            link_color,
        )
        # 对照组：读不到它 = 探针自己坏了，与共享样式无关
        check(
            "computed_control_color",
            _norm_color(control_color) == _norm_color(EXPECTED_CONTROL_COLOR),
            control_color,
        )

        # 待验条款①的硬核部分：窗口开着、css 已被 WebView2 加载的状态下覆盖写。
        # 先写坏再 copy_assets，读回内容 == 包内原件，证明覆盖真的发生了
        # （不然「覆盖同样内容」分辨不出写没写进去）。
        target = page_dir() / resources.TOKENS_CSS_NAME
        try:
            target.write_text("/* stale-while-open */", encoding="utf-8")
            resources.copy_assets(page_dir())
            overwritten = target.read_text(
                encoding="utf-8"
            ) == resources.tokens_css_path().read_text(encoding="utf-8")
            check("overwrite_while_open", overwritten, "ok" if overwritten else "内容没换过来")
        except OSError as exc:
            check("overwrite_while_open", False, f"OSError: {exc}")
    except Exception:  # noqa: BLE001 - 探针要把任何炸法都带出窗口报出来
        failures.append("on_ready 崩了：\n" + traceback.format_exc())
    finally:
        window.destroy()


def main() -> int:
    watchdog = threading.Timer(
        TIMEOUT_SECONDS,
        lambda: (print("SMOKE-FAIL: watchdog 超时", flush=True), os._exit(2)),
    )
    watchdog.daemon = True
    watchdog.start()

    # 待验条款②：版本元数据。冻结产物里不许是 0.0.0+unknown——那说明
    # hook 的 copy_metadata 没生效，下游按版本戳的缓存清理会全部失灵。
    version = msui.get_version()
    check("version", "unknown" not in version, version)
    expected_version = os.environ.get(EXPECTED_VERSION_ENV)
    if expected_version:
        check("version_matches_expected", version == expected_version, version)

    # Windows 上先确保 WebView2 就绪（dogfooding；runner 镜像通常自带，缺了就引导装）
    if sys.platform == "win32":
        from msui.webview2 import ensure_webview2

        ensure = ensure_webview2()
        check(
            "webview2_ready",
            ensure.ok,
            f"ok={ensure.ok} installed_now={ensure.installed_now} error={ensure.error}",
        )
        if not ensure.ok:
            print("SMOKE-RESULT " + json.dumps({"failures": failures, **results}, ensure_ascii=False), flush=True)
            return 1

    # 待验条款①（静态半）：把共享样式落进页面目录——冻结产物的页面目录必须可写
    pd = page_dir()
    served = resources.copy_assets(pd)
    check("copy_assets_returned_page_dir", served == pd, str(served))
    for name in resources.ASSET_NAMES:
        check(f"copied_{name}", (pd / name).is_file(), str(pd / name))

    # 验收 7：复制不动原件——Python 侧资源读取在冻结产物里仍正常
    tokens_path = resources.tokens_css_path()
    check(
        "python_side_tokens_readable",
        tokens_path.is_file() and tokens_path.parent != pd,
        str(tokens_path),
    )
    tokens = resources.parse_tokens(tokens_path.read_text(encoding="utf-8"))
    check("python_side_brand_token", tokens.get("brand") == "#db021d", tokens.get("brand"))

    # 真开窗（隐藏，全程不上屏），后台线程里读数并销毁
    run(
        pd / "index.html",
        title="msui-smoke-probe",
        hidden=True,
        on_ready=on_ready,
    )

    print(
        "SMOKE-RESULT " + json.dumps({"failures": failures, **results}, ensure_ascii=False),
        flush=True,
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
