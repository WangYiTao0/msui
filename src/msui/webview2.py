"""WebView2 运行时检测与引导安装。

**最危险的一条**：pywebview 在 Windows 上缺 WebView2 Runtime 时**不报错**——
它会静默走到别的渲染引擎分支，只打一条 warning 日志，用户看到的不是报错框，
是一个样式稀碎的窗口。指望 pywebview 自己抛异常是不成立的，检测责任必须自己担。

**纪律**：这个模块自己**绝不** `import webview`、**绝不**调 `webview.start`——
它只回答"WebView2 有没有装好"，装没装完是调用方的决定权。`is_webview2_installed` /
`ensure_webview2` 返回的是纯数据结构，调用方拿到 `EnsureResult(ok=False, ...)`
之后要不要仍然尝试开窗、要不要退出、要不要弹什么提示，一概不归这里管。

## 检测：注册表 `pv` 键三处位置

出处是 Microsoft Learn 的官方页面（<https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution>，
"Detect if a WebView2 Runtime is already installed" 一节），GUID 是 WebView2
Runtime 在 EdgeUpdate 下的 Client ID：

  - 64 位 Windows 的 per-machine 位置（32-on-64 重定向视图）：
    ``HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{GUID}``
  - 32 位 Windows 的 per-machine 位置（原生视图；64 位 Windows 上用
    `KEY_WOW64_64KEY` 打开也是这个路径——per-machine 的第二处 WOW 变体）：
    ``HKLM\\SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{GUID}``
  - per-user 位置（两种位数的 Windows 上路径相同）：
    ``HKCU\\Software\\Microsoft\\EdgeUpdate\\Clients\\{GUID}``

三处任一处的 `pv (REG_SZ)` 值非空、且不等于 `"0.0.0.0"`，即视为已装
（官方原话："a version greater than 0.0.0.0"；键缺失/值为 null/空串/0.0.0.0
三种情况官方并列为"未安装"）。

## 引导：Evergreen Bootstrapper

`BOOTSTRAPPER_URL` 是官方"Get the Link"按钮给出的固定重定向链接
（<https://developer.microsoft.com/microsoft-edge/webview2#download-the-webview2-runtime>），
实测会 301 到 `msedge.sf.dl.delivery.mp.microsoft.com` 下的
`MicrosoftEdgeWebview2Setup.exe`。跑法是官方文档给的原话：

    MicrosoftEdgeWebview2Setup.exe /silent /install

非提权进程跑它就是 per-user 安装、不弹 UAC（官方原话："If you don't run the
command from an elevated process or command prompt, a per-user install will
take place"）——标准用户即可，不做任何提权尝试。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

__all__ = [
    "BOOTSTRAPPER_FILENAME",
    "BOOTSTRAPPER_URL",
    "ERR_DOWNLOAD_FAILED",
    "ERR_INSTALL_FAILED",
    "ERR_STILL_MISSING",
    "MANUAL_INSTALL_URL",
    "REGISTRY_LOCATIONS",
    "WEBVIEW2_CLIENT_GUID",
    "BootstrapperDownloadError",
    "BootstrapperDownloader",
    "EnsureResult",
    "InstallerRunner",
    "RegistryReader",
    "WebView2Error",
    "download_bootstrapper_default",
    "ensure_webview2",
    "is_webview2_installed",
    "read_registry_pv_default",
    "run_installer_default",
]

# WebView2 Runtime 在 EdgeUpdate 下的 Client ID（Microsoft Learn 原文常量，
# 跨版本不变——它标识"WebView2 Runtime 这个产品"，不是某个版本号）。
WEBVIEW2_CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

# (hive, subkey) 三元组；hive 只有 "HKLM" / "HKCU" 两种取值，真实读取时
# 映射到 winreg 的 HKEY_LOCAL_MACHINE / HKEY_CURRENT_USER。
REGISTRY_LOCATIONS: tuple[tuple[str, str], ...] = (
    ("HKLM", f"SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{WEBVIEW2_CLIENT_GUID}"),
    ("HKLM", f"SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{WEBVIEW2_CLIENT_GUID}"),
    ("HKCU", f"Software\\Microsoft\\EdgeUpdate\\Clients\\{WEBVIEW2_CLIENT_GUID}"),
)

# Evergreen Bootstrapper 的官方固定下载链接（"Get the Link"按钮给出的那条）。
BOOTSTRAPPER_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
BOOTSTRAPPER_FILENAME = "MicrosoftEdgeWebview2Setup.exe"

# 引导全部失败时给用户的手动安装页——WebView2 Runtime 官方消费者下载页。
MANUAL_INSTALL_URL = "https://developer.microsoft.com/microsoft-edge/webview2/consumer/"

# 中性 User-Agent：这条会随下载请求真的发到微软的服务器，不带任何账号/仓库信息。
_USER_AGENT = "msui-webview2-bootstrapper/0.1"
_DOWNLOAD_TIMEOUT_SECONDS = 30.0
# 静默安装比下载慢得多（要真的装完整个 Runtime），给足余量。
_INSTALL_TIMEOUT_SECONDS = 180.0


# ---------------------------------------------------------------------------
# 可注入的三个函数：注册表读取 / 下载 / 跑安装器子进程
# ---------------------------------------------------------------------------


class RegistryReader(Protocol):
    """给一个 hive 名（``"HKLM"``/``"HKCU"``）与 subkey 路径，返回 `pv` 值。

    键不存在、或读取失败，一律返回 None——不抛异常（"缺失"本身就是正常结果
    之一，不是错误）。
    """

    def __call__(self, hive: str, subkey: str) -> str | None: ...


class BootstrapperDownloader(Protocol):
    """把 `url` 的内容下载写到 `target` 路径；下载不成功抛 `BootstrapperDownloadError`。"""

    def __call__(self, url: str, target: Path) -> None: ...


class InstallerRunner(Protocol):
    """跑一条安装器命令，返回退出码。

    实现方**不抛异常**——连子进程都起不来（找不到可执行文件之类）也归一化成
    一个非零退出码，调用方（`ensure_webview2`）只看退出码是否为 0。
    """

    def __call__(self, command: Sequence[str]) -> int: ...


class BootstrapperDownloadError(Exception):
    """引导安装程序下载失败。`BootstrapperDownloader` 实现应把网络异常包成这个类型。"""


def read_registry_pv_default(hive: str, subkey: str) -> str | None:
    """真实注册表读取：只在 Windows 上生效，其余平台直接返回 None。

    `import winreg` 放在 `sys.platform` 判断之后——Mac/Linux 上没有这个模块，
    先判平台再 import 才能让本模块在 Mac 上全量可测（Mac 上跑的全是注入的假
    reader，这个函数本身永远不会被调用到 import 那一行）。
    """
    if sys.platform != "win32":
        return None

    import winreg

    root = winreg.HKEY_LOCAL_MACHINE if hive == "HKLM" else winreg.HKEY_CURRENT_USER
    try:
        with winreg.OpenKey(root, subkey) as key:
            value, _ = winreg.QueryValueEx(key, "pv")
    except OSError:
        # 键不存在 / 没权限 —— 都算"这个位置没有"，不是程序错误。
        return None
    return str(value)


def download_bootstrapper_default(url: str, target: Path) -> None:
    """真实下载：标准库 urllib。"""
    request = urllib.request.Request(  # noqa: S310 - url 是模块常量 BOOTSTRAPPER_URL，非外部输入
        url, headers={"User-Agent": _USER_AGENT}
    )
    try:
        with (
            urllib.request.urlopen(  # noqa: S310 - url 是模块常量 BOOTSTRAPPER_URL，非外部输入
                request, timeout=_DOWNLOAD_TIMEOUT_SECONDS
            ) as response,
            open(target, "wb") as fh,
        ):
            shutil.copyfileobj(response, fh)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        raise BootstrapperDownloadError(str(exc)) from exc


def run_installer_default(command: Sequence[str]) -> int:
    """真实子进程调用：跑 bootstrapper 的 `/silent /install`。

    非提权进程跑它就是 per-user 安装、不弹 UAC——不做任何提权处理（`shell=False`，
    `creationflags` 全默认）。
    """
    try:
        completed = subprocess.run(  # noqa: S603 - command 由本模块拼装，参数是模块常量
            list(command),
            timeout=_INSTALL_TIMEOUT_SECONDS,
            check=False,
        )
    except OSError:
        # 连起都起不来（比如文件被杀软删了）—— 归一化成非零退出码，
        # 调用方不需要多分辨一种"安装器压根没跑起来"的异常类型。
        return -1
    return completed.returncode


# ---------------------------------------------------------------------------
# 检测
# ---------------------------------------------------------------------------


def is_webview2_installed(*, read_registry: RegistryReader = read_registry_pv_default) -> bool:
    """三处 `pv` 键位置任一处有非空非 "0.0.0.0" 的值，就算已装。

    `read_registry` 可注入：真实实现只在 Windows 生效，Mac 上测试全部传入
    桩函数（`REGISTRY_LOCATIONS` 的三处位置各自可测，见本模块的测试文件）。
    """
    for hive, subkey in REGISTRY_LOCATIONS:
        value = read_registry(hive, subkey)
        if value and value != "0.0.0.0":  # noqa: S104 - 版本哨兵值，不是网络绑定地址
            return True
    return False


# ---------------------------------------------------------------------------
# 引导
# ---------------------------------------------------------------------------

# error.kind 的三个取值，对应三条失败路径。
ERR_DOWNLOAD_FAILED = "webview2_download_failed"
ERR_INSTALL_FAILED = "webview2_install_failed"
ERR_STILL_MISSING = "webview2_still_missing"

_RETRY_SUFFIX = f"也可以手动下载安装：{MANUAL_INSTALL_URL}"


@dataclass(frozen=True)
class WebView2Error:
    """`ensure_webview2` 失败时的结构化错误。

    `kind` 给代码判断（三选一，见 ERR_* 常量）；`message` 是给业务用户看的
    人话——不甩英文异常原文，末尾总带手动安装链接。
    """

    kind: str
    message: str


@dataclass(frozen=True)
class EnsureResult:
    """`ensure_webview2` 的结果。

    `ok=True` 时可以放心让壳继续走下去；`ok=False` 时 `error` 非 None。
    要不要因此拦下"进 pywebview 壳"这个动作，是**调用方**的决定——
    本模块只报告"WebView2 现在到底有没有装好"这一件事实，不替调用方做主。
    `installed_now` 区分"本来就有"（零下载零安装）与"这次引导装上的"，
    纯粹给日志/遥测用，不影响 `ok` 的判断。
    """

    ok: bool
    installed_now: bool
    error: WebView2Error | None = None


def ensure_webview2(
    *,
    read_registry: RegistryReader = read_registry_pv_default,
    download_bootstrapper: BootstrapperDownloader = download_bootstrapper_default,
    run_installer: InstallerRunner = run_installer_default,
) -> EnsureResult:
    """已装则直接返回 ok（零额外开销：不下载、不联网、不起子进程）；

    缺失则下载 Evergreen Bootstrapper → 以 `/silent /install` 跑 → 复检注册表。
    三条失败路径各自返回结构化结果，全部人话 + 手动安装链接：

      1. 下载失败（网络问题/服务器错误）—— `ERR_DOWNLOAD_FAILED`
      2. 安装器退出码非零（含"根本没跑起来"，归一化成非零码）—— `ERR_INSTALL_FAILED`
      3. 装完之后复检仍缺失（bootstrapper 报成功但注册表查不到）—— `ERR_STILL_MISSING`

    下载到的 bootstrapper 落在 `tempfile.mkdtemp()` 给的系统临时目录（每次调用
    一个新目录，权限由系统临时目录机制保证），`finally` 里无条件清理——不管
    成功失败都不留下这个安装器文件。
    """
    if is_webview2_installed(read_registry=read_registry):
        return EnsureResult(ok=True, installed_now=False, error=None)

    work_dir = Path(tempfile.mkdtemp(prefix="msui-webview2-"))
    try:
        installer_path = work_dir / BOOTSTRAPPER_FILENAME
        try:
            download_bootstrapper(BOOTSTRAPPER_URL, installer_path)
        except BootstrapperDownloadError:
            return EnsureResult(
                ok=False,
                installed_now=False,
                error=WebView2Error(
                    kind=ERR_DOWNLOAD_FAILED,
                    message=f"WebView2 安装程序下载失败，请检查网络连接后重试；{_RETRY_SUFFIX}",
                ),
            )

        returncode = run_installer([str(installer_path), "/silent", "/install"])
        if returncode != 0:
            return EnsureResult(
                ok=False,
                installed_now=False,
                error=WebView2Error(
                    kind=ERR_INSTALL_FAILED,
                    message=(
                        f"WebView2 安装未完成（安装程序返回码 {returncode}）；{_RETRY_SUFFIX}"
                    ),
                ),
            )

        if not is_webview2_installed(read_registry=read_registry):
            return EnsureResult(
                ok=False,
                installed_now=False,
                error=WebView2Error(
                    kind=ERR_STILL_MISSING,
                    message=f"已尝试安装 WebView2，但检测仍未发现它；{_RETRY_SUFFIX}",
                ),
            )

        return EnsureResult(ok=True, installed_now=True, error=None)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
