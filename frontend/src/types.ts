export interface User {
  email: string;
  full_name: string;
  roles: string[];
}

export interface DocumentItem {
  id: string;
  filename: string;
  status: 'pending' | 'processing' | 'ready' | 'failed';
  chunk_count: number;
  file_size_bytes: number;
  created_at: string;
  error_message?: string | null;
}

export interface DocumentListResponse {
  items: DocumentItem[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

export interface ChunkMatch {
  chunk_id: string;
  document_id: string;
  content: string;
  similarity_score: number;
}

export interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  sources?: ChunkMatch[];
  isStreaming?: boolean;
  timestamp: string;
}

export interface QueryLogResponse {
  id: string;
  question: string;
  answer: string | null;
  chunks_retrieved: number;
  latency_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  error: string | null;
  created_at: string;
}
