import { useCallback, useState } from "react";
import {
  deleteConversation,
  getConversation,
  listConversations,
} from "../models/api";
import type { ChatMessage, ConversationMeta } from "../models/types";

/** The topics sidebar: list, open and delete conversations. */
export function useConversations() {
  const [conversations, setConversations] = useState<ConversationMeta[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);

  const refresh = useCallback(() => {
    listConversations().then(setConversations).catch(() => {});
  }, []);

  /** Returns the stored messages, or null if the conversation is gone. */
  const open = useCallback(
    async (id: string): Promise<ChatMessage[] | null> => {
      try {
        const conv = await getConversation(id);
        setActiveId(id);
        return conv.messages;
      } catch {
        refresh(); // stale entry — drop it from the list
        return null;
      }
    },
    [refresh],
  );

  const remove = useCallback(
    async (id: string) => {
      await deleteConversation(id);
      refresh();
    },
    [refresh],
  );

  return { conversations, activeId, setActiveId, refresh, open, remove };
}
