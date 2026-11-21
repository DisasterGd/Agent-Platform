"""文件存储命名（v0.3.2）：落盘可读名 = 显示名 = 链接名，重名加序号，非法字符清洗。"""
from __future__ import annotations

import uuid
from pathlib import Path

from agent_platform.config import settings
from agent_platform.infrastructure.storage.local import LocalStorage, _sanitize
from agent_platform.tools.builtin.files import generate_file


def test_sanitize_strips_invalid_chars_and_paths() -> None:
    assert _sanitize(r"C:\x\安全教学示例：文件加解密（替代）.md") == "安全教学示例：文件加解密（替代）.md"
    cleaned = _sanitize("a/b:c*d?.md")
    assert all(ch not in cleaned for ch in "/:?*") and cleaned.endswith(".md")
    assert _sanitize("CON.txt") == "_CON.txt"      # Windows 保留设备名
    assert _sanitize("..") != "" and "/" not in _sanitize("../../etc/passwd")
    assert not _sanitize("结尾点与空格...  ").endswith((" ", "."))


def test_save_uses_readable_name_and_dedupes(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    first = storage.save("generated", "报告.md", b"v1", "text/markdown")
    second = storage.save("generated", "报告.md", b"v2", "text/markdown")
    assert first.stored_name == "报告.md"
    assert second.stored_name == "报告 (2).md"
    assert (tmp_path / "generated" / "报告.md").read_bytes() == b"v1"
    assert (tmp_path / "generated" / "报告 (2).md").read_bytes() == b"v2"
    # 磁盘名可直接经 resolve 找回（下载链接与此一致）
    assert storage.resolve("generated", "报告 (2).md") is not None


def test_resolve_blocks_traversal_but_allows_dots_inside(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    storage.save("uploads", "a..b.md", b"x", "text/markdown")
    assert storage.resolve("uploads", "a..b.md") is not None  # 合法名不误伤
    assert storage.resolve("uploads", "../evil") is None
    assert storage.resolve("uploads", "..") is None
    assert storage.resolve("uploads", "sub/x.md") is None


def test_generate_file_display_equals_disk_name() -> None:
    """端到端：artifact 的 filename / stored_name / 磁盘文件 / URL 尾段四者一致。"""
    title = f"命名一致性测试{uuid.uuid4().hex[:6]}"
    result = generate_file(format="md", title=title, content="正文")
    import json

    payload = json.loads(result.content)
    artifact = result.artifacts[0]
    name = artifact["stored_name"]
    try:
        assert name == artifact["filename"] == payload["filename"]
        assert name == f"{title}.md"
        assert (settings.generated_dir / name).is_file()
        assert artifact["url"].endswith(f"/generated/{name}")
    finally:
        (settings.generated_dir / name).unlink(missing_ok=True)
