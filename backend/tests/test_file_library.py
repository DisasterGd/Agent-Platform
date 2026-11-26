"""v0.5 文件类型扩展与资料库测试：sqlite 内存库 + 临时存储目录，不依赖 MySQL 与网络。

覆盖：
- write_file：文本/代码原样写出、非文本与无扩展名拒绝、路径清洗；
- create_zip：内联 + 引用已生成文件、二进制拒绝、引用缺失跳过；
- 附件正文提取：宽文本类型（含代码、无后缀 Makefile、内容嗅探）；
- 资料库：登记幂等、筛选与计数、重命名保留后缀并重分类、项目联动校验、
  删除（连带磁盘文件 / 仅移除记录）、存量扫描、附件归属补写、预览。
"""
from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent_platform.infrastructure import filetypes as ft
from agent_platform.infrastructure.attachments import extract_text
from agent_platform.infrastructure.database.base import Base
from agent_platform.infrastructure.database.models import Project, User
from agent_platform.infrastructure.storage import local as local_storage
from agent_platform.infrastructure.storage.local import LocalStorage
from agent_platform.services.library_service import LibraryService
from agent_platform.tools.builtin.archive import create_zip
from agent_platform.tools.builtin.textfile import write_file


@pytest.fixture()
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalStorage:
    store = LocalStorage(tmp_path)
    monkeypatch.setattr(local_storage, "_storage", store)
    return store


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Session, int]:
    monkeypatch.setattr(local_storage, "_storage", LocalStorage(tmp_path))
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    user = User(username="tester")
    session.add(user)
    session.commit()
    return session, user.id


def _payload(result) -> dict:
    return json.loads(result.content)


# ---------- 类型词典 ----------

def test_kind_classification_covers_real_names() -> None:
    assert ft.classify_kind("main.py") == "code"
    assert ft.classify_kind("App.tsx") == "code"
    assert ft.classify_kind("index.html") == "code"      # 前端三件套按程序员习惯归代码
    assert ft.classify_kind("style.css") == "code"
    assert ft.classify_kind("report.pdf") == "document"
    assert ft.classify_kind("photo.jpg") == "image"       # 无 MIME 时靠后缀
    assert ft.classify_kind("blob", "image/png") == "image"
    assert ft.classify_kind("voice.mp3") == "audio"
    assert ft.classify_kind("demo.mp4") == "video"
    assert ft.classify_kind("project.zip") == "archive"
    assert ft.classify_kind("Dockerfile") == "code"       # 无后缀常见名
    assert ft.classify_kind(".gitignore") == "code"
    assert ft.classify_kind(".env.local") == "code"
    assert ft.classify_kind("mystery") == "other"


def test_text_detection_uses_suffix_then_sniff() -> None:
    assert ft.is_text_name("src/app/main.py")
    assert ft.is_text_name("Makefile")
    assert ft.is_readable_text("notes", b"hello world\n", "")      # 无后缀但内容像文本
    assert not ft.is_readable_text("data", b"\x00\x01\x02binary", "")
    assert ft.is_writable_text("docker-compose.yml")
    assert not ft.is_writable_text("app.exe")
    assert not ft.is_writable_text("photo.png")


# ---------- write_file ----------

def test_write_file_writes_content_verbatim(storage: LocalStorage) -> None:
    result = write_file(filename="src/app/main.py", content="print('你好')\n")
    payload = _payload(result)
    assert payload["ok"] is True
    artifact = result.artifacts[0]
    assert artifact["stored_name"] == "main.py"
    assert artifact["kind"] == "code"
    assert artifact["category"] == "generated"
    assert artifact["url"] == "/api/files/generated/main.py"
    # 原样落盘：不加 Markdown 标题、不加代码围栏
    disk = storage.resolve("generated", "main.py")
    assert disk is not None and disk.read_text("utf-8") == "print('你好')\n"


def test_write_file_rejects_unsupported_names(storage: LocalStorage) -> None:
    assert _payload(write_file(filename="evil.exe", content="x"))["ok"] is False
    assert _payload(write_file(filename="noextension", content="x"))["ok"] is False
    assert (storage.generated / "noextension").exists() is False


def test_write_file_sanitizes_traversal_and_collision(storage: LocalStorage) -> None:
    result = write_file(filename="../../windows/system32/config.ini", content="a=1")
    name = result.artifacts[0]["stored_name"]
    assert "/" not in name and "\\" not in name and name.endswith(".ini")
    # 同名不覆盖：第二次落盘自动加序号
    second = write_file(filename="config.ini", content="a=2")
    assert second.artifacts[0]["stored_name"] == f"{Path(name).stem} (2).ini"


# ---------- create_zip ----------

def test_create_zip_mixes_inline_and_referenced_files(storage: LocalStorage) -> None:
    written = write_file(filename="app.py", content="print(1)\n")
    url = _payload(written)["url"]
    result = create_zip(
        filename="todo-app",
        files=[
            {"path": "src/main.py", "content": "def main(): ...\n"},
            {"path": "README.md", "content": "# Todo\n"},
        ],
        from_files=[url, "不存在的文件.py"],
    )
    payload = _payload(result)
    assert payload["ok"] is True, payload
    assert payload["skipped"] == ["不存在的文件.py"]
    artifact = result.artifacts[0]
    assert artifact["kind"] == "archive"
    assert artifact["stored_name"] == "todo-app.zip"

    disk = storage.resolve("generated", "todo-app.zip")
    assert disk is not None
    with zipfile.ZipFile(BytesIO(disk.read_bytes())) as zf:
        names = set(zf.namelist())
        assert {"src/main.py", "README.md", "app.py"} <= names
        assert zf.read("src/main.py").decode() == "def main(): ...\n"
        assert zf.read("app.py").decode() == "print(1)\n"


def test_create_zip_rejects_binary_entries_and_empty_content(storage: LocalStorage) -> None:
    bad = create_zip(filename="pkg", files=[{"path": "a.png", "content": "\x89PNG"}])
    payload = _payload(bad)
    assert payload["ok"] is False and "a.png" in payload["error"]
    assert _payload(create_zip(filename="pkg"))["ok"] is False


def test_create_zip_blocks_path_escape_in_entries(storage: LocalStorage) -> None:
    result = create_zip(filename="pkg", files=[{"path": "../../etc/hosts.cfg", "content": "x"}])
    assert _payload(result)["ok"] is True          # 上跳被剥掉，不是被拒绝
    disk = storage.resolve("generated", result.artifacts[0]["stored_name"])
    with zipfile.ZipFile(BytesIO(disk.read_bytes())) as zf:
        names = zf.namelist()
        assert names == ["etc/hosts.cfg"]
        for name in names:
            assert ".." not in name and not name.startswith("/")
    # 完全清洗不出合法条目时直接报错，不会写出空包
    assert _payload(create_zip(filename="pkg2", files=[{"path": "../x/passwd", "content": "y"}]))["ok"] is False


# ---------- 附件正文提取 ----------

def test_extract_text_accepts_broad_text_types(storage: LocalStorage) -> None:
    cases = {
        "component.tsx": "export const A = 1;",
        "Makefile": "all:\n\techo hi",
        ".env": "API_KEY=abc",
        "unknown_ext_zzz": "plain text body",
    }
    for name, body in cases.items():
        storage.save("uploads", name, body.encode("utf-8"), "application/octet-stream")
        assert extract_text("uploads", name, "application/octet-stream") == body

    storage.save("uploads", "blob.bin", b"\x00\x01\x02\x03", "application/octet-stream")
    assert extract_text("uploads", "blob.bin", "application/octet-stream") is None


# ---------- 资料库 ----------

def test_register_is_idempotent_and_list_filters(db: tuple[Session, int], storage: LocalStorage) -> None:
    session, uid = db
    library = LibraryService(session)
    stored = storage.save("generated", "notes.md", b"# hi", "text/markdown")
    first = library.register_saved(stored, user_id=uid, source="chat")
    second = library.register_saved(stored, user_id=uid, source="chat")
    assert first["id"] == second["id"]                      # 同一磁盘文件只登记一次

    other = storage.save("uploads", "app.py", b"x=1", "text/x-python")
    library.register_saved(other, user_id=uid, source="upload")

    out = library.list(uid)
    assert out["total"] == 2
    assert out["kinds"] == {"document": 1, "code": 1}
    assert {i["filename"] for i in library.list(uid, kind="code")["items"]} == {"app.py"}
    assert {i["filename"] for i in library.list(uid, category="uploads")["items"]} == {"app.py"}
    assert {i["filename"] for i in library.list(uid, keyword="app")["items"]} == {"app.py"}
    assert library.list(uid, project_id=None)["total"] == 2  # 全部未归类


def test_rename_keeps_suffix_and_reclassifies(db: tuple[Session, int], storage: LocalStorage) -> None:
    session, uid = db
    library = LibraryService(session)
    asset = library.register_saved(
        storage.save("generated", "a.py", b"print(1)", "text/x-python"), user_id=uid, source="chat"
    )
    # 只输主干 → 自动补回 .py，不丢类型
    renamed = library.rename(asset["id"], uid, "b")
    assert renamed["filename"] == "b.py" and renamed["kind"] == "code"
    # 改成另一种类型 → kind 重算
    assert library.rename(asset["id"], uid, "readme.md")["kind"] == "document"
    # 磁盘名不变：历史下载链接继续可用
    assert storage.resolve("generated", "a.py") is not None


def test_project_linkage(db: tuple[Session, int], storage: LocalStorage) -> None:
    session, uid = db
    library = LibraryService(session)
    mine = Project(user_id=uid, name="我的项目")
    theirs = Project(user_id=uid + 1, name="别人的项目")
    session.add_all([mine, theirs])
    session.commit()

    asset = library.register_saved(
        storage.save("generated", "plan.md", b"x", "text/markdown"), user_id=uid, source="chat"
    )
    assert library.move_project(asset["id"], uid, mine.id)["project_id"] == mine.id
    assert library.list(uid, project_id=mine.id)["total"] == 1
    assert library.list(uid)["projects"] == [{"project_id": mine.id, "count": 1}]
    with pytest.raises(ValueError):
        library.move_project(asset["id"], uid, theirs.id)
    assert library.move_project(asset["id"], uid, None)["project_id"] is None


def test_link_attachments_assigns_ownership_after_sending(
    db: tuple[Session, int], storage: LocalStorage
) -> None:
    session, uid = db
    library = LibraryService(session)
    mine = Project(user_id=uid, name="工作")
    session.add(mine)
    session.commit()

    stored = storage.save("uploads", "spec.md", "# 需求".encode(), "text/markdown")
    asset = library.register_saved(stored, user_id=uid, source="upload")
    assert asset["conversation_id"] is None and asset["project_id"] is None

    library.link_attachments(
        [{"name": "spec.md", "url": stored.url, "content_type": "text/markdown"}],
        user_id=uid,
        conversation_id=42,
        project_id=mine.id,
    )
    updated = library.get(asset["id"], uid)
    assert updated["conversation_id"] == 42 and updated["project_id"] == mine.id


def test_delete_removes_disk_file_or_keeps_it(db: tuple[Session, int], storage: LocalStorage) -> None:
    session, uid = db
    library = LibraryService(session)
    gone = library.register_saved(
        storage.save("generated", "tmp.md", b"x", "text/markdown"), user_id=uid, source="chat"
    )
    kept = library.register_saved(
        storage.save("generated", "keep.md", b"x", "text/markdown"), user_id=uid, source="chat"
    )
    assert library.delete(gone["id"], uid) is True
    assert storage.resolve("generated", "tmp.md") is None
    assert library.delete(kept["id"], uid, remove_file=False) is True
    assert storage.resolve("generated", "keep.md") is not None
    assert library.delete(gone["id"], uid) is False          # 再删返回 False


def test_scan_registers_existing_files_without_records(
    db: tuple[Session, int], storage: LocalStorage
) -> None:
    session, uid = db
    library = LibraryService(session)
    # v0.7 起扫描的是 per-user 目录：直接往 u{uid}/ 里放两个表里没有的文件
    gen_dir = storage.user_dir("generated", uid)
    up_dir = storage.user_dir("uploads", uid)
    gen_dir.mkdir(parents=True, exist_ok=True)
    up_dir.mkdir(parents=True, exist_ok=True)
    (gen_dir / "legacy.docx").write_bytes(b"binary")
    (up_dir / "old.txt").write_text("旧的txt", encoding="utf-8")

    assert library.scan_existing(uid) == 2
    assert library.scan_existing(uid) == 0                   # 幂等：第二次不重复登记
    out = library.list(uid)
    assert out["total"] == 2
    by_name = {i["filename"]: i for i in out["items"]}
    assert by_name["old.txt"]["kind"] == "document"
    assert by_name["old.txt"]["source"] == "library"
    assert by_name["legacy.docx"]["kind"] == "document"


def test_preview_covers_text_archive_image_and_missing(
    db: tuple[Session, int], storage: LocalStorage
) -> None:
    session, uid = db
    library = LibraryService(session)
    text = library.register_saved(
        storage.save("generated", "main.py", b"print(1)\nprint(2)\n", "text/x-python"),
        user_id=uid, source="chat",
    )
    out = library.preview(text["id"], uid)
    assert out["preview"] == "text" and out["content"].count("\n") == 2
    assert out["line_count"] == 3 and out["truncated"] is False   # 结尾换行算一空行

    img = library.register_saved(
        storage.save("uploads", "shot.png", b"\x89PNG\r\n", "image/png"), user_id=uid, source="upload"
    )
    assert library.preview(img["id"], uid)["preview"] == "image"

    packed = create_zip(filename="pkg", files=[{"path": "a.md", "content": "# A"}])
    arc = library.register_saved(
        storage.save("generated", packed.artifacts[0]["filename"], b"placeholder", "application/zip"),
        user_id=uid, source="chat",
    )
    entry = library.preview(arc["id"], uid)
    assert entry["preview"] == "archive"            # 占位内容不是合法 zip → 空目录但不报错
    assert entry["entries"] == []

    binary = library.register_saved(
        storage.save("uploads", "book.epub", b"EPUB", "application/epub+zip"), user_id=uid, source="upload"
    )
    assert library.preview(binary["id"], uid)["preview"] == "binary"

    # 磁盘文件被外部删除：列表标 missing，预览给出 missing
    storage.remove("generated", "main.py")
    listed = {i["stored_name"]: i for i in library.list(uid)["items"]}
    assert listed["main.py"]["missing"] is True
    assert library.preview(text["id"], uid)["preview"] == "missing"


def test_register_artifact_from_tool_event(db: tuple[Session, int], storage: LocalStorage) -> None:
    """工具产出的 artifact（Agent 已补上 tool 名）按 url 找回磁盘文件并登记。"""
    session, uid = db
    library = LibraryService(session)
    mine = Project(user_id=uid, name="项目")
    session.add(mine)
    session.commit()

    result = write_file(filename="service.go", content="package main\n")
    artifact = {**result.artifacts[0], "tool": "write_file"}
    out = library.register_artifact(
        artifact, user_id=uid, source="task", project_id=mine.id, conversation_id=7
    )
    assert out["kind"] == "code" and out["tool"] == "write_file" and out["source"] == "task"
    assert out["size"] > 0 and out["project_id"] == mine.id and out["conversation_id"] == 7
    assert library.register_artifact({"url": "bogus"}, user_id=uid) is None
