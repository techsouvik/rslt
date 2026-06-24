// API Client for UGC Studio AI Backend
// Base URL configurable via import.meta.env

const API_BASE = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? 'http://localhost:8000' : '');

// ═══════════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════════

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatRequest {
  chat_id: string;
  message: string;
}

export interface ChatResponse {
  chat_id: string;
  reply: string;
  job_id: string;
}

export interface ChatHistoryResponse {
  messages: ChatMessage[];
}

export interface VideoSummary {
  job_id: string;
  status: string;
  video_url: string;
}

export interface Conversation {
  chat_id: string;
  title: string;
  updated_at: string;
  video_count: number;
  videos: VideoSummary[];
}

export interface JobVideo {
  job_id: string;
  chat_id: string;
  status: string;
  progress: number;
  message: string;
  product_url: string;
  video_url: string;
  api_calls_count: number;
  input_tokens_burned: number;
  output_tokens_burned: number;
  total_tokens_burned: number;
  created_at: string;
}

export interface ConversationDetail {
  chat_id: string;
  title: string;
  messages: ChatMessage[];
  videos: JobVideo[];
}

export interface JobDetails {
  job_id: string;
  chat_id: string;
  status: string;
  progress: number;
  message: string;
  product_url: string;
  custom_instructions: string;
  video_url: string;
  api_calls_count: number;
  input_tokens_burned: number;
  output_tokens_burned: number;
  total_tokens_burned: number;
  details: {
    scraped_stats: {
      url: string;
      character_count: number;
      word_count: number;
      status: string;
    };
    product_brief: {
      product: string;
      category: string;
      targetAudience: string;
      painPoint: string;
      valueProposition: string;
    };
    video_plan: {
      duration: number;
      backgroundSearch: string;
      isLightBackground: boolean;
      gifSearch: string;
      audioCategory: string;
      fontFamily: string;
      fontSize: number;
      fontColor: string;
      strokeColor: string;
    };
    rendering_stats: {
      duration_seconds: number;
      resolution: string;
      codec: string;
      file_size_mb: number;
    };
  };
}

export interface SSEProgressEvent {
  job_id: string;
  status: string;
  progress: number;
  message: string;
  video_url?: string;
}

export interface DeleteResponse {
  status: string;
  message: string;
}

// ═══════════════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════════════

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`HTTP ${response.status}: ${text}`);
  }
  return response.json() as Promise<T>;
}

// ═══════════════════════════════════════════════════════════════
// API Endpoints
// ═══════════════════════════════════════════════════════════════

/**
 * Send a chat message and trigger video generation
 */
export async function sendChat(request: ChatRequest): Promise<ChatResponse> {
  return fetchJSON<ChatResponse>(`${API_BASE}/api/chat`, {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

/**
 * Get chat message history for a conversation
 */
export async function getChatHistory(chatId: string = 'default_chat'): Promise<ChatHistoryResponse> {
  return fetchJSON<ChatHistoryResponse>(
    `${API_BASE}/api/chat/history?chat_id=${encodeURIComponent(chatId)}`
  );
}

/**
 * Get all conversations
 */
export async function getConversations(): Promise<Conversation[]> {
  return fetchJSON<Conversation[]>(`${API_BASE}/api/conversations`);
}

/**
 * Get a single conversation with all details
 */
export async function getConversation(chatId: string): Promise<ConversationDetail> {
  return fetchJSON<ConversationDetail>(`${API_BASE}/api/conversations/${encodeURIComponent(chatId)}`);
}

/**
 * Delete a conversation
 */
export async function deleteConversation(chatId: string): Promise<DeleteResponse> {
  return fetchJSON<DeleteResponse>(`${API_BASE}/api/conversations/${encodeURIComponent(chatId)}`, {
    method: 'DELETE',
  });
}

/**
 * Get job details
 */
export async function getJobDetails(jobId: string): Promise<JobDetails> {
  return fetchJSON<JobDetails>(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}`);
}

/**
 * Connect to SSE progress stream for a job
 * Returns cleanup function
 */
export function connectJobSSE(
  jobId: string,
  onEvent: (event: SSEProgressEvent) => void,
  onError?: (error: Event) => void,
  onOpen?: () => void
): () => void {
  const url = `${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/sse`;
  const eventSource = new EventSource(url);

  eventSource.addEventListener('open', () => {
    onOpen?.();
  });

  eventSource.addEventListener('progress', (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data) as SSEProgressEvent;
      onEvent(data);
    } catch {
      // ignore parse errors
    }
  });

  eventSource.addEventListener('error', (e: Event) => {
    onError?.(e);
  });

  // Cleanup function
  return () => {
    eventSource.close();
  };
}
