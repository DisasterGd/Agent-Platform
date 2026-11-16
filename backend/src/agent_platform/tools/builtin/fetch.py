"""抓取网页正文工具：搜索后读取具体页面内容。

解决「搜索只给链接、拿不到具体数据」的问题：模型可先 web_search 拿到链接，
再用本工具打开链接提取正文，从而读到具体数字、最新事实或详细说明。
"""
from __future__ import annotations

import json

import httpx

from agent_platform.tools.registry import ToolResult

FETCH_URL_DESCRIPTION = (
    "抓取一个网页 URL 并提取正文文字。当 web_search 返回的摘要不足以回答时，"
    "用它打开搜索结果里的链接读取具体内容（例如需要具体数字、最新数据、详细说明）。"
    "传入的 url 应取自 web_search 返回结果。"
)
FETCH_URL_PARAMETERS = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "要抓取的网页完整 URL（取自搜索结果）"},
    },
    "required": ["url"],
}

_MAX_CHARS = 8000
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _extract_text(html: str) -> tuple[str, str]:
    """返回 (title, body)。优先用 BeautifulSoup，缺失时退化为标准库。"""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return _extract_text_stdlib(html)

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(
        ["script", "style", "noscript", "nav", "footer", "header", "aside", "iframe", "svg", "form"]
    ):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    body = soup.get_text(" ", strip=True)
    return title, body


def _extract_text_stdlib(html: str) -> tuple[str, str]:
    from html.parser import HTMLParser

    class _Parser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.parts: list[str] = []
            self.title_parts: list[str] = []
            self.skip = 0
            self.in_title = False

        def handle_starttag(self, tag: str, attrs: list) -> None:
            if tag in ("script", "style", "noscript"):
                self.skip += 1
            if tag == "title":
                self.in_title = True

        def handle_endtag(self, tag: str) -> None:
            if tag in ("script", "style", "noscript") and self.skip:
                self.skip -= 1
            if tag == "title":
                self.in_title = False

        def handle_data(self, data: str) -> None:
            if self.in_title:
                self.title_parts.append(data)
            elif not self.skip:
                self.parts.append(data)

    parser = _Parser()
    parser.feed(html)
    title = " ".join("".join(parser.title_parts).split())
    body = " ".join(" ".join(parser.parts).split())
    return title, body


async def fetch_url(url: str) -> ToolResult:
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=_HEADERS)
            resp.raise_for_status()
            final_url = str(resp.url)
            content_type = resp.headers.get("content-type", "")
            if "html" not in content_type and "text" not in content_type:
                return ToolResult(
                    content=json.dumps(
                        {"url": final_url, "error": f"该链接不是网页（{content_type}），无法提取正文"},
                        ensure_ascii=False,
                    )
                )
            html = resp.text
    except Exception as exc:  # noqa: BLE001 — 抓取失败作为结果返回，不中断主流程
        return ToolResult(
            content=json.dumps({"url": url, "error": f"抓取失败：{exc}"}, ensure_ascii=False)
        )

    title, text = _extract_text(html)
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + "…（正文过长，已截断）"
    payload = {"url": final_url, "title": title, "text": text}
    return ToolResult(content=json.dumps(payload, ensure_ascii=False))
