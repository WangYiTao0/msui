# -*- mode: python ; coding: utf-8 -*-
# 冻结冒烟探针的 spec。**关键点：这里对 msui 的资源与元数据零配置**——
# tokens.css / base.css / dist-info 全由 msui 包自带的 pyinstaller40 hook
# （src/msui/_pyinstaller/hook-msui.py）收齐，这正是被验的机制本身。
# datas 只声明探针自己持有的页面目录（出路二：页面归消费者）。
import os

a = Analysis(
    [os.path.join(SPECPATH, "probe.py")],
    pathex=[],
    binaries=[],
    datas=[(os.path.join(SPECPATH, "pages"), "pages")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="probe",
    debug=False,
    strip=False,
    upx=False,
    console=True,  # 冒烟读数走 stdout，必须是控制台程序
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="probe",
)
