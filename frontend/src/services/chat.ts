import type { Artifact, Attachment, Conversation, Message, StreamEvent } from "../types/chat";
import { request } from "./api";

export interface StreamHandlers {
  onDelta: (text: string) => void;
  onToolStart?: (name: string) => void;
  onToolEnd?: (name: string) => void;
  onArtifact?: (artifact: Artifact) => void;
}

/** 聊天相关接口与流式请求。 */
export const chatApi = {
  listConversations: () => request<Conversation[]>("/api/conversations"),

  createConversation: (title = "新会话") =>
    request<Conversation>("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ title }),
    }),

  renameConversation: (id: number, title: string) =>
    request<Conversation>(`/api/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),

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

  async streamMessage(id: number, content: string, attachments: Attachment[], handlers: StreamHandlers) {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: id, content, attachments }),
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
  },
};
