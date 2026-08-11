"""冻结产物冒烟探针——最小消费者，走全链路：

装包 → `copy_assets` 把共享样式落到自己的页面目录 → 页面同目录相对路径
引用 → `msui.shell.run(hidden=True)` 真开窗（dogfooding，全程不上屏）→
`evaluate_js` 读 getComputedStyle 核对共享样式生效 → 销毁窗口退出。

同时钉死三条待验条款（在 Windows CI 的冻结产物里跑出答案）：

  ① 页面目录可写性——含窗口开着（css 已被 WebView2 加载）时的覆盖写；
  ② 冻结产物里 msui 版本元数据正确——不许是 0.0.0+unknown（macOS 曾观察到
     不写 copy-metadata 也拿到版本，那是未解之谜，不许依赖；这里以环境变量
     MSUI_EXPECTED_VERSION 给出的期望值硬性核对）；
  ③ 单实例守卫在**冻结产物**里真的管用（票 12）——命名 mutex 走的是 ctypes
     直调 kernel32，PyInstaller 冻结后 ctypes/api-ms-* 那套依赖是否齐全只有
     真产物答得出。做法是真双开：窗口开着（锁持有中）时 spawn 一份自己，
     副本必须打出 BLOCKED 并自己退出。

输出约定：最后一行 ``SMOKE-RESULT {json}``（全部读数），失败清单非空则
退出码 1；watchdog 超时直接 os._exit(2)。所有 print 均 flush——冻结产物
stdout 重定向到 CI 日志时是块缓冲，不 flush 顺序会乱。
"""
from __future__ import annotations

import json
import os
import subprocess
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

# 单实例守卫的 id（消费者侧就是 miniprog.toml 的 id）与「我是副本」的开关。
# 副本模式靠环境变量而不是命令行参数：冻结产物的 argv 要经 bootloader，
# 环境变量这条路两种形态（源码/onedir）完全一致。
SINGLE_INSTANCE_ID = "msui-smoke-probe"
SECOND_INSTANCE_ENV = "MSUI_SECOND_INSTANCE"
SECOND_INSTANCE_TIMEOUT = 60

# Windows 控制台默认 cp1252，本探针输出带中文——自己把 stdout/stderr 掰成
# UTF-8，不指望调用方记得设 PYTHONUTF8（errors="replace" 保底：宁可读数里
# 出问号，不许探针因为打印这一步炸掉）。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

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


def second_instance_main() -> int:
    """副本模式：同 id 再 run 一次，把守卫的判定打成一行标记。

    - 守卫拦住 → `run` 直接返回，on_ready 从没被触发 → 打 `BLOCKED`；
    - 守卫没拦住 → 窗口真开起来了，立刻销毁并打 `OPENED`（= 双开实测失败）。

    退出码一律 0：副本的结论靠输出标记传递，主探针据此判定。副本自己崩掉
    才会是非零——那也是主探针要报出来的信息。
    """
    opened: list[bool] = []

    def on_ready_second(window) -> None:  # noqa: ANN001
        opened.append(True)
        window.destroy()

    run(
        page_dir() / "index.html",
        title="msui-smoke-probe",
        hidden=True,
        single_instance=SINGLE_INSTANCE_ID,
        on_ready=on_ready_second,
    )
    print("SECOND-INSTANCE " + ("OPENED" if opened else "BLOCKED"), flush=True)
    return 0


def _spawn_second_instance() -> subprocess.CompletedProcess:
    """起一份自己当第二实例。冻结态 sys.executable 就是 probe.exe 本身。"""
    argv = [sys.executable]
    if not getattr(sys, "frozen", False):
        argv.append(str(Path(__file__).resolve()))
    env = {**os.environ, SECOND_INSTANCE_ENV: "1"}
    return subprocess.run(
        argv,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=SECOND_INSTANCE_TIMEOUT,
    )


def on_ready(window) -> None:  # noqa: ANN001 - pywebview Window，探针不引类型
    results["on_ready_ran"] = True
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
        # 先写坏再 copy_assets，读回内容 == 版本横幅 + 包内原件，证明覆盖真的
        # 发生了（不然「覆盖同样内容」分辨不出写没写进去）。
        target = page_dir() / resources.TOKENS_CSS_NAME
        try:
            target.write_text("/* stale-while-open */", encoding="utf-8")
            resources.copy_assets(page_dir())
            expected = resources.version_banner() + resources.tokens_css_path().read_text(
                encoding="utf-8"
            )
            overwritten = target.read_text(encoding="utf-8") == expected
            check("overwrite_while_open", overwritten, "ok" if overwritten else "内容没换过来")
        except OSError as exc:
            check("overwrite_while_open", False, f"OSError: {exc}")

        # 待验条款③：双开实测。此刻窗口开着、锁在本进程手里，起一份自己——
        # 副本必须被守卫拦下（BLOCKED）。放在 on_ready 里就是为了「锁确实
        # 正被持有」这个前提成立；跑在窗口销毁之后的话，测的就成了空气。
        try:
            second = _spawn_second_instance()
            blocked = "SECOND-INSTANCE BLOCKED" in second.stdout
            check(
                "second_instance_blocked",
                blocked,
                f"rc={second.returncode} out={second.stdout.strip()[-200:]!r}"
                f" err={second.stderr.strip()[-200:]!r}",
            )
        except subprocess.TimeoutExpired:
            # 副本没在预算内退出 = 守卫没拦住又卡在主循环里，这本身就是失败。
            check("second_instance_blocked", False, "副本超时未退出")
    except Exception:  # noqa: BLE001 - 探针要把任何炸法都带出窗口报出来
        failures.append("on_ready 崩了：\n" + traceback.format_exc())
    finally:
        window.destroy()


def main() -> int:
    if os.environ.get(SECOND_INSTANCE_ENV) == "1":
        return second_instance_main()

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

    # 版本标记：落出去的 css 第一行就是 `/* msui X.Y.Z */`——冻结产物的
    # 文件系统里直接可读，值必须与元数据版本一致（单一来源）。
    banner_line = (pd / resources.TOKENS_CSS_NAME).read_text(encoding="utf-8").splitlines()[0]
    check("version_banner", banner_line == f"/* msui {version} */", banner_line)

    # 复制不动原件——Python 侧资源读取在冻结产物里仍正常
    tokens_path = resources.tokens_css_path()
    check(
        "python_side_tokens_readable",
        tokens_path.is_file() and tokens_path.parent != pd,
        str(tokens_path),
    )
    tokens = resources.parse_tokens(tokens_path.read_text(encoding="utf-8"))
    check("python_side_brand_token", tokens.get("brand") == "#db021d", tokens.get("brand"))

    # 真开窗（隐藏，全程不上屏），后台线程里读数并销毁。守卫开着——本进程
    # 是第一实例，必须照常开窗；副本由 on_ready 里的双开实测负责。
    run(
        pd / "index.html",
        title="msui-smoke-probe",
        hidden=True,
        single_instance=SINGLE_INSTANCE_ID,
        on_ready=on_ready,
    )

    # 「窗口根本没开起来」与「开了、读数全绿」在 failures 上是同一个形状
    # （空清单）。不单独判这一条，守卫误拦、开窗直接失败都会静静地报绿。
    check("on_ready_ran", bool(results.get("on_ready_ran")), results.get("on_ready_ran"))

    print(
        "SMOKE-RESULT " + json.dumps({"failures": failures, **results}, ensure_ascii=False),
        flush=True,
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
