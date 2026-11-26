import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { knowledgeApi } from "../services/knowledge";
import { libraryApi, type AssetFilters } from "../services/library";
import Markdown from "./Markdown";
import type { AssetKind, AssetPreview, FileAsset, KnowledgeHit, Project } from "../types/chat";

interface Props {
  projects: Project[];
  onClose: () => void;
  /** 二次确认（App 的应用内弹窗），返回是否继续。 */
  confirm: (title: string, message: string, danger?: boolean) => Promise<boolean>;
  /** 从文件跳回产出它的会话：项目联动的反向入口。 */
  onOpenConversation?: (conversationId: number) => void;
}

type Tab = "all" | AssetKind;

const TABS: { key: Tab; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "code", label: "代码" },
  { key: "document", label: "文档" },
  { key: "image", label: "图像" },
  { key: "archive", label: "压缩包" },
  { key: "audio", label: "音频" },
  { key: "video", label: "视频" },
  { key: "other", label: "其他" },
];

const SOURCE_LABELS: Record<string, string> = {
  upload: "我上传的",
  chat: "聊天生成",
  task: "任务生成",
  library: "历史文件",
};

function relTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const min = Math.floor((Date.now() - t) / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const day = Math.floor(hr / 24);
  return day < 30 ? `${day} 天前` : new Date(t).toLocaleDateString();
}

function fmtBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export default function LibraryModal(props: Props) {
  const { projects, onClose, confirm, onOpenConversation } = props;

  const [tab, setTab] = useState<Tab>("all");
  const [source, setSource] = useState<"" | "upload" | "generated">("");
  const [projectId, setProjectId] = useState<number | "none" | undefined>(undefined);
  const [grouped, setGrouped] = useState(false);
  const [keyword, setKeyword] = useState("");
  // v0.6.1 内容检索：在“上传资料的切块”里搜正文（与按文件名搜索互斥）
  const [searchMode, setSearchMode] = useState<"name" | "content">("name");
  const [hits, setHits] = useState<KnowledgeHit[] | null>(null);
  const [hitsLoading, setHitsLoading] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [reindexNote, setReindexNote] = useState("");
  const [kbTick, setKbTick] = useState(0);

  const [items, setItems] = useState<FileAsset[]>([]);
  const [kindCounts, setKindCounts] = useState<Record<string, number>>({});
  const [projectCounts, setProjectCounts] = useState<{ project_id: number | null; count: number }[]>([]);
  const [total, setTotal] = useState(0);
  const [matched, setMatched] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [menuMode, setMenuMode] = useState<"main" | "move">("main");
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [draftName, setDraftName] = useState("");

  // 预览：头部先显示选中的文件，正文等接口回来再填
  const [previewHead, setPreviewHead] = useState<FileAsset | null>(null);
  const [preview, setPreview] = useState<AssetPreview | null>(null);

  const filters = useMemo<AssetFilters>(() => ({
    projectId,
    kind: tab === "all" ? undefined : tab,
    category: source === "generated" ? "generated" : source === "upload" ? "uploads" : undefined,
    q: keyword,
    limit: 400,
  }), [projectId, tab, source, keyword]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setError("");
      const res = await libraryApi.list(filters);
      setItems(res.items);
      setKindCounts(res.kinds as Record<string, number>);
      setProjectCounts(res.projects);
      setTotal(res.total);
      setMatched(res.matched);
    } catch (e) {
      setError(e instanceof Error ? e.message : "资料库加载失败");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  // 最新的 load 放进 ref：挂载时那次“扫描 → 加载”完成时，用户可能已改过筛选，
  // 直接用当时捕获的旧闭包会把新结果盖回去。
  const loadRef = useRef(load);
  loadRef.current = load;

  const mounted = useRef(false);
  useEffect(() => {
    // 首帧：先把磁盘上的历史文件登记进来（幂等），再加载列表
    void libraryApi.scan()
      .catch(() => undefined)
      .finally(() => void loadRef.current());
  }, []);

  // 筛选/搜索变化：防抖 250ms 再请求（首帧由上面的挂载效应负责）
  useEffect(() => {
    if (!mounted.current) { mounted.current = true; return; }
    if (searchMode === "content") return;  // 内容模式走下面的知识库检索，不重拉列表
    const timer = window.setTimeout(() => void load(), 250);
    return () => window.clearTimeout(timer);
  }, [load, searchMode]);

  // v0.6.1 内容检索：防抖 300ms 查知识库切块；项目筛选仅在“具体项目”时生效（未归类无法按项目限定）
  useEffect(() => {
    if (searchMode !== "content") return;
    const q = keyword.trim();
    if (!q) { setHits([]); return; }
    const timer = window.setTimeout(() => {
      setHitsLoading(true);
      knowledgeApi.search(q, {
        projectId: typeof projectId === "number" ? projectId : undefined,
        limit: 24,
      })
        .then(r => setHits(r.items))
        .catch((e: unknown) => { setHits([]); setError(e instanceof Error ? e.message : "内容检索失败"); })
        .finally(() => setHitsLoading(false));
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchMode, keyword, projectId, kbTick]);

  async function runReindex() {
    setReindexing(true);
    setReindexNote("");
    try {
      const r = await knowledgeApi.reindex();
      // v0.6.2：嵌入角色开启时返回本次补嵌入的块数（0/缺省=纯切块，未开向量）
      const emb = r.embedded_chunks ? ` · 补向量 ${r.embedded_chunks} 块` : "";
      setReindexNote(`本次补索引 ${r.indexed_assets} 个文件 · ${r.new_chunks} 块${emb}；库内共 ${r.total_chunks} 块`);
      setKbTick(t => t + 1);  // 让正在进行的关键词检索重跑一次，新块马上能搜到
    } catch (e) {
      setError(e instanceof Error ? e.message : "重建索引失败");
    } finally {
      setReindexing(false);
    }
  }

  function switchMode(next: "name" | "content") {
    if (next === searchMode) return;
    setSearchMode(next);
    setHits(next === "content" ? [] : null);
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (previewHead) { setPreviewHead(null); setPreview(null); }
      else if (menuFor != null) setMenuFor(null);
      else onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [previewHead, menuFor, onClose]);

  const projectName = useCallback(
    (id: number | null) => (id == null ? null : projects.find(p => p.id === id)?.name ?? "已删除的项目"),
    [projects],
  );
  const countFor = useCallback(
    (id: number | null) => projectCounts.find(x => x.project_id === id)?.count ?? 0,
    [projectCounts],
  );

  async function startPreview(asset: FileAsset) {
    setPreviewHead(asset);
    setPreview(null);
    try {
      setPreview(await libraryApi.preview(asset.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "预览失败");
      setPreviewHead(null);
    }
  }

  function closePreview() {
    setPreviewHead(null);
    setPreview(null);
  }

  async function commitRename(asset: FileAsset) {
    const next = draftName.trim();
    setRenamingId(null);
    if (!next || next === asset.filename) return;
    try {
      const updated = await libraryApi.rename(asset.id, next);
      setItems(cur => cur.map(x => (x.id === asset.id ? { ...x, ...updated } : x)));
      setPreviewHead(cur => (cur && cur.id === asset.id ? { ...cur, ...updated } : cur));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "重命名失败");
    }
  }

  async function moveTo(asset: FileAsset, id: number | null) {
    setMenuFor(null);
    setMenuMode("main");
    try {
      await libraryApi.move(asset.id, id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "移动失败");
    }
  }

  async function remove(asset: FileAsset) {
    setMenuFor(null);
    setMenuMode("main");
    const ok = await confirm(
      "删除文件",
      `删除「${asset.filename}」？磁盘上的文件会一并移除，聊天里指向它的下载链接随即失效，此操作不可恢复。`,
    );
    if (!ok) return;
    try {
      await libraryApi.remove(asset.id);
      if (previewHead?.id === asset.id) closePreview();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    }
  }

  const groups = useMemo(() => {
    if (!grouped) return null;
    const map = new Map<number | "none", FileAsset[]>();
    for (const a of items) {
      const key = a.project_id ?? "none";
      const arr = map.get(key);
      if (arr) arr.push(a);
      else map.set(key, [a]);
    }
    const entries = [...map.entries()];
    // 未归类永远排最后，其余按项目名
    entries.sort((x, y) => {
      if (x[0] === "none") return 1;
      if (y[0] === "none") return -1;
      return (projectName(x[0] as number) ?? "").localeCompare(projectName(y[0] as number) ?? "", "zh");
    });
    return entries;
  }, [grouped, items, projectName]);

  function renderMenu(asset: FileAsset) {
    return (
      <>
        <div className="menu-scrim" onClick={() => setMenuFor(null)} />
        <div className="conv-menu card-menu lib-menu">
          {menuMode === "main" ? (<>
            <button type="button" onClick={() => {
              setMenuFor(null); setRenamingId(asset.id); setDraftName(asset.filename);
            }}>重命名</button>
            <a href={asset.url} download={asset.filename}>下载</a>
            {asset.conversation_id != null && onOpenConversation && (
              <button type="button" onClick={() => {
                setMenuFor(null);
                onOpenConversation(asset.conversation_id as number);
                onClose();
              }}>查看来源会话</button>
            )}
            {projects.length > 0 && (
              <button type="button" onClick={() => setMenuMode("move")}>
                {asset.project_id != null ? "更换项目" : "移至项目"}
              </button>
            )}
            {asset.project_id != null && (
              <button type="button" onClick={() => void moveTo(asset, null)}>从项目中移除</button>
            )}
            <button type="button" className="danger" onClick={() => void remove(asset)}>删除</button>
          </>) : (<>
            <button type="button" className="back" onClick={() => setMenuMode("main")}>‹ 返回</button>
            {projects.map(p => (
              <button key={p.id} type="button" className={asset.project_id === p.id ? "cur" : ""}
                onClick={() => void moveTo(asset, p.id)}>
                {p.pinned && "📌"}{p.name}{asset.project_id === p.id && " ✓"}
              </button>
            ))}
          </>)}
        </div>
      </>
    );
  }

  function renderCard(asset: FileAsset) {
    if (renamingId === asset.id) {
      return (
        <input key={asset.id} className="lib-card-name-input" autoFocus value={draftName}
          onChange={e => setDraftName(e.target.value)}
          onBlur={() => void commitRename(asset)}
          onKeyDown={e => {
            if (e.key === "Enter") { e.preventDefault(); (e.currentTarget as HTMLInputElement).blur(); }
            if (e.key === "Escape") setRenamingId(null);
          }} />
      );
    }
    return (
      <div key={asset.id} className={`lib-card ${asset.missing ? "missing" : ""} ${menuFor === asset.id ? "open" : ""}`}>
        <button type="button" className="lib-card-open" data-tip={asset.filename}
          onClick={() => void startPreview(asset)}>
          <span className="lib-badge">{asset.badge}</span>
          <span className="lib-name">{asset.filename}</span>
          <span className="lib-meta">
            <em>{asset.size_label}</em>
            <em>{relTime(asset.created_at)}</em>
            <em>{SOURCE_LABELS[asset.source] ?? asset.source}</em>
            {!grouped && asset.project_id != null && (
              <em className="lib-proj" data-tip={projectName(asset.project_id) ?? ""}>{projectName(asset.project_id)}</em>
            )}
          </span>
          {asset.missing && <span className="lib-warn">文件已不在磁盘上</span>}
        </button>
        <button type="button" className="lib-card-more" aria-label="文件操作"
          onClick={() => {
            setMenuFor(menuFor === asset.id ? null : asset.id);
            setMenuMode("main");
          }}>⋯</button>
        {menuFor === asset.id && renderMenu(asset)}
      </div>
    );
  }

  return (
    <div className="modal-overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal xxwide fixed lib-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">资料库</span>
          <em className="lib-total">
            {matched === total ? `${total} 个文件` : `${matched} / ${total} 个文件`}
          </em>
          <button className="modal-close" data-tip="关闭" onClick={onClose}>×</button>
        </div>

        <div className="lib-tabs">
          {TABS.map(t => (
            <button key={t.key} type="button" className={`s-tab ${tab === t.key ? "on" : ""}`}
              onClick={() => setTab(t.key)}>
              {t.label}
              {t.key !== "all" && kindCounts[t.key] ? <em>{kindCounts[t.key]}</em> : null}
            </button>
          ))}
        </div>

        <div className="lib-toolbar">
          <div className="lib-seg">
            <button type="button" className={`lib-seg-btn ${searchMode === "name" ? "on" : ""}`}
              onClick={() => switchMode("name")}>文件名</button>
            <button type="button" className={`lib-seg-btn ${searchMode === "content" ? "on" : ""}`}
              data-tip="在已上传文件的正文切块里全文检索（Agent 在对话中也能调用）"
              onClick={() => switchMode("content")}>内容</button>
          </div>
          <input className="search-input lib-search"
            placeholder={searchMode === "content" ? "搜索文件正文（知识库切块）…" : "按文件名搜索…"}
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); if (searchMode === "name") void load(); } }} />
          <div className="lib-seg">
            {([["", "全部来源"], ["upload", "我上传的"], ["generated", "Agent 生成"]] as const).map(([key, label]) => (
              <button key={key || "all"} type="button" className={`lib-seg-btn ${source === key ? "on" : ""}`}
                onClick={() => setSource(key)}>{label}</button>
            ))}
          </div>
          <div className="lib-seg">
            <button type="button" className={`lib-seg-btn ${!grouped ? "on" : ""}`} onClick={() => setGrouped(false)}
              data-tip="平铺查看全部文件">平铺</button>
            <button type="button" className={`lib-seg-btn ${grouped ? "on" : ""}`} onClick={() => setGrouped(true)}
              data-tip="按项目分组（文件夹视图）">按项目</button>
          </div>
          <button type="button" className="lib-reindex" onClick={() => void runReindex()} disabled={reindexing}
            data-tip="给还没建过内容索引的上传文件补建切块（已索引的不重复）">
            {reindexing ? "索引中…" : "内容索引"}
          </button>
          {reindexNote && <em className="lib-reindex-note">{reindexNote}</em>}
        </div>

        {projects.length > 0 && (
          <div className="lib-projects">
            <button type="button" className={`lib-chip ${projectId === undefined ? "on" : ""}`}
              onClick={() => setProjectId(undefined)}>全部项目</button>
            {projects.map(p => (
              <button key={p.id} type="button" className={`lib-chip ${projectId === p.id ? "on" : ""}`}
                onClick={() => setProjectId(p.id)}>
              {p.name}<em>{countFor(p.id)}</em>
              </button>
            ))}
            <button type="button" className={`lib-chip ${projectId === "none" ? "on" : ""}`}
              onClick={() => setProjectId("none")}>未归类<em>{countFor(null)}</em></button>
          </div>
        )}

        {error && <div className="error lib-error">{error}</div>}

        <div className="modal-body lib-body">
          {searchMode === "content" ? (
            keyword.trim() === ""
              ? <div className="s-empty">输入关键词，在<b>用户上传资料</b>的正文切块里检索；点击结果可直接预览来源文件。<br />
                  没索引过的文件先点上方“内容索引”补建。</div>
              : hitsLoading
                ? <div className="s-empty">正在检索内容索引…</div>
                : !hits || hits.length === 0
                  ? <div className="s-empty">知识库里没有匹配的内容。<br />
                      换个关键词试试，或点“内容索引”给未索引的上传文件补建切块。</div>
                  : (
                    <div className="lib-kb-list">
                      {hits.map(h => (
                        <button key={`${h.asset.id}-${h.chunk_index}`} type="button" className="lib-kb-hit"
                          data-tip="点击预览来源文件" onClick={() => void startPreview(h.asset)}>
                          <span className="lib-kb-file">{h.asset.filename}<em>块 {h.chunk_index + 1}</em>
                            {h.semantic && (
                              // 关键词分（score）恒显示；semantic 仅嵌入角色开启时出现——“换个说法也命中”的凭据
                              <em className="lib-kb-sem"
                                data-tip={`语义 cosine ${h.semantic.vector ?? "—"} · 融合分 ${h.semantic.final}`}>
                                语义 {h.semantic.vector == null ? "—" : h.semantic.vector.toFixed(2)}
                              </em>
                            )}
                          </span>
                          <span className="lib-kb-snip">{h.snippet}</span>
                        </button>
                      ))}
                    </div>
                  )
          ) : loading && items.length === 0
            ? <div className="s-empty">正在读取资料库…</div>
            : items.length === 0
              ? <div className="s-empty">
                这里还没有{tab === "all" ? "" : `「${TABS.find(t => t.key === tab)?.label}」类`}文件。<br />
                  让 Agent 生成文档、代码或压缩包，或在聊天里上传文件，都会自动登记到资料库。
              </div>
            : grouped
              ? groups?.map(([key, list]) => (
                <section key={String(key)} className="lib-group">
                  <div className="lib-group-head">
                    <span>{key === "none" ? "未归类" : projectName(key as number) ?? "已删除的项目"}</span>
                    <em>{list.length}</em>
                  </div>
                  <div className="lib-grid">{list.map(renderCard)}</div>
                </section>
              ))
              : <div className="lib-grid">{items.map(renderCard)}</div>}
        </div>

        {previewHead && (
          <div className="lib-preview">
            <div className="lib-preview-head">
              <button type="button" className="lib-back" onClick={closePreview}>‹ 返回资料库</button>
              <span className="lib-preview-name" data-tip={previewHead.filename}>
                <em className="lib-badge">{previewHead.badge}</em>{previewHead.filename}
              </span>
              <span className="lib-preview-meta">{previewHead.size_label} · {relTime(previewHead.created_at)}</span>
              <a className="lib-dl" href={previewHead.url} download={previewHead.filename}>下载</a>
              <button type="button" className="modal-close" onClick={closePreview}>×</button>
            </div>
            <div className="lib-preview-body">
              {!preview && <div className="s-empty">正在读取…</div>}
              {preview && preview.preview === "text" && (
                /\.md$/i.test(preview.filename)
                  ? <div className="lib-md"><Markdown content={preview.content ?? ""} /></div>
                  : <pre className="lib-pre">{preview.content}{preview.truncated ? "\n\n…（内容过大，仅显示前面部分）" : ""}</pre>
              )}
              {preview && preview.preview === "image" && (
                <div className="lib-media"><img src={libraryApi.inlineUrl(preview)} alt={preview.filename} /></div>
              )}
              {preview && preview.preview === "audio" && (
                <div className="lib-media"><audio controls src={libraryApi.inlineUrl(preview)} /></div>
              )}
              {preview && preview.preview === "video" && (
                <div className="lib-media"><video controls src={libraryApi.inlineUrl(preview)} /></div>
              )}
              {preview && preview.preview === "archive" && (
                <div className="lib-tree">
                  <div className="lib-tree-head">{preview.entry_count ?? preview.entries?.length ?? 0} 个条目</div>
                  {(preview.entries ?? []).map(e => (
                    <div key={e.path} className={`lib-tree-row ${e.is_dir ? "dir" : ""}`}>
                      <span className="lib-tree-path">{e.path}</span>
                      <em>{e.is_dir ? "目录" : fmtBytes(e.size)}</em>
                    </div>
                  ))}
                  {(preview.entries ?? []).length === 0 && (
                    <div className="sub-empty">读不出目录（可能不是标准 zip，可直接下载）</div>
                  )}
                </div>
              )}
              {preview && preview.preview === "binary" && (
                <div className="s-empty">这类文件不支持在线预览，请下载后打开。</div>
              )}
              {preview && preview.preview === "missing" && (
                <div className="s-empty">磁盘上的文件已经不存在了（可能被手动删除），可从资料库中移除这条记录。</div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
