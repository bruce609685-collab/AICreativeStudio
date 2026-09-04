# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：AI Creative Studio onedir 打包。

交付约定（长期规范）：
- onedir（优于 onefile）：解压即用、零安装、脚本可扩展
- 进程名 AICreativeStudio（英文、无版本号）
- about 字段编进 exe 版本资源（version_info.txt）
- 单实例 / 日志 rotation 由代码层保证，打包不改
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve()

# 版本资源（about.py → version_info.txt）
# 每次构建都重新生成：原实现只在文件不存在时生成，about.py 升版本后
# exe 会带着旧版本资源（2026-09-03 实测 v0.1.1 包内仍是 0.1.0）
version_txt = ROOT / "packaging" / "version_info.txt"
import subprocess
subprocess.run(
    [sys.executable, str(ROOT / "packaging" / "build_version.py")],
    check=True, cwd=ROOT,
    stdout=open(version_txt, "w", encoding="utf-8"),
)

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "scripts"), "scripts"),          # 制式脚本（用户可扩展）
        (str(ROOT / "templates"), "templates"),       # 提示词模板
        (str(ROOT / "LICENSE"), "LICENSE"),           # GPL v3 许可文本随包分发
    ],
    # §3.2 内置视频播放：QMediaPlayer 的解码后端是运行时插件加载的，
    # PyInstaller 静态分析发现不了，必须显式声明（缺了会"内置播放无声无息失败"）
    hiddenimports=[
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest", "matplotlib", "numpy", "openpyxl", "lxml",
        "python_docx", "Pygments", "pydantic", "anyio", "httpcore",
        "h11", "httpx", "markdown", "contourpy", "cycler",
        "fonttools", "kiwisolver", "pyparsing", "dateutil",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AICreativeStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,               # GUI 程序：无控制台窗口
    version=str(version_txt),    # about 字段编进 exe
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AICreativeStudio",
)
