import type { Project } from "../types/chat";
import { request } from "./api";

/** v0.4 项目接口：左侧项目栏管理。 */
export const projectsApi = {
  list: () => request<Project[]>("/api/projects"),

  create: (name: string, description = "") =>
    request<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),

  update: (id: number, patch: { name?: string; description?: string; pinned?: boolean }) =>
    request<Project>(`/api/projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  remove: async (id: number) => {
    const response = await fetch(`/api/projects/${id}`, { method: "DELETE" });
    if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
  },
};
