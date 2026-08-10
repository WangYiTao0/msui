"""样式资产的两态定位与 tokens 解析。

这个模块管两份 css：`tokens.css`（唯一色源，见该文件头注释）与
`base.css`（通用组件默认样式，色彩只许 var(--…) 引用 tokens）。

**资源定位是 dev / frozen 两态**：

  冻结产物   ``sys._MEIPASS/msui/<文件名>``（PyInstaller ``--add-data`` 收进去
             的那份 —— 收集条目请用 ``asset_datas()``，datas 的目的地必须是
             ``BUNDLE_DIR``。在打包配置里手抄第二份路径字符串，就会造成
             「收进去了但程序不去那儿找」）
  开发机     这个包自己所在目录（源码树 / wheel 安装下就是这一份）

谁先存在算谁；都不存在时返回开发机那份路径 —— 调用方（页面装配、测试）
应当当场读不到、当场失败，而不是拿到一个悄悄糊弄出来的空路径。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

__all__ = [
    "ASSET_NAMES",
    "BASE_CSS_NAME",
    "BUNDLE_DIR",
    "TOKENS_CSS_NAME",
    "asset_datas",
    "asset_path",
    "base_css_path",
    "parse_tokens",
    "tokens_css_path",
]

# 资产文件名 —— 只写这一处，别处从这里取。
TOKENS_CSS_NAME = "tokens.css"
BASE_CSS_NAME = "base.css"

# 全部静态资产。**逐文件列名，不用目录通配**：目录通配会把 .py / __pycache__
# 一起收进 datas，而且「收了哪些文件」就没有单一来源可查了。
# 往包里新加静态资产必须同步进这里 —— tests/test_resources.py 与
# tests/test_wheel.py 都盯着。
ASSET_NAMES = (TOKENS_CSS_NAME, BASE_CSS_NAME)

# 冻结产物里这个包的相对目录（"msui"）。从 __package__ 算，不手抄：
# PyInstaller datas 的目的地与运行时查找路径同出这一处。
BUNDLE_DIR = (__package__ or "msui").replace(".", "/")


def _package_dir() -> Path:
    """这个包自己所在的目录（源码树 / wheel 安装下就是这一份）。"""
    return Path(__file__).resolve().parent


def _candidates(name: str) -> list[Path]:
    """两态候选路径，冻结态优先。"""
    found: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)  # 只有 PyInstaller 冻结后才有
    if meipass:
        found.append(Path(meipass) / BUNDLE_DIR / name)
    found.append(_package_dir() / name)
    return found


def asset_datas() -> list[tuple[str, str]]:
    """PyInstaller ``datas`` 用的条目：把全部静态资产收进冻结产物。

    目的地就是上面的 ``BUNDLE_DIR``，与运行时 ``_candidates()`` 的冻结态
    查找路径**同出一处** —— 在 spec 里手写第二份路径字符串，文件会被收进
    产物，但程序不去那儿找。
    """
    return [(str(_package_dir() / name), BUNDLE_DIR) for name in ASSET_NAMES]


def asset_path(name: str) -> Path:
    """这次运行能读到的那份资产文件；候选都不存在时返回开发机那份。

    不抛异常也不返回 None：文件真缺了，让调用方在**读取**的那一刻炸出来，
    错误信息里自然带着它期望的路径。
    """
    candidates = _candidates(name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[-1]


def tokens_css_path() -> Path:
    """`tokens.css`（唯一色源）此刻应读的路径。"""
    return asset_path(TOKENS_CSS_NAME)


def base_css_path() -> Path:
    """`base.css`（通用组件默认样式）此刻应读的路径。"""
    return asset_path(BASE_CSS_NAME)


# ---------------------------------------------------------------------------
# tokens.css 的变量解析器。
#
# 典型用途：主题闸门测试解析出各变量的色值做对比度断言；原生窗口装配代码
# 取 `--win` 之类的底色去染窗口边框。解析器在这，「解析出来的值怎么用、
# 合不合法」归各自调用方判断。
# ---------------------------------------------------------------------------

# 先整块吃掉注释（`/* ... */`，含跨行），再解析变量声明 —— 这样注释写在哪、
# 跨不跨行都不影响解析，不用在变量正则里单独处理注释。
_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
# `--name: value;`，name 允许字母数字和连字符，value 到分号为止（前后空白后面 strip）。
_VAR_RE = re.compile(r"--([a-zA-Z0-9-]+)\s*:\s*([^;]+);")


def parse_tokens(css_text: str) -> dict[str, str]:
    """把 CSS 文本里的自定义属性声明解析成 `{变量名: 值}`（名字不带前导 `--`）。

    口径说明：扫的是**全文任何位置**的 `--name: value;` 声明，不只 `:root`
    块 —— tokens.css 恰好只有一个 `:root` 块，两种口径结果相同；但若文本里
    还有别的规则块声明了变量，这里也会收进来（同名以后出现的为准）。
    容忍变量声明前后的空白、同行或独立成行的 `/* ... */` 注释。
    """
    text_without_comments = _COMMENT_RE.sub("", css_text)
    return {
        match.group(1): match.group(2).strip()
        for match in _VAR_RE.finditer(text_without_comments)
    }
