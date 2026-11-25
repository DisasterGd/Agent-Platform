"""v0.6.1 知识库：切块/分词/片段纯函数、search_knowledge 工具形状、预设子集约束。"""
from __future__ import annotations

import json

from agent_platform.services.knowledge_service import (
    _snippet,
    chunk_text,
    tokenize_query,
)
from agent_platform.services.settings_service import PRESETS
from agent_platform.tools.builtin.knowledge_search import build_search_knowledge
from agent_platform.tools.builtin.registry import build_default_registry

# ---------- chunk_text ----------


def test_chunk_packs_paragraphs_without_loss() -> None:
    paras = [f"第{i}段。" + "填充文字内容" * 30 for i in range(8)]
    chunks = chunk_text("\n\n".join(paras))
    assert chunks
    joined = "".join(chunks)
    for para in paras:
        assert para in joined
    assert all(len(c) <= 2000 for c in chunks)


def test_chunk_empty_and_trivial() -> None:
    assert chunk_text("") == []
    assert chunk_text("  \n\n\t\n") == []
    assert chunk_text("hello") == ["hello"]


def test_chunk_hard_splits_monster_paragraph() -> None:
    chunks = chunk_text("字" * 5000)
    assert len(chunks) >= 3
    assert all(len(c) <= 1900 for c in chunks)
    assert sum(len(c) for c in chunks) >= 4900  # 只丢空白，不丢内容


def test_chunk_respects_max_limit() -> None:
    text = "\n\n".join("段" * 1700 for _ in range(1000))  # 每段独立成块 → 共 1000 块
    assert len(chunk_text(text, max_chunks=400)) == 400


# ---------- tokenize_query ----------


def test_tokenize_cjk_bigrams_skip_question_words() -> None:
    terms = tokenize_query("什么是勒贝格积分")
    assert "什么" not in terms  # 疑问碎词被过滤
    assert "勒贝" in terms and "格积" in terms and "积分" in terms


def test_tokenize_ascii_words_kept_as_whole() -> None:
    assert tokenize_query("DeepSeek  V4 API key") == ["deepseek", "v4", "api", "key"]


def test_tokenize_short_cjk_not_splitted() -> None:
    assert tokenize_query("勒贝格") == ["勒贝格"]


def test_tokenize_caps_at_12() -> None:
    assert len(tokenize_query(" ".join(f"w{i}" for i in range(30)))) <= 12


# ---------- _snippet ----------


def test_snippet_windows_around_first_hit() -> None:
    content = "前" * 300 + "勒贝格" + "后" * 300
    snip = _snippet(content, ["勒贝"])
    assert "勒贝" in snip
    assert len(snip) <= 500  # 带省略号的窗口，不会整块返回
    assert snip.startswith("…") and snip.endswith("…")


def test_snippet_no_hit_returns_head() -> None:
    assert _snippet("abcdef", ["zz"]).startswith("abcdef")


# ---------- search_knowledge 工具 ----------


def test_tool_shapes_hits_and_misses() -> None:
    fn = build_search_knowledge(
        lambda q, p: [{"asset": {"id": 7, "filename": "笔记.md"}, "chunk_index": 2, "score": 5, "snippet": "…勒贝格…"}]
    )
    payload = json.loads(fn("勒贝格").content)
    assert payload["ok"] is True and payload["count"] == 1
    assert payload["results"][0]["filename"] == "笔记.md" and payload["results"][0]["asset_id"] == 7

    miss = json.loads(build_search_knowledge(lambda q, p: [])("x").content)
    assert miss["ok"] is True and miss["count"] == 0 and "note" in miss


def test_tool_catches_search_failure() -> None:
    def boom(query: str, project_only: bool) -> list[dict]:
        raise RuntimeError("数据库断了")

    payload = json.loads(build_search_knowledge(boom)("q").content)
    assert payload["ok"] is False and "数据库断了" in payload["error"]


def test_tool_requires_query() -> None:
    assert json.loads(build_search_knowledge(lambda q, p: [])("  ").content)["ok"] is False


def test_registry_only_injects_knowledge_tool_when_given() -> None:
    assert "search_knowledge" not in build_default_registry().names()
    assert "search_knowledge" in build_default_registry(knowledge_search=lambda q, p: []).names()
    assert "generate_image" in build_default_registry().names()  # v0.6 工具不受影响


# ---------- 预设子集约束（问题清单 #2） ----------


def test_vision_models_are_subset_of_chat_models() -> None:
    for pid, preset in PRESETS.items():
        if pid == "custom":
            continue
        assert set(preset["vision_models"]) <= set(preset["models"]), f"{pid} 视觉模型必须出现在主模型下拉里"
        assert preset["model"] in preset["models"]
