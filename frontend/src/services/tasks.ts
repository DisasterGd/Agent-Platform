import type { Task, TaskStep } from "../types/chat";
import { request } from "./api";
import { streamSSE, type StreamHandlers } from "./chat";

/** v0.3 任务接口：创建/编辑计划/执行(SSE)/取消/查询。 */
export const tasksApi = {
  create: (goal: string, conversationId: number | null) =>
    request<Task>("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ goal, conversation_id: conversationId }),
    }),

  get: (id: number) => request<Task>(`/api/tasks/${id}`),

  listByConversation: (conversationId: number) =>
    request<Task[]>(`/api/tasks?conversation_id=${conversationId}`),

  revise: (id: number, steps: { title: string; detail: string }[]) =>
    request<Task>(`/api/tasks/${id}/steps`, { method: "PUT", body: JSON.stringify({ steps }) }),

  cancel: (id: number) => request<Task>(`/api/tasks/${id}/cancel`, { method: "POST" }),

  execute: (id: number, handlers: StreamHandlers) =>
    streamSSE(`/api/tasks/${id}/execute`, {}, handlers),
};

export type { Task, TaskStep };
