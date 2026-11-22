import type { AssetKind, AssetListResult, AssetPreview, FileAsset } from "../types/chat";
import { request } from "./api";

/** 资料库筛选条件：projectId 为 "none" 表示未归类，undefined 表示不限。 */
export interface AssetFilters {
  projectId?: number | "none";
  kind?: AssetKind;
  category?: "uploads" | "generated";
  q?: string;
  limit?: number;
}

function query(filters: AssetFilters = {}): string {
  const params = new URLSearchParams();
  if (typeof filters.projectId === "number") params.set("project_id", String(filters.projectId));
  else if (filters.projectId === "none") params.set("project_id", "none");
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.category) params.set("category", filters.category);
  if (filters.q && filters.q.trim()) params.set("q", filters.q.trim());
  if (filters.limit) params.set("limit", String(filters.limit));
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export const libraryApi = {
  list: (filters: AssetFilters = {}) =>
    request<AssetListResult>(`/api/library/assets${query(filters)}`),

  /** 磁盘上有、库里没有的历史文件登记进来（幂等，打开弹窗时调用一次）。 */
  scan: () => request<{ registered: number }>("/api/library/scan", { method: "POST" }),

  preview: (id: number) => request<AssetPreview>(`/api/library/assets/${id}/preview`),

  rename: (id: number, filename: string) =>
    request<FileAsset>(`/api/library/assets/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ filename }),
    }),

  /** project_id 传 null = 移出项目（与后端“显式传才修改”一致）。 */
  move: (id: number, projectId: number | null) =>
    request<FileAsset>(`/api/library/assets/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ project_id: projectId }),
    }),

  /** keepFile=true 只从资料库移除记录，磁盘文件保留。 */
  remove: async (id: number, keepFile = false) => {
    const response = await fetch(
      `/api/library/assets/${id}${keepFile ? "?keep_file=true" : ""}`,
      { method: "DELETE" },
    );
    if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
  },

  /** 媒体/文本在浏览器里打开（图像预览、音视频播放）需要 inline。 */
  inlineUrl: (asset: FileAsset) => `${asset.url}?inline=1`,
};
