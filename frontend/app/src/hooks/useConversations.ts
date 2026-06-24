import { useState, useEffect, useCallback } from 'react';
import { getConversations, deleteConversation } from '@/api/client';
import type { Conversation } from '@/api/client';

export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getConversations();
      setConversations(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load conversations');
    } finally {
      setLoading(false);
    }
  }, []);

  const remove = useCallback(async (chatId: string) => {
    try {
      await deleteConversation(chatId);
      setConversations((prev) => prev.filter((c) => c.chat_id !== chatId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete conversation');
    }
  }, []);

  useEffect(() => {
    fetch();
  }, [fetch]);

  return { conversations, loading, error, refresh: fetch, remove };
}
