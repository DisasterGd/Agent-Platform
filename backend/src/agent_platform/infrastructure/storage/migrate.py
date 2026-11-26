"""存量文件目录迁移（v0.7 per-user 布局）。

v0.6 及之前文件都落在 data/{category}/ 根目录；v0.7 起按用户落 u{user_id}/ 子目录。
本模块把根目录遗留文件搬入指定用户的目录，幂等可重复执行：

- 目标同名文件已存在 → 跳过搬移（保留两边，绝不覆盖）；
- 只搬根目录的**文件**，不动已有的 u* 子目录；
- 应用启动时会用 dev 用户自动执行一次（local 模式唯一用户），也可用
  scripts/migrate_files_to_user_dirs.py 手动指定用户执行（云端升级场景）。
"""
from __future__ import annotations

import shutil

from agent_platform.infrastructure.storage.local import get_storage


def migrate_root_files_to_user_dirs(user_id: int) -> int:
    """把 uploads/generated 根目录的遗留文件搬入 u{user_id}/，返回搬移的文件数。"""
    storage = get_storage()
    moved = 0
    for category in ("uploads", "generated"):
        target_dir = storage.user_dir(category, user_id)
        for name, _size in storage.iter_files(category):  # user_id=None → 只列根目录文件
            target = target_dir / name
            if target.exists():
                continue  # 同名已存在：跳过，绝不覆盖（幂等）
            target_dir.mkdir(parents=True, exist_ok=True)
            source = storage.resolve(category, name)  # local 模式下 user 未命中会回退根目录
            if source is None or source.parent != storage.user_dir(category, None):
                continue
            try:
                shutil.move(str(source), str(target))
                moved += 1
            except OSError:
                continue
    return moved
