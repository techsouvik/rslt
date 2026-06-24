import { useState, useCallback } from 'react';
import { sendChat, getChatHistory } from '@/api/client';
import type { ChatMessage, ChatResponse } from '@/api/client';

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastResponse, setLastResponse] = useState<ChatResponse | null>(null);

  const sendMessage = useCallback(
    async (message: string, chatId?: string) => {
      setLoading(true);
      setError(null);
      const id = chatId || `chat_${Date.now()}`;
      
      // Optimistically add user message instantly
      setMessages((prev) => [...prev, { role: 'user', content: message }]);
      
      try {
        const response = await sendChat({ chat_id: id, message });
        setLastResponse(response);
        
        // Append assistant reply to the state
        setMessages((prev) => [...prev, { role: 'assistant', content: response.reply }]);
        return response;
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to send message');
        return null;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const loadHistory = useCallback(async (chatId: string) => {
    setLoading(true);
    try {
      const data = await getChatHistory(chatId);
      setMessages(data.messages);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load history');
    } finally {
      setLoading(false);
    }
  }, []);

  return {
    messages,
    loading,
    error,
    lastResponse,
    sendMessage,
    loadHistory,
    setMessages,
  };
}

