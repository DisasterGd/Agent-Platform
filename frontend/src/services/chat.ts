import type { Artifact, Attachment, Conversation, Message, StreamEvent } from "../types/chat";
import { request } from "./api";

export interface StreamHandlers {
  onDelta: (text: string) => void;
  onToolStart?: (name: string) => void;
  onToolEnd?: (name: string) => void;
  onArtifact?: (artifact: Artifact) => void;
  /** 通用事件旁路（v0.3 任务事件等），每种事件都会回调。 */
  onEvent?: (event: StreamEvent) => void;
}

/** 发起 SSE 流式请求并逐事件回调。 */
export async function streamSSE(url: string, body: unknown, handlers: StreamHandlers) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
  if (!response.body) throw new Error("浏览器不支持响应流");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        for (const line of frame.split(/\r?\n/)) {
          if (!line.startsWith("data:")) continue;
          const event = JSON.parse(line.slice(5).trim()) as StreamEvent;
          handlers.onEvent?.(event);
          switch (event.type) {
            case "text_delta":
              if (event.content) handlers.onDelta(event.content);
              break;
            case "tool_started":
              handlers.onToolStart?.(event.name || "");
              break;
            case "tool_completed":
              handlers.onToolEnd?.(event.name || "");
              break;
            case "artifact_ready":
              handlers.onArtifact?.({
                filename: event.filename || "",
                url: event.url || "",
                format: event.format || "",
                content_type: event.content_type,
              });
              break;
            case "error":
              throw new Error(event.message || "流式响应错误");
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/** 聊天相关接口与流式请求。 */
export const chatApi = {
  listConversations: () => request<Conversation[]>("/api/conversations"),

  createConversation: (title = "新会话", projectId: number | null = null) =>
    request<Conversation>("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ title, project_id: projectId }),
    }),

  updateConversation: (id: number, patch: { title?: string; pinned?: boolean }) =>
    request<Conversation>(`/api/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  deleteConversation: async (id: number) => {
    const response = await fetch(`/api/conversations/${id}`, { method: "DELETE" });
    if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
  },

  listMessages: (id: number) =>
    request<Message[]>(`/api/conversations/${id}/messages`),

  /** 上传文件/图片，返回可在消息中引用的附件信息。 */
  async uploadFile(file: File): Promise<Attachment> {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch("/api/files", { method: "POST", body: form });
    if (!response.ok) {
      throw new Error((await response.text()) || `HTTP ${response.status}`);
    }
    const json = (await response.json()) as {
      filename: string;
      url: string;
      content_type: string;
    };
    return { name: json.filename, url: json.url, content_type: json.content_type };
  },

  streamMessage(id: number, content: string, attachments: Attachment[], handlers: StreamHandlers) {
    return streamSSE("/api/chat/stream", { conversation_id: id, content, attachments }, handlers);
  },

  /** 重新生成：messageId 为要重跑的那条用户提问，content 可选（编辑场景传入新内容）。 */
  regenerate(
    conversationId: number,
    messageId: number,
    content: string | undefined,
    handlers: StreamHandlers,
  ) {
    return streamSSE(
      "/api/chat/regenerate",
      { conversation_id: conversationId, message_id: messageId, content },
      handlers,
    );
  },
};
