export default function Sidebar({ conversations, activeId, onSelect, onNew }) {
  return (
    <aside className="sidebar">
      <button className="new-chat-btn" onClick={onNew}>
        + New Conversation
      </button>
      <ul className="conversation-list">
        {conversations.map((c) => (
          <li
            key={c.id}
            className={`conversation-item ${
              c.id === activeId ? "conversation-item--active" : ""
            }`}
            onClick={() => onSelect(c.id)}
          >
            {c.title}
          </li>
        ))}
        {conversations.length === 0 && (
          <li className="conversation-empty">No conversations yet</li>
        )}
      </ul>
    </aside>
  );
}
