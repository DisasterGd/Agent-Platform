# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：便携版单文件 AgentPlatform.exe（v0.9）
# 用法（仓库根目录）：.venv\Scripts\python.exe scripts\build_exe.py
import os
import sys

ROOT = SPECPATH  # 本 spec 放在仓库根目录
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "backend", "src"))

# 运行期资源随包一起打进 exe，解包到 sys._MEIPASS
datas = [
    (os.path.join(ROOT, "frontend", "dist"), "frontend/dist"),
    (os.path.join(ROOT, "backend", "migrations"), "backend/migrations"),
    (os.path.join(ROOT, "backend", "alembic.ini"), "backend"),
    (os.path.join(ROOT, ".env.example"), "."),
]

# SQLAlchemy 的 MySQL 方言是运行时按 URL 动态加载的，静态分析抓不到，显式补上
hiddenimports = [
    "pymysql",
    "sqlalchemy.dialects.mysql",
    "sqlalchemy.dialects.mysql.pymysql",
]

a = Analysis(
    [os.path.join(ROOT, "backend", "run.py")],
    pathex=[os.path.join(ROOT, "backend"), os.path.join(ROOT, "backend", "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AgentPlatform",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 保留控制台窗口（日志可见；双击启动器需要）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
