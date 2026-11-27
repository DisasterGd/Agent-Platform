/** v0.7.4 本地项目接口：注册/管理真实目录 + 选目录浏览（仅 local 模式，cloud 下端点 404）。 */
import type { LocalProject } from "../types/chat";
import { request } from "./api";

export interface BrowseResult {
  path: string;
  parent: string;
  dirs: string[];
}

export const localProjectsApi = {
  list: () => request<LocalProject[]>("/api/local-projects"),

  create: (root_path: string, title = "") =>
    request<LocalProject>("/api/local-projects", {
      method: "POST",
      body: JSON.stringify({ root_path, title }),
    }),

  update: (id: number, patch: { title?: string; allow_write?: boolean }) =>
    request<LocalProject>(`/api/local-projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  /** 注销注册（磁盘文件不受影响）。 */
  remove: async (id: number) => {
    const response = await fetch(`/api/local-projects/${id}`, { method: "DELETE" });
    if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
  },

  /** 选目录弹窗起点：Windows 盘符列表。 */
  drives: () => request<{ drives: string[] }>("/api/local-projects/drives"),

  /** 逐层浏览子目录（忽略 node_modules/.git 等噪音）。 */
  browse: (path: string) =>
    request<BrowseResult>(`/api/local-projects/browse?path=${encodeURIComponent(path)}`),
};
