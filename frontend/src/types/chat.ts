export interface Conversation {
  id: number;
  title: string;
  pinned: boolean;
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
  /** 版本链：同一逻辑消息（重新生成/编辑的多个版本）共享 group_id，组内 variant_index 递增。 */
  group_id?: number;
  variant_index?: number;
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
