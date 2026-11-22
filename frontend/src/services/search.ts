import type { SearchResults } from "../types/chat";
import { request } from "./api";

export type SearchScope = "all" | "conversations" | "tasks" | "projects" | "groups";

/** v0.4.1 全局搜索接口：搜索弹窗按范围检索对话 / 任务 / 项目 / 分组。 */
export const searchApi = {
  query: (q: string, scope: SearchScope) =>
    request<SearchResults>(`/api/search?q=${encodeURIComponent(q)}&scope=${scope}`),
};
