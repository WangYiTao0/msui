"""单实例守卫：同一个 app_id 的第二个实例不再开新窗（票 12）。

用户在客户端里连点小程序图标会开出 N 个一模一样的窗口。限制长在小程序
**自己**身上而不是主壳的启动侧——用户完全可能绕过主壳直接双击 exe。

机制选型：

  - **Windows：命名 mutex**（`Local\\msui-<app_id>`，ctypes `CreateMutexW` +
    `ERROR_ALREADY_EXISTS`）。选它不选锁文件的理由是**没有 stale 态**：内核
    对象随进程消亡，上一次崩溃或被任务管理器杀掉不会把小程序永久锁死。
    `Local\\` 前缀 = 当前登录会话内唯一（多用户各开各的，符合直觉）。
  - **POSIX（开发机预演）：flock 锁文件**，行为对齐。必须是 `flock` 而不是
    `fcntl.lockf`：后者按**进程**记账，同进程再拿一次会成功，跟命名 mutex
    的语义对不上。

两条纪律：

  1. **失败方向朝「放行」**：加锁机制自身炸了（权限、临时目录不可写、ctypes
     调用异常……）一律返回「可以开窗」。守卫的职责是拦住多余的窗，不是成为
     「小程序打不开」的新理由。
  2. **绝不弹错误框**：第二实例的用户语义是「我想打开它」，弹个错误框是在
     惩罚这个意图。带前台尽力而为，带不动就静默退出，日志一行说清楚。

锁的生命周期就是进程本身：拿到的句柄挂在模块级 `_held` 上防止被 GC 回收，
**不写任何清理代码**——mutex 与 flock 都随进程消亡自动释放。
"""
from __future__ import annotations

import logging
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

__all__ = [
    "ERROR_ALREADY_EXISTS",
    "MUTEX_PREFIX",
    "acquire",
    "lock_path",
    "mutex_name",
    "raise_existing_window",
]

_log = logging.getLogger(__name__)

# Windows 命名 mutex 的名字前缀：`Local\` = 当前登录会话内唯一。
MUTEX_PREFIX = "Local\\msui-"

# CreateMutexW 之后 GetLastError 的这个值 = 名字已被别人建过（winerror.h）。
ERROR_ALREADY_EXISTS = 183

# 拿到的锁挂在这里：只为防 GC，进程活多久就持有多久，没有对应的释放函数。
_held: list[object] = []

# 注入缝的形状：app_id -> 持有对象（拿到了）或 None（已被别人占）。
AcquireLock = Callable[[str], object | None]


def mutex_name(app_id: str) -> str:
    """Windows 命名 mutex 的完整名字。app_id 用 miniprog.toml 的 id（全局唯一）。"""
    return f"{MUTEX_PREFIX}{app_id}"


def lock_path(app_id: str) -> Path:
    """POSIX 侧锁文件路径：系统临时目录下 `msui-<app_id>.lock`。

    文件本身留不留在盘上无所谓——判据是 flock 持没持住，不是文件存不存在。
    """
    return Path(tempfile.gettempdir()) / f"msui-{app_id}.lock"


def _acquire_posix(path: Path) -> object | None:
    """POSIX：对锁文件加非阻塞独占 flock。拿到返回文件对象，被占返回 None。

    返回的文件对象必须被调用方持有——它一关，flock 就没了。
    """
    import fcntl

    handle = path.open("a+b")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # EWOULDBLOCK/EAGAIN：别人正持着。这是**预期**结果不是故障，
        # 所以在这里就地转成 None，不让它冒到 acquire 的降级分支去。
        handle.close()
        return None
    return handle


def _acquire_windows(app_id: str) -> object | None:
    """Windows：建命名 mutex。名字已存在 = 已有实例在跑，返回 None。

    `use_last_error=True` 是必须的：`ctypes.windll` 那份共享的 kernel32 不保存
    调用后的 GetLastError，中间随便一次别的调用就把 183 冲掉了，守卫会永远
    以为自己是第一实例。
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    # restype 必须显式给 HANDLE：默认按 c_int 收会把 64 位句柄截断成垃圾值。
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.CreateMutexW(None, False, mutex_name(app_id))
    last_error = ctypes.get_last_error()
    if not handle:
        # 建都没建成（名字非法、会话受限……）：交给 acquire 的降级分支放行。
        raise ctypes.WinError(last_error)
    if last_error == ERROR_ALREADY_EXISTS:
        # 已有实例在跑。CreateMutexW 即使遇到已存在也会给一份句柄，
        # 关掉自己这份——第一实例那份还在，锁不受影响。
        kernel32.CloseHandle(handle)
        return None
    return handle


def acquire(
    app_id: str,
    *,
    platform: str | None = None,
    acquire_lock: AcquireLock | None = None,
) -> bool:
    """尝试成为 `app_id` 的唯一实例。True = 可以开窗，False = 已有实例在跑。

    platform/acquire_lock 可注入，纯粹为了在开发机上测出 Windows 的分支选择；
    真实运行一个都不传。
    """
    if acquire_lock is None:
        resolved_platform = platform if platform is not None else sys.platform
        if resolved_platform == "win32":
            acquire_lock = _acquire_windows
        else:
            acquire_lock = lambda aid: _acquire_posix(lock_path(aid))  # noqa: E731

    try:
        held = acquire_lock(app_id)
    except Exception:  # noqa: BLE001 - 见模块 docstring 纪律 1：失败朝「放行」
        _log.info("单实例守卫加锁失败，按「放行」处理（id=%s）", app_id, exc_info=True)
        return True

    if held is None:
        return False
    _held.append(held)  # 只为防 GC；随进程消亡，没有清理代码
    return True


def raise_existing_window(
    title: str,
    *,
    platform: str | None = None,
    find_window: Callable[[str], int] | None = None,
    set_foreground: Callable[[int], bool] | None = None,
) -> bool:
    """尽力把已经开着的那扇窗带到前台。带成了 True，其余一律 False。

    按窗口标题找（标题是 msui 自己建窗时给的，调用方传的就是同一个字符串）。
    Windows 对 `SetForegroundWindow` 有前台权限限制（不在前台的进程抢焦点会
    被系统拒绝，只闪任务栏），所以这里**只是尽力而为**：失败不是错误，调用方
    照样静默退出。
    """
    resolved_platform = platform if platform is not None else sys.platform
    if resolved_platform != "win32":
        _log.info("带前台：非 Windows（%s），no-op", resolved_platform)
        return False

    finder = find_window if find_window is not None else _find_window
    raiser = set_foreground if set_foreground is not None else _set_foreground
    try:
        hwnd = finder(title)
        if not hwnd:
            _log.info("带前台：没找到标题为 %r 的窗口", title)
            return False
        return bool(raiser(hwnd))
    except Exception:  # noqa: BLE001 - 装饰性动作，任何失败都只降级
        _log.info("带前台失败，静默退出", exc_info=True)
        return False


def _find_window(title: str) -> int:
    """真家伙：按窗口标题找顶层窗口的 HWND，没找到返回 0。"""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    return int(user32.FindWindowW(None, title) or 0)


# ShowWindow 的命令码（winuser.h）：把最小化的窗口还原回原来的大小和位置。
SW_RESTORE = 9


def _set_foreground(hwnd: int) -> bool:
    """真家伙：先从最小化还原，再抢前台。返回 SetForegroundWindow 的 BOOL。

    ShowWindow 那一步不能省：窗口被最小化时 SetForegroundWindow 只会让它在
    任务栏闪，用户看不到界面——而用户的意图是「把它打开」。
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.ShowWindow(hwnd, SW_RESTORE)
    return bool(user32.SetForegroundWindow(hwnd))
