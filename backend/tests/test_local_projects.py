"""v0.7.4 本地项目测试：路径安全（命门）+ 注册/浏览接口 + 归属隔离 + local 模式门禁。

设计文档 docs/design-local-projects.md：safe_resolve 是防路径穿越的唯一真源；
cloud 模式下整组端点必须 404（远程用户没有本机磁盘）。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agent_platform.config import settings
from agent_platform.infrastructure.database.base import Base
from agent_platform.infrastructure.database.models import User
from agent_platform.infrastructure.database.session import get_db
from agent_platform.services import local_project_service as svc
from agent_platform.services.local_project_service import LocalProjectError
from apps.api.dependencies import get_current_user_id
from apps.api.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """本地模式测试环境：两个用户 + HTTP 客户端 + sqlite 内存库（同 test_isolation 惯例）。"""
    monkeypatch.setattr(settings, "auth_mode", "local")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    user_a = User(username="alice")
    user_b = User(username="bob")
    session.add_all([user_a, user_b])
    session.commit()
    ids = {"a": user_a.id, "b": user_b.id}
    current = {"id": ids["a"]}

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user_id] = lambda: current["id"]

    @asynccontextmanager
    async def noop(_app):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", noop)
    with TestClient(app) as test_client:
        yield test_client, ids, current
    app.dependency_overrides.clear()
    session.close()


@pytest.fixture()
def repo_dir(tmp_path) -> str:
    """一个模拟的真实项目目录：src/ 与 README.md。"""
    root = tmp_path / "my-repo"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "node_modules").mkdir()  # 噪音目录：浏览必须忽略
    (root / "README.md").write_text("# demo", encoding="utf-8")
    return str(root)


# ---------- 路径安全（单元） ----------


def test_safe_resolve_allows_inside(tmp_path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    assert svc.safe_resolve(root, "src/app.py") == (root / "src" / "app.py").resolve()
    assert svc.safe_resolve(root, ".") == root.resolve()
    # root 内的绝对路径也接受（对话里出现绝对路径很自然）
    assert svc.safe_resolve(root, str(root / "notes.md")) == (root / "notes.md").resolve()
    # 穿一层 .. 仍在 root 内 → 允许
    assert svc.safe_resolve(root, "src/../README.md") == (root / "README.md").resolve()


def test_safe_resolve_blocks_escape(tmp_path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(LocalProjectError, match="越出"):
        svc.safe_resolve(root, "../../etc/passwd")
    with pytest.raises(LocalProjectError, match="越出"):
        svc.safe_resolve(root, str(outside))  # root 外的绝对路径


def test_normalize_root(tmp_path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    assert svc.normalize_root(str(root)) == root.resolve()
    with pytest.raises(LocalProjectError, match="不存在"):
        svc.normalize_root(str(tmp_path / "nope"))
    a_file = tmp_path / "f.txt"
    a_file.write_text("x", encoding="utf-8")
    with pytest.raises(LocalProjectError, match="不是目录"):
        svc.normalize_root(str(a_file))
    with pytest.raises(LocalProjectError, match="填写"):
        svc.normalize_root("   ")


def test_browse_lists_dirs_only_and_ignores_noise(repo_dir) -> None:
    result = svc.browse(repo_dir)
    assert result["dirs"] == ["docs", "src"]  # node_modules 被忽略、文件不出现、排序稳定
    nested = svc.browse(str(__import__("pathlib").Path(repo_dir) / "src"))
    assert nested["dirs"] == []
    with pytest.raises(LocalProjectError, match="不存在"):
        svc.browse(str(__import__("pathlib").Path(repo_dir) / "missing"))


# ---------- HTTP 接口 ----------


def test_register_and_list_local_projects(client, repo_dir) -> None:
    tc, ids, current = client
    resp = tc.post("/api/local-projects", json={"root_path": repo_dir})
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "my-repo"  # 默认取目录名
    assert body["allow_write"] is True

    resp2 = tc.post("/api/local-projects", json={"root_path": repo_dir})
    assert resp2.status_code == 400  # 重复注册

    listing = tc.get("/api/local-projects").json()
    assert [p["title"] for p in listing] == ["my-repo"]

    # 另一用户看不到、改不了、删不了
    current["id"] = ids["b"]
    assert tc.get("/api/local-projects").json() == []
    pid = body["id"]
    assert tc.patch(f"/api/local-projects/{pid}", json={"allow_write": False}).status_code == 404
    assert tc.delete(f"/api/local-projects/{pid}").status_code == 404

    # 归属者：改名 + 关写入开关
    current["id"] = ids["a"]
    patched = tc.patch(f"/api/local-projects/{pid}", json={"title": "我的仓库", "allow_write": False})
    assert patched.status_code == 200 and patched.json()["allow_write"] is False

    # 注销：只删注册行（磁盘文件由 tmp_path 生命周期管理，这里只验接口）
    assert tc.delete(f"/api/local-projects/{pid}").status_code == 204
    assert tc.get("/api/local-projects").json() == []


def test_register_rejects_bad_root(client, tmp_path) -> None:
    tc, _ids, _current = client
    assert tc.post("/api/local-projects", json={"root_path": str(tmp_path / "nope")}).status_code == 400
    assert tc.post("/api/local-projects", json={"root_path": ""}).status_code == 400


def test_drives_and_browse_endpoints(client, repo_dir) -> None:
    tc, _ids, _current = client
    drives = tc.get("/api/local-projects/drives")
    assert drives.status_code == 200 and "drives" in drives.json()

    import pathlib

    src = pathlib.Path(repo_dir) / "src"
    browse = tc.get("/api/local-projects/browse", params={"path": str(src)})
    assert browse.status_code == 200 and browse.json()["dirs"] == []
    bad = tc.get("/api/local-projects/browse", params={"path": str(src / "gone")})
    assert bad.status_code == 400


def test_cloud_mode_hides_local_projects(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """双保险的第二层：挂载在 import 时决定，路由内依赖在请求时决定——cloud 必须 404。"""
    tc, _ids, _current = client
    monkeypatch.setattr(settings, "auth_mode", "cloud")
    assert tc.get("/api/local-projects").status_code == 404
    assert tc.post("/api/local-projects", json={"root_path": "D:/x"}).status_code == 404


# ---------- v0.7.5 伪编辑器：树 + 文件读取 ----------


def _make_editor_tree(tmp_path):
    """一个内容多样的演示项目：md/py/二进制/图片/超大文本/噪音目录。"""
    import struct
    import zlib

    root = tmp_path / "editor-demo"
    (root / "src").mkdir(parents=True)
    (root / "node_modules").mkdir()  # 噪音
    (root / "README.md").write_text("# 你好\n\n正文", encoding="utf-8")
    (root / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "blob.bin").write_bytes(bytes(range(256)) * 4)  # 无后缀二进制（NUL 多）
    (root / "logo.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + struct.pack(">IIB", 1, 1, 8) + zlib.crc32(b"IHDR").to_bytes(4, "big")
    )  # 不完整 PNG 无所谓——只验后缀与大小分支
    (root / "big.log").write_text("x" * (513 * 1024), encoding="utf-8")  # 超大文本
    return root


def test_list_layer_dirs_first_and_ignores_noise(tmp_path) -> None:
    root = _make_editor_tree(tmp_path)
    layer = svc.list_layer(root, ".")
    names = [e["name"] for e in layer["entries"]]
    assert names[0] == "src"                       # 目录在前
    assert "node_modules" not in names             # 噪音不出现
    readme = next(e for e in layer["entries"] if e["name"] == "README.md")
    assert readme["type"] == "file" and readme["size"] > 0
    assert layer["truncated"] is False
    nested = svc.list_layer(root, "src")
    assert [e["name"] for e in nested["entries"]] == ["app.py"]
    with pytest.raises(LocalProjectError, match="越出"):
        svc.list_layer(root, "../../outside")
    with pytest.raises(LocalProjectError, match="不是目录"):
        svc.list_layer(root, "README.md")


def test_read_file_text_and_truncation(tmp_path) -> None:
    root = _make_editor_tree(tmp_path)
    md = svc.read_file(root, "README.md")
    assert md["kind"] == "text" and "你好" in md["content"] and md["mime"] == "text/markdown"
    big = svc.read_file(root, "big.log")
    assert big["kind"] == "text" and big["content"] is None and big["truncated"] is True
    py = svc.read_file(root, str(root / "src" / "app.py"))  # root 内绝对路径也接受
    assert py["kind"] == "text" and "print" in py["content"]


def test_read_file_image_and_binary(tmp_path) -> None:
    root = _make_editor_tree(tmp_path)
    img = svc.read_file(root, "logo.png")
    assert img["kind"] == "image" and img["content"].startswith("data:image/png;base64,")
    blob = svc.read_file(root, "blob.bin")
    assert blob["kind"] == "binary" and blob["content"] is None


def test_read_file_rejects_missing_and_dir(tmp_path) -> None:
    root = _make_editor_tree(tmp_path)
    with pytest.raises(LocalProjectError, match="不存在"):
        svc.read_file(root, "nope.md")
    with pytest.raises(LocalProjectError, match="是目录"):
        svc.read_file(root, "src")


def test_tree_and_file_endpoints(client, tmp_path) -> None:
    tc, ids, current = client
    root = _make_editor_tree(tmp_path)
    pid = tc.post("/api/local-projects", json={"root_path": str(root)}).json()["id"]

    layer = tc.get(f"/api/local-projects/{pid}/tree")
    assert layer.status_code == 200
    assert "node_modules" not in [e["name"] for e in layer.json()["entries"]]

    nested = tc.get(f"/api/local-projects/{pid}/tree", params={"path": "src"})
    assert [e["name"] for e in nested.json()["entries"]] == ["app.py"]

    md = tc.get(f"/api/local-projects/{pid}/file", params={"path": "README.md"})
    assert md.status_code == 200 and md.json()["kind"] == "text"

    missing = tc.get(f"/api/local-projects/{pid}/file", params={"path": "gone.txt"})
    assert missing.status_code == 404
    escape = tc.get(f"/api/local-projects/{pid}/tree", params={"path": "../../.."})
    assert escape.status_code == 400

    # 另一用户不可见
    current["id"] = ids["b"]
    assert tc.get(f"/api/local-projects/{pid}/tree").status_code == 404
    assert tc.get(f"/api/local-projects/{pid}/file", params={"path": "README.md"}).status_code == 404
