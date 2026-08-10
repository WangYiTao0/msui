# -*- mode: python ; coding: utf-8 -*-
# 最小消费者的 PyInstaller spec。关键点：对 msui 的资源与元数据**零配置**——
# tokens.css / base.css / dist-info 全由 msui 包自带的 pyinstaller40 hook 收齐。
# datas 只声明自己持有的页面目录。
import os

a = Analysis(
    [os.path.join(SPECPATH, "app.py")],
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
    name="app",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # 真实小程序是窗口程序；冒烟只看退出码，不需要控制台
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="app",
)
