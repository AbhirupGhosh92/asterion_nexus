import type { ConversationMeta } from "../models/types";

/** Conversation topics. Presentational — every action is a callback. */
export default function Sidebar({
  conversations,
  activeId,
  open,
  onNewChat,
  onOpen,
  onDelete,
}: {
  conversations: ConversationMeta[];
  activeId: string | null;
  open: boolean;
  onNewChat: () => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <aside className={`sidebar ${open ? "sidebar-open" : ""}`}>
      <button className="composer-send new-chat" onClick={onNewChat}>
        + NEW CHANNEL
      </button>
      <nav className="conv-list">
        {conversations.length === 0 && <p className="conv-empty">no transmissions yet</p>}
        {conversations.map((c) => (
          <div
            key={c.id}
            className={`conv-item ${c.id === activeId ? "conv-active" : ""}`}
            onClick={() => onOpen(c.id)}
          >
            <span className="conv-title">{c.title}</span>
            <button
              className="conv-delete"
              title="Delete"
              onClick={(e) => {
                e.stopPropagation();
                onDelete(c.id);
              }}
            >
              ✕
            </button>
          </div>
        ))}
      </nav>
    </aside>
  );
}
