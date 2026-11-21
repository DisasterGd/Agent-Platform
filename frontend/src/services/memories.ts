import type { Memory } from "../types/chat";
import { request } from "./api";

/** v0.4 记忆接口：设置界面的查看/编辑/启停/删除。 */
export const memoriesApi = {
  list: (scope?: "global" | "project", projectId?: number) => {
    const params = new URLSearchParams();
    if (scope) params.set("scope", scope);
    if (projectId !== undefined) params.set("project_id", String(projectId));
    const query = params.toString();
    return request<Memory[]>(`/api/memories${query ? `?${query}` : ""}`);
  },

  create: (input: { content: string; scope?: "global" | "project"; project_id?: number | null; category?: string; title?: string }) =>
    request<Memory>("/api/memories", { method: "POST", body: JSON.stringify(input) }),

  update: (id: number, patch: { title?: string; content?: string; category?: string; enabled?: boolean }) =>
    request<Memory>(`/api/memories/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),

  remove: async (id: number) => {
    const response = await fetch(`/api/memories/${id}`, { method: "DELETE" });
    if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
  },
};
