export default function MessageBubble({ role, content }) {
  const isUser = role === "user";
  return (
    <div className={`message-row ${isUser ? "message-row--user" : "message-row--assistant"}`}>
      <div
        className={`message-bubble ${
          isUser ? "message-bubble--user" : "message-bubble--assistant"
        }`}
      >
        {content}
      </div>
    </div>
  );
}
