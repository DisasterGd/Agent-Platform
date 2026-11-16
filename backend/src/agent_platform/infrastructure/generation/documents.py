"""文档生成器：md / docx / pdf。

输入统一为 Markdown 文本（模型输出天然是 Markdown），按目标格式导出。
- md   ：原样拼接标题与内容
- docx ：python-docx，标题 + 段落 + 代码块
- pdf  ：reportlab（内置 CID 字体 STSong-Light，支持中文，无需外置字体文件）
"""
from __future__ import annotations

import html
import re
from io import BytesIO

_FORMATS = {"md", "markdown", "docx", "word", "pdf"}


def _normalize_format(fmt: str) -> str:
    fmt = fmt.strip().lower().lstrip(".")
    if fmt in ("markdown", "md"):
        return "md"
    if fmt == "word":
        return "docx"
    if fmt == "pdf":
        return "pdf"
    if fmt in _FORMATS:
        return fmt
    raise ValueError(f"不支持的文件格式：{fmt}（支持 md / docx / pdf）")


def _safe_name(title: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n]+', "_", title).strip().strip(".")
    return name[:60] or "document"


def _blocks(content: str) -> list[tuple]:
    """把 Markdown 解析成 (type, payload) 列表。"""
    lines = content.split("\n")
    blocks: list[tuple] = []
    in_code = False
    code: list[str] = []
    for line in lines:
        stripped = line.rstrip()
        if stripped.strip().startswith("```"):
            if in_code:
                blocks.append(("code", "\n".join(code)))
                code = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code.append(stripped)
            continue
        s = stripped.strip()
        if not s:
            continue
        if s.startswith("#"):
            level = len(s) - len(s.lstrip("#"))
            blocks.append(("heading", (min(level, 4), s.lstrip("#").strip())))
        elif s.startswith(("- ", "* ", "+ ")):
            blocks.append(("bullet", s[2:].strip()))
        else:
            blocks.append(("para", stripped))
    if in_code and code:
        blocks.append(("code", "\n".join(code)))
    return blocks


class DocumentGenerator:
    def generate(self, fmt: str, title: str, content: str) -> tuple[str, str, bytes]:
        """返回 (filename, content_type, bytes)。"""
        fmt = _normalize_format(fmt)
        filename = f"{_safe_name(title)}.{fmt}"
        if fmt == "md":
            return filename, "text/markdown", self._render_md(title, content).encode("utf-8")
        if fmt == "docx":
            return filename, (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ), self._render_docx(title, content)
        return filename, "application/pdf", self._render_pdf(title, content)

    def _render_md(self, title: str, content: str) -> str:
        return f"# {title}\n\n{content}\n"

    def _render_docx(self, title: str, content: str) -> bytes:
        from docx import Document  # 延迟导入

        doc = Document()
        doc.add_heading(title, 0)
        for kind, payload in _blocks(content):
            if kind == "heading":
                level, text = payload
                doc.add_heading(text, level=level)
            elif kind == "code":
                p = doc.add_paragraph()
                run = p.add_run(payload)
                run.font.name = "Consolas"
            elif kind == "bullet":
                doc.add_paragraph(payload, style="List Bullet")
            else:
                doc.add_paragraph(payload)
        buf = BytesIO()
        doc.save(buf)
        return buf.getvalue()

    def _render_pdf(self, title: str, content: str) -> bytes:
        from reportlab.lib.pagesizes import A4  # 延迟导入
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        font = "STSong-Light"
        title_style = ParagraphStyle(
            "TitleCN", fontName=font, fontSize=20, leading=26, spaceAfter=14
        )
        h_style = ParagraphStyle(
            "HeadingCN", fontName=font, fontSize=14, leading=20, spaceBefore=10, spaceAfter=6
        )
        body = ParagraphStyle(
            "BodyCN", fontName=font, fontSize=11, leading=18, spaceAfter=6
        )
        code_style = ParagraphStyle(
            "CodeCN", fontName="Courier", fontSize=9, leading=12, spaceAfter=6,
            backColor="#f3f4f6", borderPadding=6,
        )
        bullet = ParagraphStyle(
            "BulletCN", fontName=font, fontSize=11, leading=18, leftIndent=14, spaceAfter=3
        )

        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
            topMargin=2 * cm, bottomMargin=2 * cm, title=title,
        )
        story: list = [Paragraph(html.escape(title), title_style), Spacer(1, 4)]
        for kind, payload in _blocks(content):
            if kind == "heading":
                _, text = payload
                story.append(Paragraph(html.escape(text), h_style))
            elif kind == "code":
                story.append(Paragraph(html.escape(payload).replace("\n", "<br/>"), code_style))
            elif kind == "bullet":
                story.append(Paragraph(f"• {html.escape(payload)}", bullet))
            else:
                story.append(Paragraph(html.escape(payload), body))
        doc.build(story)
        return buf.getvalue()
