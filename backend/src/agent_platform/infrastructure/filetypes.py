"""v0.5 文件类型词典：一处说清“这是什么文件、能不能当文本读、能不能原样写、归资料库哪一页”。

上传附件解析（attachments）、Agent 写文件（generation/textfiles）、资料库分类
（services/library_service）三处共用这张表，避免每个地方各写一份后缀清单。

设计要点：
- 文本判定**双保险**：后缀在白名单里 → 当文本读；后缀未知但内容嗅探像文本 → 也当文本读
  （程序员的真实文件名五花八门：Makefile、Dockerfile、.gitignore、.env.local、*.cfg）。
- `mimetypes` 在部分平台上把 `.ts` 认成视频（MPEG-TS）、`.py` 没有类型，所以显式覆盖表优先。
"""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path

# 资料库页签与卡片图标的归类口径（kind）
KIND_CODE = "code"
KIND_DOCUMENT = "document"
KIND_IMAGE = "image"
KIND_AUDIO = "audio"
KIND_VIDEO = "video"
KIND_ARCHIVE = "archive"
KIND_OTHER = "other"
KINDS = (KIND_CODE, KIND_DOCUMENT, KIND_IMAGE, KIND_AUDIO, KIND_VIDEO, KIND_ARCHIVE, KIND_OTHER)

KIND_LABELS: dict[str, str] = {
    KIND_CODE: "代码",
    KIND_DOCUMENT: "文档",
    KIND_IMAGE: "图像",
    KIND_AUDIO: "音频",
    KIND_VIDEO: "视频",
    KIND_ARCHIVE: "压缩包",
    KIND_OTHER: "其他",
}

# 编程语言 / 脚本 / 样式 / 配置即代码
# 清单上百项，写成字面量列表会占满几屏；这里用“空白分隔文本块 + split”，是刻意的取舍。
_CODE_BLOCK = """
py pyi pyw ipynb
js jsx mjs cjs ts tsx mts cts vue svelte astro
java kt kts scala swift c cc cpp cxx h hh hpp hxx cs go rs rb php pl pm lua r jl dart nim zig
sh bash zsh fish bat cmd ps1 psm1 psm
sql psql hql graphql gql proto thrift avsc plist
css scss sass less styl
ini cfg conf env properties toml yaml yml json jsonc json5 jsonl ndjson xml xsl xslt
tf tfvars hcl nix bazel bzl cmake mk
asm s v sv vhdl groovy m
"""
CODE_SUFFIXES: frozenset[str] = frozenset(_CODE_BLOCK.split())

# 纯文本类文档
_TEXT_DOC_BLOCK = """
txt text md markdown mdx rst asciidoc adoc org tex bib ltx log
csv tsv tab htm html xhtml xml xsl xslt svg eml mbox ics vcf srt sub ass vtt
"""
TEXT_DOC_SUFFIXES: frozenset[str] = frozenset(_TEXT_DOC_BLOCK.split())

# 可直接当文本读（含代码）——上传正文提取与文本预览都用它
TEXT_SUFFIXES: frozenset[str] = CODE_SUFFIXES | TEXT_DOC_SUFFIXES

# 二进制文档：走专门解析器提取正文
BINARY_DOC_SUFFIXES: frozenset[str] = frozenset(
    ["pdf", "docx", "doc", "pptx", "ppt", "xlsx", "xls", "epub"]
)

IMAGE_SUFFIXES: frozenset[str] = frozenset(
    ["png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff", "tif", "svg", "ico", "avif", "heic", "heif"]
)
AUDIO_SUFFIXES: frozenset[str] = frozenset(
    ["mp3", "wav", "ogg", "oga", "opus", "flac", "aac", "m4a", "mid", "midi", "amr", "wma"]
)
VIDEO_SUFFIXES: frozenset[str] = frozenset(
    ["mp4", "mov", "avi", "mkv", "webm", "m4v", "mpg", "mpeg", "wmv", "flv"]
)
ARCHIVE_SUFFIXES: frozenset[str] = frozenset(
    ["zip", "tar", "gz", "tgz", "bz2", "tbz2", "xz", "txz", "7z", "rar", "jar", "war", "whl", "epub", "apk", "iso"]
)

# Agent 用 write_file 原样写出的白名单：文本/代码/标记/配置（不含二进制）
WRITABLE_SUFFIXES: frozenset[str] = TEXT_SUFFIXES | frozenset(
    ["lock", "patch", "diff", "gitignore", "dockerignore", "editorconfig", "shellcheck"]
)

# 归到“代码”页签的标记/样式文件（is_text 仍成立，只是归类偏好不同）
_CODE_BY_SUFFIX: frozenset[str] = frozenset(
    ["html", "htm", "css", "scss", "less", "styl", "js", "jsx", "ts", "tsx"]
)

# 明确是二进制的后缀（svg 除外：它是纯文本矢量图）
_BINARY_ONLY_SUFFIXES: frozenset[str] = (
    ARCHIVE_SUFFIXES | BINARY_DOC_SUFFIXES | IMAGE_SUFFIXES | AUDIO_SUFFIXES | VIDEO_SUFFIXES
) - {"svg"}

# 无后缀也要认的常见文件名（小写比较）
SPECIAL_NAMES: dict[str, str] = {
    "dockerfile": "code", "makefile": "code", "gnumakefile": "code",
    "license": "document", "readme": "document", "changelog": "document",
    "contributors": "document", "todo": "document", "procfile": "code",
    "cmakelists.txt": "code", "gemfile": "code", "rakefile": "code",
    "justfile": "code", "vagrantfile": "code",
}

# 显式 MIME 覆盖（优先于 mimetypes 的平台差异）
MIME_OVERRIDES: dict[str, str] = {
    "md": "text/markdown", "markdown": "text/markdown", "mdx": "text/markdown",
    "txt": "text/plain", "text": "text/plain", "log": "text/plain",
    "csv": "text/csv", "tsv": "text/tab-separated-values",
    "json": "application/json", "jsonc": "application/json", "json5": "application/json",
    "jsonl": "application/x-ndjson", "ndjson": "application/x-ndjson",
    "yaml": "application/yaml", "yml": "application/yaml",
    "toml": "application/toml", "xml": "application/xml", "html": "text/html",
    "htm": "text/html", "css": "text/css", "scss": "text/x-scss", "less": "text/x-less",
    "js": "text/javascript", "mjs": "text/javascript", "cjs": "text/javascript",
    "ts": "text/plain", "tsx": "text/plain",          # 别被平台认成 video/mp2t
    "vue": "text/plain", "svelte": "text/plain",
    "py": "text/x-python", "rb": "text/x-ruby", "go": "text/x-go",
    "sh": "text/plain", "bash": "text/plain", "zsh": "text/plain",
    "bat": "text/plain", "cmd": "text/plain", "ps1": "text/plain",
    "sql": "application/sql", "java": "text/x-java", "c": "text/plain",
    "h": "text/plain", "cpp": "text/plain", "hpp": "text/plain",
    "ini": "text/plain", "cfg": "text/plain", "conf": "text/plain",
    "env": "text/plain", "properties": "text/plain",
    "svg": "image/svg+xml", "pdf": "application/pdf",
    "zip": "application/zip", "tar": "application/x-tar",
    "gz": "application/gzip", "tgz": "application/gzip",
    "7z": "application/x-7z-compressed", "rar": "application/vnd.rar",
    "jar": "application/java-archive", "whl": "application/octet-stream",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ipynb": "application/x-ipynb+json",
    "epub": "application/epub+zip",
}

_SUFFIX_RE = re.compile(r"\.([a-z0-9]{1,12})$")


def suffix_of(name: str) -> str:
    """规范化后缀（不含点，小写）；无后缀返回 ""。`.env`/`.gitignore` 这类点开头文件名取其“后缀”本身。"""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
    if not base:
        return ""
    if base.startswith(".") and "." not in base[1:]:
        return base[1:]            # .gitignore → gitignore
    m = _SUFFIX_RE.search(base)
    return m.group(1) if m else ""


def base_name(name: str) -> str:
    return (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip().lower()


def content_type_for(name: str, fallback: str = "application/octet-stream") -> str:
    """按后缀推断 MIME；未知后缀回退 mimetypes，再回退 fallback。"""
    ext = suffix_of(name)
    if ext in MIME_OVERRIDES:
        return MIME_OVERRIDES[ext]
    guess = mimetypes.guess_type(name or "")[0]
    return guess or fallback


def _dotfile_family(base: str) -> str:
    """.env.local → env、.gitignore → gitignore（点开头文件按“族”判断）"""
    return base[1:].split(".", 1)[0] if base.startswith(".") else ""


def is_text_name(name: str) -> bool:
    """后缀属于已知文本类（代码/标记/配置/纯文本）。"""
    base = base_name(name)
    if base in SPECIAL_NAMES:
        return True
    if _dotfile_family(base) and _dotfile_family(base) in WRITABLE_SUFFIXES:
        return True                 # .env / .env.local / .gitignore
    return suffix_of(name) in TEXT_SUFFIXES


def looks_like_text(data: bytes, limit: int = 8192) -> bool:
    """内容嗅探：空文件算文本；含 NUL 字节算二进制；控制字符占比过高算二进制。"""
    if not data:
        return True
    head = data[:limit]
    if b"\x00" in head:
        return False
    # UTF-16/32 文本常有 NUL，但上一步已排除；这里统计“不可打印”比例
    odd = sum(1 for b in head if b < 9 or (13 < b < 32))
    return odd / len(head) <= 0.05


def is_readable_text(name: str, data: bytes | None = None, content_type: str = "") -> bool:
    """能否按文本读取（上传正文提取 / 资料库文本预览）。"""
    # 已知二进制后缀先否决：几字节的 .epub/.pdf 样本会被内容嗅探误判成文本
    if suffix_of(name) in _BINARY_ONLY_SUFFIXES:
        return False
    ct = (content_type or "").lower()
    if ct.startswith("text/") or ct in (
        "application/json", "application/xml", "application/yaml", "application/toml",
        "application/x-ipynb+json", "application/x-ndjson", "application/sql",
        "image/svg+xml",
    ):
        return True
    if is_text_name(name):
        return True
    return data is not None and looks_like_text(data)


def is_writable_text(name: str) -> bool:
    """Agent 的 write_file 是否允许原样写出该文件（只放行文本类，二进制交给专用工具）。"""
    base = base_name(name)
    if base in SPECIAL_NAMES:
        return True
    family = _dotfile_family(base)
    if family and family in WRITABLE_SUFFIXES:
        return True                 # .env / .env.local / .gitignore / .dockerignore
    return suffix_of(name) in WRITABLE_SUFFIXES


def classify_kind(name: str, content_type: str = "") -> str:
    """资料库归类：压缩 > 图像/音频/视频 > 代码 > 文档 > 其他。

    既看 MIME（上传时浏览器给的类型）也看后缀（Agent 生成的文件常常没有 MIME），
    任一路命中即可，所以纯按后缀的 .jpg 与只带 image/* 的无名文件都能归对。
    """
    base = base_name(name)
    ext = suffix_of(name)
    ct = (content_type or "").lower()
    if ext in ARCHIVE_SUFFIXES or ext == "epub" or ct in ("application/zip", "application/x-tar", "application/gzip"):
        return KIND_ARCHIVE
    if ext in IMAGE_SUFFIXES or ct.startswith("image/"):
        return KIND_IMAGE
    if ext in AUDIO_SUFFIXES or ct.startswith("audio/"):
        return KIND_AUDIO
    if ext in VIDEO_SUFFIXES or ct.startswith("video/"):
        return KIND_VIDEO
    if base in SPECIAL_NAMES:
        return SPECIAL_NAMES[base]
    # 前端三件套按“程序员的习惯”归代码，而不是文档
    if ext in _CODE_BY_SUFFIX or ext in CODE_SUFFIXES:
        return KIND_CODE
    if base.startswith(".") and is_writable_text(base):
        return KIND_CODE        # .env / .env.local / .gitignore / .dockerignore
    if ext in TEXT_DOC_SUFFIXES or ext in BINARY_DOC_SUFFIXES:
        return KIND_DOCUMENT
    if ct.startswith("text/"):
        return KIND_DOCUMENT
    return KIND_OTHER


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, KIND_LABELS[KIND_OTHER])


def badge_label(name: str) -> str:
    """卡片上的扩展名徽标文字（无后缀时用整名的前 4 个字符）。"""
    ext = suffix_of(name)
    if ext:
        return ext[:4].upper()
    return (base_name(name) or "?")[:4].upper()


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    return f"{size / 1024 / 1024 / 1024:.2f} GB"


# 给模型看的“可写格式”清单（write_file 工具描述里用，避免它去猜冷僻后缀）
WRITABLE_HINT = (
    "常见可用后缀：.txt .md .csv .tsv .json .jsonl .yaml .toml .ini .env .log "
    ".html .css .scss .xml .svg .tex .sql .graphql "
    ".py .js .ts .jsx .tsx .vue .svelte .java .kt .swift .c .h .cpp .hpp .cs .go "
    ".rs .rb .php .lua .r .dart .sh .bash .ps1 .bat .dockerfile .makefile；"
    "无后缀的 Dockerfile / Makefile / README / LICENSE 同样支持。"
)


def normalize_path(path: str, default_name: str = "file.txt") -> str:
    """把模型给的相对路径清洗成 zip 内的安全相对路径（拒绝绝对路径与 .. 上跳）。"""
    raw = (path or "").replace("\\", "/").strip().lstrip("/")
    parts = [p for p in raw.split("/") if p and p not in (".", "..")]
    if not parts:
        parts = [default_name]
    cleaned = []
    for i, part in enumerate(parts):
        part = re.sub(r'[<>:"|?*\x00-\x1f]+', "_", part).strip().rstrip(". ")
        if not part:
            part = f"part_{i}"
        cleaned.append(part[:120])
    return "/".join(cleaned)


def path_suffix(path: str) -> str:
    """zip 内路径的后缀判定用（等价 suffix_of，语义更明确）。"""
    return suffix_of(Path((path or "").replace("\\", "/")).name)
