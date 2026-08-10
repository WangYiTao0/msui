"""WebView2 检测与引导安装。

seam：`is_webview2_installed` 的 `read_registry`、`ensure_webview2` 的
`read_registry` / `download_bootstrapper` / `run_installer` 三个注入点——
全部用桩函数，Mac 上全量可测，不碰真注册表/真网络/真子进程。

纪律钉住的两件事：
  1. 缺失路径绝不下载/联网（已装时零额外开销）；
  2. 三条失败路径的 message 是人话，不甩英文异常原文/Traceback。

品牌中性化核对（这三处不许出现公司名/内部票号/个人账号）：
  - User-Agent（会随下载请求发到微软服务器）；
  - 临时目录前缀；
  - 模块 docstring 第一行。

守卫写法约定：全部用 allowlist/结构断言（fullmatch 白名单、前缀断言、票号
正则），**不许把被禁字样本身写进断言字面量**——否则守卫测试自己就成了泄漏源。
"""
from __future__ import annotations

import re

import pytest

from msui.webview2 import (
    BOOTSTRAPPER_URL,
    ERR_DOWNLOAD_FAILED,
    ERR_INSTALL_FAILED,
    ERR_STILL_MISSING,
    REGISTRY_LOCATIONS,
    WEBVIEW2_CLIENT_GUID,
    BootstrapperDownloadError,
    ensure_webview2,
    is_webview2_installed,
)


def _reader(values: dict[tuple[str, str], str | None]):
    """按 (hive, subkey) 精确匹配返回值的桩注册表读取函数；没配置的位置返回 None。"""

    def read(hive: str, subkey: str) -> str | None:
        return values.get((hive, subkey))

    return read


# ---------------------------------------------------------------------------
# 检测：三处 pv 键位置
# ---------------------------------------------------------------------------


def test_registry_locations_are_exactly_the_three_documented_pv_keys():
    """「per-machine 两处 WOW 变体 + per-user」= 3 处，键位路径逐字钉住。"""
    expected = (
        ("HKLM", f"SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{WEBVIEW2_CLIENT_GUID}"),
        ("HKLM", f"SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{WEBVIEW2_CLIENT_GUID}"),
        ("HKCU", f"Software\\Microsoft\\EdgeUpdate\\Clients\\{WEBVIEW2_CLIENT_GUID}"),
    )
    assert expected == REGISTRY_LOCATIONS
    assert WEBVIEW2_CLIENT_GUID == "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def test_installed_when_only_hklm_wow6432node_hit():
    hive, subkey = REGISTRY_LOCATIONS[0]
    assert is_webview2_installed(read_registry=_reader({(hive, subkey): "120.0.2210.61"}))


def test_installed_when_only_hklm_native_hit():
    hive, subkey = REGISTRY_LOCATIONS[1]
    assert is_webview2_installed(read_registry=_reader({(hive, subkey): "120.0.2210.61"}))


def test_installed_when_only_hkcu_hit():
    hive, subkey = REGISTRY_LOCATIONS[2]
    assert is_webview2_installed(read_registry=_reader({(hive, subkey): "120.0.2210.61"}))


def test_not_installed_when_all_three_locations_missing():
    assert not is_webview2_installed(read_registry=_reader({}))


def test_not_installed_when_value_is_all_zero_version():
    """"0.0.0.0" 是官方文档明写的"未安装"哨兵值，即便键存在也不算已装。"""
    reader = _reader({loc: "0.0.0.0" for loc in REGISTRY_LOCATIONS})  # noqa: S104 - 版本哨兵值
    assert not is_webview2_installed(read_registry=reader)


def test_not_installed_when_value_is_empty_string():
    reader = _reader({loc: "" for loc in REGISTRY_LOCATIONS})
    assert not is_webview2_installed(read_registry=reader)


def test_checks_all_locations_not_just_the_first():
    """第一处缺失、第三处命中也算已装——不能读到第一个 None 就提前判负。"""
    hive, subkey = REGISTRY_LOCATIONS[2]
    reader = _reader({(hive, subkey): "121.0.0.1"})
    assert is_webview2_installed(read_registry=reader)


# ---------------------------------------------------------------------------
# 引导：ensure_webview2
# ---------------------------------------------------------------------------


def _installed_reader():
    hive, subkey = REGISTRY_LOCATIONS[0]
    return _reader({(hive, subkey): "120.0.2210.61"})


def _missing_reader():
    return _reader({})


def _refusing_downloader(*_args, **_kwargs):
    raise AssertionError("已装时不该调用下载器")


def _refusing_installer(*_args, **_kwargs):
    raise AssertionError("已装时不该调用安装器")


def test_already_installed_is_ok_with_zero_download_calls():
    """已装 → 直接返回 ok，下载器/安装器一次都不被调（红线：零额外开销）。"""
    result = ensure_webview2(
        read_registry=_installed_reader(),
        download_bootstrapper=_refusing_downloader,
        run_installer=_refusing_installer,
    )
    assert result.ok is True
    assert result.installed_now is False
    assert result.error is None


def test_missing_then_install_succeeds():
    downloaded = []

    def downloader(url, target):
        downloaded.append(url)
        target.write_bytes(b"fake bootstrapper bytes")

    def installer(command):
        assert command[0].endswith("MicrosoftEdgeWebview2Setup.exe")
        assert command[1:] == ["/silent", "/install"]
        return 0

    # 装完之后复检要读到"已装"——用一个"先缺后有"的可变状态模拟真实序列。
    installed = {"value": False}

    def reader(hive, subkey):
        if not installed["value"]:
            return None
        loc = REGISTRY_LOCATIONS[0]
        return "120.0.2210.61" if (hive, subkey) == loc else None

    def installer_then_flip(command):
        rc = installer(command)
        installed["value"] = True
        return rc

    result = ensure_webview2(
        read_registry=reader,
        download_bootstrapper=downloader,
        run_installer=installer_then_flip,
    )

    assert downloaded == [BOOTSTRAPPER_URL]
    assert result.ok is True
    assert result.installed_now is True
    assert result.error is None


def test_download_failure_returns_structured_error():
    def failing_downloader(url, target):
        raise BootstrapperDownloadError("Connection refused")

    result = ensure_webview2(
        read_registry=_missing_reader(),
        download_bootstrapper=failing_downloader,
        run_installer=_refusing_installer,
    )

    assert result.ok is False
    assert result.error.kind == ERR_DOWNLOAD_FAILED
    assert result.error.message  # 非空


def test_installer_nonzero_exit_code_returns_structured_error():
    def downloader(url, target):
        target.write_bytes(b"fake")

    result = ensure_webview2(
        read_registry=_missing_reader(),
        download_bootstrapper=downloader,
        run_installer=lambda command: 1603,  # MSI 常见的失败码，随便挑一个非零值
    )

    assert result.ok is False
    assert result.error.kind == ERR_INSTALL_FAILED
    assert "1603" in result.error.message


def test_still_missing_after_install_returns_structured_error():
    """安装器报了退出码 0（"成功"），但复检注册表仍然没有 —— 不能盲信退出码。"""

    def downloader(url, target):
        target.write_bytes(b"fake")

    result = ensure_webview2(
        read_registry=_missing_reader(),  # 复检用的还是这个 reader：永远查不到
        download_bootstrapper=downloader,
        run_installer=lambda command: 0,
    )

    assert result.ok is False
    assert result.error.kind == ERR_STILL_MISSING


@pytest.mark.parametrize(
    "make_result",
    [
        lambda: ensure_webview2(
            read_registry=_missing_reader(),
            download_bootstrapper=lambda url, target: (_ for _ in ()).throw(
                BootstrapperDownloadError("[Errno -2] Name or service not known")
            ),
            run_installer=_refusing_installer,
        ),
        lambda: ensure_webview2(
            read_registry=_missing_reader(),
            download_bootstrapper=lambda url, target: target.write_bytes(b"fake"),
            run_installer=lambda command: 1603,
        ),
        lambda: ensure_webview2(
            read_registry=_missing_reader(),
            download_bootstrapper=lambda url, target: target.write_bytes(b"fake"),
            run_installer=lambda command: 0,
        ),
    ],
)
def test_all_three_failure_messages_are_human_not_raw_exceptions(make_result):
    """message 不含 Traceback / 英文异常类名，全是给业务用户看的人话，并附手动安装链接。"""
    result = make_result()
    assert result.ok is False
    message = result.error.message

    assert "Traceback" not in message
    for leaked in (
        "BootstrapperDownloadError",
        "OSError",
        "URLError",
        "HTTPError",
        "Errno",
        "Exception",
    ):
        assert leaked not in message
    assert "developer.microsoft.com" in message  # 手动安装链接必须在
    # 全篇挑不出连续 3 个以上的纯 ASCII 字母单词（阈值防止把 URL/HKLM 之类误伤）——
    # 真正的英文异常原文（句子）会明显命中，人话文案不会。
    assert not re.search(r"[A-Za-z]{4,}\s+[A-Za-z]{4,}\s+[A-Za-z]{4,}", message)


# ---------------------------------------------------------------------------
# 品牌中性化：三处补点
# ---------------------------------------------------------------------------


def test_user_agent_is_neutral_msui_form():
    """UA 会随下载请求发到微软服务器，必须是中性的 msui/<版本> 形态。

    用 allowlist（fullmatch 白名单）而非列举被禁词：任何品牌名、账号名、
    空格、括号都进不了这个字符集，且守卫自身不携带被禁字样。
    """
    from msui import webview2

    ua = webview2._USER_AGENT
    assert re.fullmatch(r"msui-[A-Za-z0-9./-]+", ua)
    assert "github.com" not in ua.lower()
    assert not re.search(r"#\d+", ua)


def test_temp_dir_prefix_has_no_brand():
    tmp_prefix_calls = []
    real_mkdtemp = __import__("tempfile").mkdtemp

    def spy_mkdtemp(*args, **kwargs):
        tmp_prefix_calls.append(kwargs.get("prefix", ""))
        return real_mkdtemp(*args, **kwargs)

    import msui.webview2 as webview2_module

    original = webview2_module.tempfile.mkdtemp
    webview2_module.tempfile.mkdtemp = spy_mkdtemp
    try:
        ensure_webview2(
            read_registry=_missing_reader(),
            download_bootstrapper=lambda url, target: (_ for _ in ()).throw(
                BootstrapperDownloadError("boom")
            ),
            run_installer=_refusing_installer,
        )
    finally:
        webview2_module.tempfile.mkdtemp = original

    assert tmp_prefix_calls
    for prefix in tmp_prefix_calls:
        # allowlist：前缀必须是 msui- 开头的纯 [msui-字母数字.-] 形态，
        # 品牌名/账号名根本进不来，无须列举被禁词。
        assert prefix.startswith("msui-")
        assert re.fullmatch(r"msui-[A-Za-z0-9.-]*", prefix)


def test_module_docstring_has_no_ticket_or_internal_references():
    """结构断言拦内部痕迹：#号票引、spec+井号、P+两位数内部代号、账号域名。

    不把品牌词本身写进断言字面量——用形态特征（票号/代号的书写模式）覆盖
    内部引用，配合非空断言确保 docstring 存在。
    """
    import msui.webview2 as webview2_module

    doc = webview2_module.__doc__ or ""
    assert doc.strip()  # docstring 必须存在，否则下面全是空转
    assert not re.search(r"#\d+", doc)  # 内部票号形如 #NN
    assert not re.search(r"spec\s*#", doc, re.IGNORECASE)
    assert not re.search(r"\bP\d{2}\b", doc)  # 内部阶段代号形如 P + 两位数
    assert "github.com" not in doc.lower()  # 个人账号以仓库 URL 形态出现
