"""单实例守卫（msui.single_instance）的测试。

三层：

  1. **真锁语义**——不注入任何替身，在开发机（POSIX）上用真 flock 跑：同 id
     第二次拿不到、不同 id 互不干扰、持有者进程一死锁立刻可再拿（无 stale）。
     Windows 侧的命名 mutex 语义与这几条一一对应，靠形态测试钉住名字与分支
     选择——真机行为在冻结冒烟里验（见 tests/smoke/probe.py）。
  2. **分支选择与降级**——platform 与底层调用可注入，Mac 上照样走 Windows 分支。
  3. **带前台**——FindWindow/SetForegroundWindow 两个缝注入，钉住「找不到就
     不硬来」「失败只降级」。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

from msui import single_instance


# ---------------------------------------------------------------------------
# 真锁语义：POSIX 侧 flock，不注入替身
# ---------------------------------------------------------------------------


def _real_posix_acquire(tmp_path):
    """把锁文件挪进 tmp_path 的 acquire_lock：真加锁，只是不共用系统临时目录。"""
    return lambda app_id: single_instance._acquire_posix(tmp_path / f"{app_id}.lock")


def test_first_instance_acquires_the_lock(tmp_path):
    """头一个实例拿得到锁 → True = 「可以开窗」。"""
    assert single_instance.acquire("solo-a", acquire_lock=_real_posix_acquire(tmp_path))


def test_second_acquire_of_the_same_id_fails(tmp_path):
    """同 id 再拿一次就拿不到——这正是「第二实例不开新窗」的判据。

    用 flock 而不是 fcntl.lockf 就是为了这一条：POSIX record lock（lockf）
    按**进程**记账，同一进程再拿一次会成功，守卫在「用户双击两下、第二个
    进程还没起来」之外的任何同进程复核里都会假绿；flock 绑在 open file
    description 上，同进程的另一个 fd 一样被挡。
    """
    acquire_lock = _real_posix_acquire(tmp_path)
    assert single_instance.acquire("solo-b", acquire_lock=acquire_lock) is True
    assert single_instance.acquire("solo-b", acquire_lock=acquire_lock) is False


def test_different_ids_do_not_collide(tmp_path):
    """锁按 app_id 分——计数器开着不该挡住另一个小程序。"""
    acquire_lock = _real_posix_acquire(tmp_path)
    assert single_instance.acquire("solo-c", acquire_lock=acquire_lock) is True
    assert single_instance.acquire("solo-d", acquire_lock=acquire_lock) is True


# ---------------------------------------------------------------------------
# 双实例实测：真起子进程，钉住跨进程互斥与「持有者一死就没有 stale」
# ---------------------------------------------------------------------------

_CHILD = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    sys.path.insert(0, {src!r})
    from msui import single_instance
    lock = Path({lock!r})
    got = single_instance.acquire("child", acquire_lock=lambda a: single_instance._acquire_posix(lock))
    print("GOT" if got else "BLOCKED", flush=True)
    time.sleep(float(sys.argv[1]))
    """
)


def _child(lock, hold_seconds: float) -> subprocess.Popen:
    src = str(single_instance.__file__).rsplit("/msui/", 1)[0]
    code = _CHILD.format(src=src, lock=str(lock))
    return subprocess.Popen(
        [sys.executable, "-c", code, str(hold_seconds)],
        stdout=subprocess.PIPE,
        text=True,
    )


@pytest.mark.skipif(os.name != "posix", reason="子进程实测走 POSIX 锁文件路径")
def test_two_processes_only_one_gets_the_lock(tmp_path):
    """两个进程抢同一把锁：先到的 GOT，后到的 BLOCKED。"""
    lock = tmp_path / "child.lock"
    first = _child(lock, hold_seconds=5)
    assert first.stdout is not None
    assert first.stdout.readline().strip() == "GOT"

    second = _child(lock, hold_seconds=0)
    assert second.stdout is not None
    assert second.stdout.readline().strip() == "BLOCKED"
    second.wait(timeout=10)

    first.kill()
    first.wait(timeout=10)


@pytest.mark.skipif(os.name != "posix", reason="子进程实测走 POSIX 锁文件路径")
def test_lock_dies_with_the_holder_process(tmp_path):
    """持有者进程一没，锁立刻可再拿——不选锁文件「存在即占用」的理由就是这个：
    内核持锁没有 stale 态，上一次崩溃/被任务管理器杀掉不会把小程序永久锁死。"""
    lock = tmp_path / "child.lock"
    first = _child(lock, hold_seconds=60)
    assert first.stdout is not None
    assert first.stdout.readline().strip() == "GOT"
    first.kill()
    first.wait(timeout=10)

    after = _child(lock, hold_seconds=0)
    assert after.stdout is not None
    assert after.stdout.readline().strip() == "GOT"
    after.wait(timeout=10)


# ---------------------------------------------------------------------------
# 名字与路径形态：Windows 侧只能靠这条钉住（开发机跑不出真 mutex）
# ---------------------------------------------------------------------------


def test_mutex_name_is_session_local_and_namespaced():
    """`Local\\msui-<id>`：Local = 当前登录会话内唯一（多用户各开各的），
    msui- 前缀避免与别的程序撞名。"""
    assert single_instance.mutex_name("counter") == "Local\\msui-counter"


def test_lock_path_lives_in_the_system_temp_dir():
    """POSIX 锁文件落系统临时目录，不往调用方的数据目录里塞东西。"""
    path = single_instance.lock_path("counter")
    assert path.name == "msui-counter.lock"
    assert path.parent == Path(tempfile.gettempdir())


# ---------------------------------------------------------------------------
# 分支选择与降级：platform 可注入，Mac 上照样测 Windows 分支
# ---------------------------------------------------------------------------


def test_windows_platform_uses_the_named_mutex(monkeypatch):
    """platform=win32 → 走 `_acquire_windows`，收到的就是 app_id 本身。"""
    seen: list[str] = []
    monkeypatch.setattr(
        single_instance, "_acquire_windows", lambda app_id: seen.append(app_id) or object()
    )

    assert single_instance.acquire("counter", platform="win32") is True
    assert seen == ["counter"]


def test_non_windows_platform_uses_the_lock_file(monkeypatch):
    """非 Windows → 走 flock 锁文件，路径就是 `lock_path(app_id)`（不是别处）。"""
    seen: list[Path] = []
    monkeypatch.setattr(
        single_instance, "_acquire_posix", lambda path: seen.append(path) or object()
    )

    assert single_instance.acquire("counter", platform="darwin") is True
    assert seen == [single_instance.lock_path("counter")]


def test_acquire_degrades_to_allow_when_locking_itself_blows_up():
    """加锁机制自己炸了 → 放行（True）。守卫是来拦多余的窗的，不能反过来
    成为「小程序打不开」的新理由。"""

    def boom(_app_id):
        raise OSError("临时目录不可写")

    assert single_instance.acquire("counter", acquire_lock=boom) is True


def test_acquired_lock_is_kept_alive_by_the_module():
    """拿到的句柄被模块挂住——不挂就会被 GC 回收，文件一关 flock 当场消失，
    「唯一实例」几秒后自己失效。"""
    token = object()
    single_instance.acquire("kept-alive", acquire_lock=lambda _a: token)

    assert any(held is token for held in single_instance._held)


# ---------------------------------------------------------------------------
# 带前台：尽力而为，带不动就静默退出
# ---------------------------------------------------------------------------


def test_raise_existing_window_is_a_noop_off_windows():
    """非 Windows 直接 no-op——开发机上连 FindWindow 都不碰。"""
    assert single_instance.raise_existing_window("某个小程序", platform="darwin") is False


def test_raise_existing_window_focuses_the_window_found_by_title():
    """按标题找到窗口 → 对着那个 HWND 抢前台，成功返回 True。"""
    focused: list[int] = []
    ok = single_instance.raise_existing_window(
        "某个小程序",
        platform="win32",
        find_window=lambda title: 4242 if title == "某个小程序" else 0,
        set_foreground=lambda hwnd: focused.append(hwnd) or True,
    )

    assert ok is True
    assert focused == [4242]


def test_raise_existing_window_does_not_touch_anything_when_no_window_matches():
    """找不到（HWND 0）就不硬来——对 0 号句柄调 SetForegroundWindow 是在
    乱指别人的窗口。"""
    focused: list[int] = []
    ok = single_instance.raise_existing_window(
        "某个小程序",
        platform="win32",
        find_window=lambda _title: 0,
        set_foreground=lambda hwnd: focused.append(hwnd) or True,
    )

    assert ok is False
    assert focused == []


def test_raise_existing_window_reports_a_refused_foreground_switch():
    """SetForegroundWindow 被系统拒绝（前台权限限制，只闪任务栏）→ False。
    调用方据此记日志，但**不因此弹错误框**。"""
    ok = single_instance.raise_existing_window(
        "某个小程序",
        platform="win32",
        find_window=lambda _title: 4242,
        set_foreground=lambda _hwnd: False,
    )

    assert ok is False


def test_raise_existing_window_degrades_on_exceptions():
    """任何异常都只降级——带前台失败绝不能变成第二实例崩溃退出。"""

    def boom(_title):
        raise OSError("user32 不在")

    ok = single_instance.raise_existing_window(
        "某个小程序", platform="win32", find_window=boom
    )

    assert ok is False
