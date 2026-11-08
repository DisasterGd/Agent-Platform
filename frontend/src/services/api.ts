import type { Conversation, Message } from "../types/chat";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers }
  });
  if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
  return response.json() as Promise<T>;
}

export const api = {
  listConversations: () => request<Conversation[]>("/api/conversations"),
  createConversation: (title = "新会话") =>
    request<Conversation>("/api/conversations", {
      method: "POST", body: JSON.stringify({ title })
    }),
  listMessages: (id: number) =>
    request<Message[]>(`/api/conversations/${id}/messages`),

  async streamMessage(id: number, content: string, onDelta: (text: string) => void) {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: id, content })
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
            const event = JSON.parse(line.slice(5).trim()) as {
              type: string; content?: string; message?: string
            };
            if (event.type === "text_delta" && event.content) onDelta(event.content);
            if (event.type === "error") throw new Error(event.message || "流式响应错误");
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }
};