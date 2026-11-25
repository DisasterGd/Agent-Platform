import type { KnowledgeReindexResult, KnowledgeSearchResult } from "../types/chat";
import { request } from "./api";

/** v0.6.1 知识库：内容检索与补索引（只覆盖用户上传的资料）。 */
export const knowledgeApi = {
  search: (q: string, opts?: { projectId?: number; limit?: number }) => {
    const params = new URLSearchParams({ q });
    if (opts?.projectId !== undefined) params.set("project_id", String(opts.projectId));
    if (opts?.limit) params.set("limit", String(opts.limit));
    return request<KnowledgeSearchResult>(`/api/knowledge/search?${params.toString()}`);
  },
  reindex: () => request<KnowledgeReindexResult>("/api/knowledge/reindex", { method: "POST" }),
};
