export type ConversationKind = "chat" | "task";

export interface Conversation {
  id: number;
  title: string;
  pinned: boolean;
  /** v0.4 项目归属：null = 未分组 */
  project_id?: number | null;
  /** v0.7.4 本地项目归属：与 project_id 互斥 */
  local_project_id?: number | null;
  /** v0.4.1 自定义分组归属：null = 按默认分组归类 */
  group_id?: number | null;
  /** v0.4.1 默认分组归类依据：task = 任务模式相关会话 */
  kind?: ConversationKind;
  created_at: string;
  updated_at: string;
}

/** v0.4.1 用户自定义会话分组（默认分组不建记录，由代码归类）。
 * kind: group=根级自定义分组；task=“任务”分区下的子分组（仅任务会话可归入）。 */
export interface ConvGroup {
  id: number;
  user_id: number;
  name: string;
  kind?: "group" | "task";
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: number;
  user_id: number;
  name: string;
  description: string;
  pinned: boolean;
  created_at: string;
  updated_at: string;
}

/** v0.7.4 本地项目：机器上真实目录的注册记录（伪编辑器，仅 local 模式有此功能）。 */
export interface LocalProject {
  id: number;
  title: string;
  root_path: string;
  /** 项目级写入开关：false = Agent 只读（0.7.6 起决定是否注入写工具） */
  allow_write: boolean;
  created_at: string;
  updated_at: string;
}

export interface Memory {
  id: number;
  scope: "global" | "project";
  project_id: number | null;
  category: string;
  title: string;
  content: string;
  /** explicit=用户要求记住 / auto=对话自动提炼 */
  source: "explicit" | "auto" | string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface MemorySavedItem {
  title?: string;
  scope?: string;
  category?: string;
  source?: string;
}

export interface Attachment {
  name: string;
  url: string;
  content_type: string;
}

/** v0.5 资料库条目：磁盘上每个上传/生成文件的记录（重命名只改 filename，url 保持稳定）。 */
export type AssetKind = "code" | "document" | "image" | "audio" | "video" | "archive" | "other";

export interface FileAsset {
  id: number;
  user_id: number;
  project_id: number | null;
  conversation_id: number | null;
  /** uploads = 用户上传；generated = Agent 产出 */
  category: "uploads" | "generated";
  stored_name: string;
  filename: string;
  url: string;
  content_type: string;
  kind: AssetKind;
  kind_label: string;
  /** 扩展名徽标文字，如 PY / MD / ZIP */
  badge: string;
  /** upload / chat / task / library（存量扫描登记） */
  source: string;
  tool: string;
  size: number;
  size_label: string;
  /** 磁盘文件已不存在（外部删除），下载与预览都会失败 */
  missing: boolean;
  created_at: string;
  updated_at: string;
}

export interface AssetListResult {
  items: FileAsset[];
  /** 全库条数 */
  total: number;
  /** 当前筛选条件下的条数 */
  matched: number;
  kinds: Partial<Record<AssetKind, number>>;
  categories: Record<string, number>;
  /** “文件夹”视图计数：project_id 为 null 表示未归类 */
  projects: { project_id: number | null; count: number }[];
}

export interface ZipEntry {
  path: string;
  size: number;
  is_dir: boolean;
}

export interface AssetPreview extends FileAsset {
  preview: "text" | "image" | "audio" | "video" | "archive" | "binary" | "missing";
  content?: string;
  truncated?: boolean;
  line_count?: number;
  entries?: ZipEntry[];
  entry_count?: number;
}

export interface Artifact {
  filename: string;
  url: string;
  format: string;
  content_type?: string;
}

export interface Message {
  id: number;
  conversation_id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  attachments?: Attachment[];
  artifacts?: Artifact[];
  /** 版本链：同一逻辑消息（重新生成/编辑的多个版本）共享 group_id，组内 variant_index 递增。 */
  group_id?: number;
  variant_index?: number;
}

export interface StreamEvent {
  type: string;
  content?: string;
  message?: string;
  name?: string;
  filename?: string;
  url?: string;
  format?: string;
  content_type?: string;
  /** v0.3 任务事件字段 */
  steps?: TaskStep[];
  index?: number;
  title?: string;
  summary?: string;
  error?: string;
  artifacts?: Artifact[];
  status?: Task["status"];
  conversation_id?: number;
  /** v0.4 记忆事件字段 */
  count?: number;
  items?: MemorySavedItem[];
}

export type TaskStatus = "awaiting_approval" | "running" | "completed" | "failed" | "cancelled";
export type TaskStepStatus = "pending" | "running" | "done" | "failed";

export interface TaskStep {
  idx: number;
  title: string;
  detail: string;
  status: TaskStepStatus;
  summary: string;
  error: string;
  artifacts?: Artifact[];
}

export interface Task {
  id: number;
  user_id: number;
  conversation_id: number | null;
  goal: string;
  status: TaskStatus;
  summary: string;
  error: string;
  created_at: string;
  updated_at: string;
  steps: TaskStep[];
}

/** v0.4.1 全局搜索：会话结果附带最近一条消息摘要，任务结果附带步骤进度。 */
export interface ConversationHit extends Conversation {
  snippet: string;
}

export interface TaskHit {
  id: number;
  conversation_id: number | null;
  project_id: number | null;
  goal: string;
  status: TaskStatus;
  updated_at: string;
  steps_total: number;
  steps_done: number;
}

export interface SearchResults {
  conversations: ConversationHit[];
  tasks: TaskHit[];
  projects: Project[];
  groups: ConvGroup[];
}

/** v0.6.1 知识库检索命中：asset 与资料库列表同形状，可直接复用预览链路。 */
export interface KnowledgeHit {
  asset: FileAsset;
  chunk_index: number;
  snippet: string;
  score: number;
  /** v0.6.2 hybrid 混排：嵌入角色开启时为 {vector: cosine, final: 融合分}，关闭/降级时 null（向后兼容） */
  semantic?: { vector: number | null; final: number } | null;
}

export interface KnowledgeSearchResult {
  query: string;
  terms: string[];
  items: KnowledgeHit[];
}

export interface KnowledgeReindexResult {
  scanned: number;
  indexed_assets: number;
  new_chunks: number;
  total_chunks: number;
  /** v0.6.2：嵌入角色开启时本次补嵌入的块数（关闭时恒为 0） */
  embedded_chunks?: number;
}
