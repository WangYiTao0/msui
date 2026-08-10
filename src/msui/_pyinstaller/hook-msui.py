"""PyInstaller 收集 msui 的 hook：静态资产 + 发行版元数据，一并进冻结产物。

- ``collect_data_files("msui")``：包目录里的非 .py 文件（tokens.css /
  base.css）收进产物的 ``msui/`` 目录——与 `resources.BUNDLE_DIR` 的运行时
  查找路径一致。
- ``copy_metadata("msui")``：把 dist-info 元数据也收进去。**这一条是刻意
  的**：冻结产物里 `importlib.metadata.version("msui")` 全靠它才拿得到真
  版本号；曾在 macOS 上观察到不写 copy-metadata 也拿到了版本，但那是未解
  之谜（大概率是别的包的 hook 顺带收了），不许依赖——包自带 hook 的独有
  优势就是能把这个坑一次性替所有下游焊死，缺了它下游版本号显示
  0.0.0+unknown，陈旧缓存清理（按版本戳）也会失灵。
"""
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

datas = collect_data_files("msui") + copy_metadata("msui")
