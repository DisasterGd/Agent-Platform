import type { ConvGroup } from "../types/chat";
import { request } from "./api";

/** v0.4.1 自定义分组接口：默认分组（项目/任务/未分组）不在此管理。 */
export const groupsApi = {
  list: () => request<ConvGroup[]>("/api/groups"),

  create: (name: string, kind: "group" | "task" = "group") =>
    request<ConvGroup>("/api/groups", { method: "POST", body: JSON.stringify({ name, kind }) }),

  rename: (id: number, name: string) =>
    request<ConvGroup>(`/api/groups/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),

  remove: async (id: number) => {
    const response = await fetch(`/api/groups/${id}`, { method: "DELETE" });
    if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
  },
};
