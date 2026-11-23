"""generate_image 工具（v0.6 生图角色）。

模型侧只描述“画什么”，用哪个供应商哪个模型由用户在「设置 → 模型角色 → 图像生成」里预先配置——
这正是角色化的意义：生图交给真正的多模态厂商，主模型负责理解需求与组织对话。

与文本工具同规：纯函数、不碰数据库；产物放 ToolResult.artifacts，由服务层登记进资料库。
"""
from __future__ import annotations

import json

from agent_platform.infrastructure.filetypes import classify_kind, human_size
from agent_platform.infrastructure.imagegen import ImageGenError, generate_image
from agent_platform.infrastructure.storage.local import get_storage
from agent_platform.models.factory import create_image_config
from agent_platform.tools.registry import ToolResult

#: 各家 OpenAI 兼容端点的公约数尺寸
SIZES = ("1024x1024", "1024x768", "768x1024")
PROMPT_LIMIT = 1000

GENERATE_IMAGE_DESCRIPTION = (
    "根据文字描述生成一张图片（使用用户在设置中配置的“图像生成角色”，与你自己是不同的模型）。"
    "适合插画、概念图、海报、头像等；prompt 用一段连贯的文字描述画面主体、风格、构图与配色。"
    "图片会自动出现在对话中并可从资料库下载。未配置生图角色时会返回错误说明——此时如实告知用户"
    "去「设置 → 模型角色」配置，不要反复重试。画精确的图表/流程图/架构图不要用本工具（模型看不清文字），"
    "改用 generate_file/write_file 输出 Mermaid 或 SVG。"
)
GENERATE_IMAGE_PARAMETERS: dict = {
    "type": "object",
    "properties": {
        "prompt": {
            "type": "string",
            "description": f"画面描述（不超过 {PROMPT_LIMIT} 字）：主体、风格、构图、配色",
        },
        "size": {
            "type": "string",
            "enum": list(SIZES),
            "description": "尺寸，默认 1024x1024（方形）；横图 1024x768、竖图 768x1024",
        },
        "name": {
            "type": "string",
            "description": "可选文件名主干（不含扩展名），如 poster_spring；省略则自动命名",
        },
    },
    "required": ["prompt"],
}

_EXT_BY_MIME = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}


def _fail(error: str) -> ToolResult:
    return ToolResult(content=json.dumps({"ok": False, "error": error}, ensure_ascii=False))


async def generate_image_tool(prompt: str, size: str = "1024x1024", name: str = "") -> ToolResult:
    cfg = create_image_config()
    if cfg is None:
        return _fail("尚未配置生图角色：请在「设置 → 模型角色 → 图像生成」选择供应商与模型，并配好该供应商的 API Key")
    text = (prompt or "").strip()
    if not text:
        return _fail("prompt 不能为空")
    if len(text) > PROMPT_LIMIT:
        text = text[:PROMPT_LIMIT]
    if size not in SIZES:
        size = "1024x1024"
    try:
        data, content_type = await generate_image(cfg["base_url"], cfg["api_key"], cfg["model"], text, size)
    except ImageGenError as exc:
        return _fail(f"生图失败：{exc}")

    safe_name = "".join(ch for ch in (name or "").strip() if ch.isalnum() or ch in "-_")[:40] or "生成图像"
    filename = f"{safe_name}.{_EXT_BY_MIME.get(content_type, 'png')}"
    stored = get_storage().save("generated", filename, data, content_type)
    artifact = {
        "filename": stored.stored_name,
        "stored_name": stored.stored_name,
        "url": stored.url,
        "format": stored.stored_name.rpartition(".")[2] or "png",
        "content_type": stored.content_type,
        "category": stored.category,
        "size": stored.size,
        "kind": classify_kind(filename, content_type),
    }
    return ToolResult(
        content=json.dumps(
            {
                "ok": True,
                "filename": stored.stored_name,
                "url": stored.url,
                "size_label": human_size(stored.size),
                "content_type": stored.content_type,
                "generated_by": f"{cfg['provider']}/{cfg['model']}",
                "note": "图片已生成并附在回复中；不满意可调整 prompt 再生成一次",
            },
            ensure_ascii=False,
        ),
        artifacts=[artifact],
    )
