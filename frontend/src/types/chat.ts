export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Attachment {
  name: string;
  url: string;
  content_type: string;
}

export interface Artifact {
  filename: string;
  url: string;
  format: string;
  content_type?: string;
}

export interface Message {
  id: number;
  conversation_id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  attachments?: Attachment[];
  artifacts?: Artifact[];
}

export interface StreamEvent {
  type: string;
  content?: string;
  message?: string;
  name?: string;
  filename?: string;
  url?: string;
  format?: string;
  content_type?: string;
}
