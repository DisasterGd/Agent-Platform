import type { Task, TaskStep } from "../types/chat";
import { request } from "./api";
import { streamSSE, type StreamHandlers } from "./chat";

/** v0.3 任务接口：创建/编辑计划/执行(SSE)/取消/查询。v0.4.1 任务界面列出全部任务。 */
export const tasksApi = {
  create: (goal: string, conversationId: number | null, projectId: number | null = null) =>
    request<Task>("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ goal, conversation_id: conversationId, project_id: projectId }),
    }),

  /** 全部任务（不带 conversation_id 时）。 */
  list: () => request<Task[]>("/api/tasks"),

  get: (id: number) => request<Task>(`/api/tasks/${id}`),

  listByConversation: (conversationId: number) =>
    request<Task[]>(`/api/tasks?conversation_id=${conversationId}`),

  revise: (id: number, steps: { title: string; detail: string }[]) =>
    request<Task>(`/api/tasks/${id}/steps`, { method: "PUT", body: JSON.stringify({ steps }) }),

  cancel: (id: number) => request<Task>(`/api/tasks/${id}/cancel`, { method: "POST" }),

  /** v0.4.1 任务界面：删除未执行/失败的任务记录（已产生的会话不受影响）。 */
  remove: async (id: number) => {
    const response = await fetch(`/api/tasks/${id}`, { method: "DELETE" });
    if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
  },

  execute: (id: number, handlers: StreamHandlers) =>
    streamSSE(`/api/tasks/${id}/execute`, {}, handlers),
};

export type { Task, TaskStep };
