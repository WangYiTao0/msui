"""pywebview 壳启动层（msui.shell.run）的测试。

这一层只做装配：建窗、挂钩子、起主循环。业务对象（js_api）由调用方组装好
整个递进来，壳不认识它的形状。测试全部经假 webview 模块驱动——绝不开窗、
绝不进主循环。

storage 语义：`storage_dir` 是显式参数，**没有默认路径**——不传就完全不定制
存储（也不做陈旧缓存清理），传了才落 `private_mode=False` + 显式
`storage_path` 那套持久化装配。`version` 同理由调用方注入，只被
`purge_stale_webview_storage` 消费。
"""
from __future__ import annotations

import ast
import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from msui import shell, single_instance


# ---------------------------------------------------------------------------
# 公共替身
# ---------------------------------------------------------------------------


class _FakeEvent:
    """长得像 pywebview 的 Event：只支持 `+=` 订阅，记下 handler 供测试触发。"""

    def __init__(self) -> None:
        self.handlers: list = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


def _install_fake_webview(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """把 `webview` 换成假模块：记录调用参数，绝不开窗、绝不进主循环。"""
    calls = SimpleNamespace(create_window=[], start=[], order=[])
    fake = types.ModuleType("webview")
    fake_window = SimpleNamespace(
        name="fake-window",
        # run 会往 before_show 上挂标题栏深色化的 handler，
        # 假窗口要有同形状的事件对象才接得住。
        events=SimpleNamespace(before_show=_FakeEvent()),
    )
    calls.window = fake_window

    def create_window(*args, **kwargs):
        calls.create_window.append((args, kwargs))
        calls.order.append("create_window")
        return fake_window

    def start(*args, **kwargs):
        calls.start.append((args, kwargs))
        calls.order.append("start")

    fake.create_window = create_window
    fake.start = start
    monkeypatch.setitem(sys.modules, "webview", fake)
    return calls


PAGE = "/somewhere/index.html"


# ---------------------------------------------------------------------------
# 窗口参数化：宽/高/最小尺寸/标题全是 run() 的关键字参数，带默认值
# ---------------------------------------------------------------------------


def test_run_defaults_create_window_geometry(monkeypatch):
    """不传时的默认几何：560×520、min_size (460, 360)（逻辑像素）。"""
    calls = _install_fake_webview(monkeypatch)
    shell.run(PAGE, single_instance=False)

    assert len(calls.create_window) == 1
    args, kwargs = calls.create_window[0]
    assert args[1] == PAGE
    assert kwargs["width"] == 560
    assert kwargs["height"] == 520
    assert kwargs["min_size"] == (460, 360)


def test_run_passes_custom_geometry_through(monkeypatch):
    """调用方给的宽/高/最小尺寸原样落到 create_window——这正是参数化的意义。"""
    calls = _install_fake_webview(monkeypatch)
    shell.run(PAGE, width=800, height=600, min_size=(500, 400), single_instance=False)

    _args, kwargs = calls.create_window[0]
    assert kwargs["width"] == 800
    assert kwargs["height"] == 600
    assert kwargs["min_size"] == (500, 400)


def test_run_default_title_is_a_neutral_placeholder(monkeypatch):
    """默认标题就是包名这种中性占位——共享运行时不带任何调用方的品牌。"""
    calls = _install_fake_webview(monkeypatch)
    shell.run(PAGE, single_instance=False)

    args, _kwargs = calls.create_window[0]
    assert args[0] == "msui"


def test_run_passes_custom_title_through(monkeypatch):
    calls = _install_fake_webview(monkeypatch)
    shell.run(PAGE, title="某个小程序", single_instance=False)

    args, _kwargs = calls.create_window[0]
    assert args[0] == "某个小程序"


def test_run_accepts_a_path_url_and_passes_it_as_string(monkeypatch, tmp_path):
    """url 收 Path 也行，递给 create_window 时是字符串——pywebview 只认 str。"""
    calls = _install_fake_webview(monkeypatch)
    page = tmp_path / "index.html"
    shell.run(page, single_instance=False)

    args, _kwargs = calls.create_window[0]
    assert args[1] == str(page)
    assert isinstance(args[1], str)


def test_run_passes_the_js_api_object_as_is(monkeypatch):
    """js_api 是调用方组装好的对象本身，壳原封不动递给 create_window。"""
    calls = _install_fake_webview(monkeypatch)
    api = object()
    shell.run(PAGE, js_api=api, single_instance=False)

    _args, kwargs = calls.create_window[0]
    assert kwargs["js_api"] is api


def test_run_without_js_api_passes_none(monkeypatch):
    calls = _install_fake_webview(monkeypatch)
    shell.run(PAGE, single_instance=False)

    _args, kwargs = calls.create_window[0]
    assert kwargs["js_api"] is None


# ---------------------------------------------------------------------------
# storage：显式 storage_dir 才定制持久化；不传就完全不碰
# ---------------------------------------------------------------------------


def test_run_with_storage_dir_starts_with_private_mode_false(monkeypatch, tmp_path):
    """给了 storage_dir 就必须两个参数一起落：pywebview 默认 private_mode=True
    会在关窗时 rmtree 整个用户数据目录；不显式给 storage_path 则落到所有
    pywebview 应用共享的目录。缺一个，「数据在版本更新后仍在」都不成立。"""
    calls = _install_fake_webview(monkeypatch)
    storage = tmp_path / "webview"
    shell.run(PAGE, storage_dir=storage, single_instance=False)

    assert len(calls.start) == 1
    _args, kwargs = calls.start[0]
    assert kwargs["private_mode"] is False
    assert kwargs["storage_path"] == str(storage)
    assert storage.is_dir()  # run 负责把目录建出来，pywebview 只管用


def test_run_without_storage_dir_leaves_storage_untouched(monkeypatch):
    """不传 storage_dir → 不递 private_mode / storage_path，全按 pywebview 默认走。
    共享运行时不许自己发明一个默认数据目录。"""
    calls = _install_fake_webview(monkeypatch)
    shell.run(PAGE, single_instance=False)

    _args, kwargs = calls.start[0]
    assert "storage_path" not in kwargs
    assert "private_mode" not in kwargs


def test_run_without_storage_dir_never_purges(monkeypatch):
    """没有 storage_dir 时连清理都不该发生——没有目录，清什么都是越权。"""
    _install_fake_webview(monkeypatch)
    purges: list = []
    monkeypatch.setattr(
        shell, "purge_stale_webview_storage", lambda *a: purges.append(a) or True
    )
    shell.run(PAGE, version="1.0.0", single_instance=False)

    assert purges == []


def test_run_with_storage_dir_but_no_version_skips_purge(monkeypatch, tmp_path):
    """有 storage_dir 没 version → 建目录但不清理：没有版本可比对，「陈旧」
    无从谈起，留着缓存比瞎清安全。"""
    _install_fake_webview(monkeypatch)
    storage = tmp_path / "webview"
    storage.mkdir()
    leftover = storage / "cache-file"
    leftover.write_text("keep me", encoding="utf-8")

    shell.run(PAGE, storage_dir=storage, single_instance=False)

    assert leftover.is_file()
    assert not (storage / "page-version.txt").exists()


def test_run_purges_with_the_injected_version(monkeypatch, tmp_path):
    """version 由调用方注入，purge 收到的就是这个字符串——壳自己绝不去任何
    发行版元数据里取版本号。"""
    _install_fake_webview(monkeypatch)
    storage = tmp_path / "webview"
    purges: list = []

    def spy(path, version):
        purges.append((path, version))
        return True

    monkeypatch.setattr(shell, "purge_stale_webview_storage", spy)
    shell.run(PAGE, storage_dir=storage, version="7.8.9+local", single_instance=False)

    assert purges == [(storage, "7.8.9+local")]


def test_run_purges_stale_storage_before_creating_it(monkeypatch, tmp_path):
    """run() 必须在自己 mkdir storage 之前调用 purge_stale_webview_storage
    （否则 purge 永远看不到「目录还不存在」这个首次开窗态）。"""
    _install_fake_webview(monkeypatch)
    storage = tmp_path / "webview"
    order: list[str] = []
    original_purge = shell.purge_stale_webview_storage

    def spy(path, version):
        order.append("purge")
        assert not storage.is_dir(), "purge 被调用时 storage 目录已经存在，说明 run() 抢先建了目录"
        return original_purge(path, version)

    monkeypatch.setattr(shell, "purge_stale_webview_storage", spy)
    original_mkdir = Path.mkdir

    def spying_mkdir(self, *args, **kwargs):
        if self == storage:
            order.append("mkdir")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", spying_mkdir)

    shell.run(PAGE, storage_dir=storage, version="1.0.0", single_instance=False)

    assert order[:2] == ["purge", "mkdir"]


# ---------------------------------------------------------------------------
# purge_stale_webview_storage：按版本戳整目录清理陈旧 webview 缓存
# ---------------------------------------------------------------------------
#
# 背景：WebView2 以 URL 为键缓存页面，裸文件路径的 URL 在版本之间不变，
# 更新后老页面会被继续端出来；在 URL 上拼版本查询串的做法在 Windows/WebView2
# 上会被并进文件名报 ERR_FILE_NOT_FOUND。所以缓存职责收在 Python 侧：
# storage 目录里放一枚版本戳文件，戳对不上就把 storage 整个推倒重建。


def test_purge_matching_stamp_skips_cleanup(tmp_path):
    """戳文件内容 == 当前版本 → 什么都不动，返回 False。"""
    storage = tmp_path / "webview"
    storage.mkdir()
    stamp = storage / "page-version.txt"
    stamp.write_text("1.2.3", encoding="utf-8")
    marker = storage / "leftover-cache-file"
    marker.write_text("still here", encoding="utf-8")

    result = shell.purge_stale_webview_storage(storage, "1.2.3")

    assert result is False
    assert marker.is_file()
    assert stamp.read_text(encoding="utf-8") == "1.2.3"


def test_purge_mismatched_stamp_clears_and_restamps(tmp_path):
    """戳文件内容 != 当前版本 → storage 整个被 rmtree 重建，戳写成新版本，返回 True。"""
    storage = tmp_path / "webview"
    storage.mkdir()
    (storage / "page-version.txt").write_text("1.2.3", encoding="utf-8")
    stale = storage / "leftover-cache-file"
    stale.write_text("old cache", encoding="utf-8")

    result = shell.purge_stale_webview_storage(storage, "1.2.4")

    assert result is True
    assert not stale.exists()
    assert storage.is_dir()
    assert (storage / "page-version.txt").read_text(encoding="utf-8") == "1.2.4"


def test_purge_missing_stamp_clears_storage(tmp_path):
    """无戳（含 storage 目录本身还不存在的首次开窗）视为不匹配，清一次无害。"""
    storage = tmp_path / "webview"  # 故意不预先建目录

    result = shell.purge_stale_webview_storage(storage, "1.0.0")

    assert result is True
    assert storage.is_dir()
    assert (storage / "page-version.txt").read_text(encoding="utf-8") == "1.0.0"


def test_purge_second_call_same_version_after_stamp_written_skips_cleanup(tmp_path):
    """先按某版本清一次、写好戳，同版本再调一次 → 第二次不该再清。"""
    storage = tmp_path / "webview"

    first = shell.purge_stale_webview_storage(storage, "2.0.0")
    marker = storage / "fresh-cache-file"
    marker.write_text("just cached", encoding="utf-8")
    second = shell.purge_stale_webview_storage(storage, "2.0.0")

    assert first is True
    assert second is False
    assert marker.is_file()


def test_purge_rmtree_failure_degrades_without_crashing(monkeypatch, tmp_path):
    """rmtree 抛异常时不能让调用方崩掉——debug 降级，返回 False。"""
    storage = tmp_path / "webview"
    storage.mkdir()
    (storage / "page-version.txt").write_text("1.0.0", encoding="utf-8")

    def boom(_path):
        raise OSError("device busy")

    monkeypatch.setattr(shell.shutil, "rmtree", boom)

    result = shell.purge_stale_webview_storage(storage, "1.0.1")

    assert result is False


def test_purge_leaves_sibling_files_untouched(tmp_path):
    """rmtree 只碰得到 storage 这一棵子树，调用方放在旁边的数据文件必须原封不动。"""
    storage = tmp_path / "webview"
    storage.mkdir()
    (storage / "page-version.txt").write_text("1.2.3", encoding="utf-8")
    sibling = tmp_path / "settings.json"
    sibling.write_text('{"pinned": true}', encoding="utf-8")

    shell.purge_stale_webview_storage(storage, "1.2.4")

    assert sibling.is_file()
    assert sibling.read_text(encoding="utf-8") == '{"pinned": true}'


# ---------------------------------------------------------------------------
# 标题栏深色化挂载：before_show 上、收到的就是这扇窗
# ---------------------------------------------------------------------------


def test_run_hooks_dark_chrome_onto_before_show(monkeypatch):
    """标题栏深色化挂在 window.events.before_show 上：winforms 在
    Form.__init__ 里就创建了 Handle，before_show 又是 should_lock=True 的同步
    事件，Show() 之前染好——白标题栏一帧都不闪。触发后收到的就是这扇窗。"""
    calls = _install_fake_webview(monkeypatch)
    painted = []
    monkeypatch.setattr(shell, "apply_dark_chrome", painted.append)

    shell.run(PAGE, single_instance=False)

    handlers = calls.window.events.before_show.handlers
    assert handlers, "run 没有往 before_show 上挂任何 handler"
    for handler in handlers:
        handler()
    assert painted == [calls.window]


# ---------------------------------------------------------------------------
# 隐藏开窗：给无人值守验证用的缝——默认必须可见
# ---------------------------------------------------------------------------


def test_run_creates_a_visible_window_by_default(monkeypatch):
    """默认可见——断言的是 create_window 收到的值本身而不是「没传这个参数」：
    pywebview 的默认也是 False，但那是它的默认，不是本壳的承诺；显式传死
    才挡得住哪天默认变了。"""
    calls = _install_fake_webview(monkeypatch)
    shell.run(PAGE, single_instance=False)

    _args, kwargs = calls.create_window[0]
    assert kwargs["hidden"] is False


def test_run_can_create_a_hidden_window(monkeypatch):
    """hidden=True 原样递给 create_window——窗口建起来、页面照常加载，只是不上屏。"""
    calls = _install_fake_webview(monkeypatch)
    shell.run(PAGE, hidden=True, single_instance=False)

    _args, kwargs = calls.create_window[0]
    assert kwargs["hidden"] is True


# ---------------------------------------------------------------------------
# 调用序列与注入钩子
# ---------------------------------------------------------------------------


def test_run_creates_window_before_start(monkeypatch):
    """create_window 在前、start 在后——start 阻塞主循环，反过来窗口永远出不来。"""
    calls = _install_fake_webview(monkeypatch)
    shell.run(PAGE, single_instance=False)
    assert calls.order == ["create_window", "start"]


def test_before_start_runs_after_the_window_exists_but_before_the_loop(monkeypatch):
    """`before_start` 必须夹在 create_window 与 start **之间**，一边都不能挪。

    两个方向都是硬要求，所以断言的是整个调用序列而不是「它被调过」：

    - 早于 create_window：拿不到窗口，钩子（比如托盘的「打开主界面」）没有
      东西可 show；
    - 晚于 start：`webview.start()` 一进去就是主循环、不返回了，根本轮不到它跑；
      而 macOS 上寄生宿主 run loop 的组件（如 pystray）挂晚了就不出现。

    钩子拿得到窗口本尊也一并钉住。"""
    calls = _install_fake_webview(monkeypatch)
    seen: list[object] = []

    def _before_start(window):
        # 自己往序列里记一笔：order 是假 webview 记的，这个钩子不经过它。
        calls.order.append("before_start")
        seen.append(window)

    shell.run(PAGE, before_start=_before_start, single_instance=False)

    assert calls.order == ["create_window", "before_start", "start"]
    assert seen == [calls.window]


def test_run_works_without_before_start(monkeypatch):
    """不传就是纯开窗——调用方不该被迫关心这个缝。"""
    calls = _install_fake_webview(monkeypatch)

    shell.run(PAGE, single_instance=False)

    assert calls.order == ["create_window", "start"]


def test_run_passes_on_ready_hook_to_start(monkeypatch):
    """on_ready 钩子（自动驾驶/无头驱动用）经 start(func=…, args=(window,)) 接进去。"""
    calls = _install_fake_webview(monkeypatch)

    def hook(window) -> None:  # pragma: no cover - 只比对身份，不会被调用
        pass

    shell.run(PAGE, on_ready=hook, single_instance=False)

    _args, kwargs = calls.start[0]
    assert kwargs["func"] is hook
    # args 里就是 create_window 返回的那个 window 对象
    assert kwargs["args"][0].name == "fake-window"


def test_run_passes_the_window_icon_to_start(monkeypatch, tmp_path):
    """`icon` 经 `webview.start(icon=…)` 接进去。

    核对结论（pywebview 6.2.1 源码）：`webview/__init__.py` 的 docstring 说 icon
    "Supported only on GTK/QT"，但 `platforms/winforms.py` 242-244 行实际支持——
    显式给了 icon 就 `self.Icon = Icon(path)`；没给则 247 行自动从 sys.executable
    的资源段提取。cocoa 628 行也读它（NSImage 对 .ico 只是静默失败），传了不会炸。
    """
    calls = _install_fake_webview(monkeypatch)
    icon = tmp_path / "app.ico"

    shell.run(PAGE, icon=icon, single_instance=False)

    _args, kwargs = calls.start[0]
    assert kwargs["icon"] == str(icon)


def test_run_without_an_icon_does_not_invent_one(monkeypatch):
    """不传 icon 就传 None 给 start：Windows 上 pywebview 会退回「从 exe 资源段
    提取」，那正是打包资源该承担的那份。"""
    calls = _install_fake_webview(monkeypatch)

    shell.run(PAGE, single_instance=False)

    _args, kwargs = calls.start[0]
    assert kwargs.get("icon") is None


# ---------------------------------------------------------------------------
# 单实例守卫：id 必填（票 13）；被拦时第二实例连窗口都不建（票 12）
# ---------------------------------------------------------------------------


def _stub_guard(monkeypatch, *, allowed: bool):
    """把守卫两个函数换成探针：记下收到的参数，acquire 按 `allowed` 作答。"""
    seen = SimpleNamespace(acquire=[], raise_window=[])
    monkeypatch.setattr(
        single_instance,
        "acquire",
        lambda app_id: seen.acquire.append(app_id) or allowed,
    )
    monkeypatch.setattr(
        single_instance,
        "raise_existing_window",
        lambda title: seen.raise_window.append(title) or False,
    )
    return seen


def test_run_without_single_instance_refuses_to_open_a_window(monkeypatch):
    """**不报上 id 就开不了窗**：`single_instance` 是必填关键字参数。

    单例是默认模式、不是可选装饰——漏接入必须在编码期当场炸，而不是等到用户
    连点图标开出 N 个窗才发现（官方样板 Tool_Counter 就这么漏了整整一版）。
    TypeError 由 Python 的签名检查抛出：连函数体都进不去，自然也不会建窗。
    """
    calls = _install_fake_webview(monkeypatch)

    with pytest.raises(TypeError):
        shell.run(PAGE)  # type: ignore[call-arg]

    assert calls.order == []


def test_run_with_single_instance_false_skips_the_guard(monkeypatch):
    """`False` 是**显式**多开的逃生口：守卫整段跳过，照常建窗。

    保留这个口子是给极少数真需要多开的场景（以及本文件里那些测别的维度的
    用例）。它与「漏传」的区别正是这条规矩的全部意义：多开必须是写下来的决定。
    """
    calls = _install_fake_webview(monkeypatch)
    seen = _stub_guard(monkeypatch, allowed=True)

    shell.run(PAGE, single_instance=False)

    assert seen.acquire == []
    assert calls.order == ["create_window", "start"]


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_run_rejects_a_blank_id_before_doing_anything(monkeypatch, tmp_path, blank):
    """空串 / 纯空白 id 当场 ValueError，且**什么都还没做**。

    为什么不当成「没传」放行：空 id 会让 mutex 名退化成裸前缀 `Local\\msui-`，
    于是**两个不同的小程序共用同一把锁**——先开的那个会把后开的那个顶掉，用户
    看到的是「点了 B，前台弹出来的是 A」。这比压根不设守卫更糟，而且是静默的。

    「什么都还没做」有两条可判据：没建窗（create_window 没被调），也没碰
    storage（purge 没跑、目录没建）——校验必须在装配之前，不能等窗都建好了才炸。
    """
    calls = _install_fake_webview(monkeypatch)
    storage = tmp_path / "webview"

    with pytest.raises(ValueError):
        shell.run(PAGE, single_instance=blank, storage_dir=storage, version="1.0.0")

    assert calls.order == []
    assert not storage.exists()


def test_run_with_single_instance_acquires_that_id(monkeypatch):
    """给了 id 就拿这个 id 去抢锁——值用 miniprog.toml 的 id，全局唯一现成。"""
    calls = _install_fake_webview(monkeypatch)
    seen = _stub_guard(monkeypatch, allowed=True)

    shell.run(PAGE, single_instance="counter")

    assert seen.acquire == ["counter"]
    assert calls.order == ["create_window", "start"]  # 第一实例照常开窗


def test_second_instance_creates_no_window_at_all(monkeypatch):
    """抢不到锁 = 已有实例在跑：不建窗、不进主循环、静默返回。"""
    calls = _install_fake_webview(monkeypatch)
    _stub_guard(monkeypatch, allowed=False)

    shell.run(PAGE, single_instance="counter")

    assert calls.order == []


def test_second_instance_tries_to_raise_the_existing_window_by_title(monkeypatch):
    """先尽力把已开的窗带到前台，找的就是本次 run 会用的那个标题——用户的
    意图是「打开它」，能把老窗端到眼前就等于满足了。"""
    _install_fake_webview(monkeypatch)
    seen = _stub_guard(monkeypatch, allowed=False)

    shell.run(PAGE, single_instance="counter", title="计数器")

    assert seen.raise_window == ["计数器"]


def test_second_instance_never_touches_the_first_instances_storage(monkeypatch, tmp_path):
    """第二实例不许碰 storage：purge 会把**第一实例正开着的窗**的缓存整个
    推倒重建。所以守卫必须判在 purge/mkdir 之前，不只是 create_window 之前。"""
    _install_fake_webview(monkeypatch)
    _stub_guard(monkeypatch, allowed=False)
    storage = tmp_path / "webview"
    purges: list = []
    monkeypatch.setattr(
        shell, "purge_stale_webview_storage", lambda *a: purges.append(a) or True
    )

    shell.run(PAGE, single_instance="counter", storage_dir=storage, version="1.0.0")

    assert purges == []
    assert not storage.exists()


def test_second_instance_exits_without_importing_webview(monkeypatch):
    """第二实例连 pywebview 都不 import——「不初始化 webview」的可判据形态：
    把 sys.modules['webview'] 顶成 None（import 会当场 ImportError），守卫
    路径若还去 import 它，这条测试立刻红。"""
    monkeypatch.setitem(sys.modules, "webview", None)
    _stub_guard(monkeypatch, allowed=False)

    shell.run(PAGE, single_instance="counter")  # 不抛 = 通过


def test_second_instance_exits_silently_even_if_raising_blows_up(monkeypatch):
    """带前台那一步炸了也只是静默退出：第二实例**绝不弹错误框**，也绝不
    把异常摔到用户脸上——用户语义是「我想打开它」，报错是在惩罚这个意图。"""
    _install_fake_webview(monkeypatch)
    monkeypatch.setattr(single_instance, "acquire", lambda _app_id: False)

    def boom(_title):
        raise RuntimeError("user32 不在")

    monkeypatch.setattr(single_instance, "raise_existing_window", boom)

    shell.run(PAGE, single_instance="counter")  # 不抛 = 通过


def test_second_instance_logs_exactly_one_line(monkeypatch, caplog):
    """日志一行：出问题时日志里答得出「第二实例被守卫拦下了」，但不刷屏。"""
    _install_fake_webview(monkeypatch)
    _stub_guard(monkeypatch, allowed=False)

    with caplog.at_level("INFO", logger="msui.shell"):
        shell.run(PAGE, single_instance="counter")

    assert len(caplog.records) == 1


def test_guard_path_pops_no_dialog():
    """形态守卫：壳与守卫模块里不许出现任何弹框 API——「静默退出」是契约，
    哪天有人「好心」加个提示框，这条当场红。"""
    for module in (shell, single_instance):
        source = Path(module.__file__).read_text(encoding="utf-8")
        for banned in ("MessageBox", "messagebox", "create_confirmation_dialog", "alert("):
            assert banned not in source, f"{module.__name__} 里出现了弹框 API：{banned}"


# ---------------------------------------------------------------------------
# 依赖形态：webview 延迟 import；壳不依赖任何宿主发行版
# ---------------------------------------------------------------------------


def test_shell_module_has_no_top_level_webview_import(monkeypatch):
    """没装 pywebview 的环境 import 壳模块不炸：webview 的 import 必须在 run()
    函数体内。做法：把 sys.modules['webview'] 顶成 None（import 会立刻
    ImportError），然后 reload 壳模块——顶层若有 import webview，这里当场就红。
    """
    monkeypatch.setitem(sys.modules, "webview", None)
    importlib.reload(shell)


def test_shell_imports_only_stdlib_msui_and_webview():
    """壳的全部 import（含函数体内的）只许来自标准库、msui 自己和 webview——
    版本号、页面路径、js_api 全靠调用方注入，绝不 import 任何宿主包去取。"""
    tree = ast.parse(Path(shell.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            assert node.module is not None
            roots.add(node.module.split(".")[0])
    allowed = set(sys.stdlib_module_names) | {"msui", "webview", "__future__"}
    offenders = roots - allowed
    assert not offenders, f"shell.py import 了宿主/第三方包：{sorted(offenders)}"
