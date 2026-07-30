import { useEffect, useRef, useState } from "react";
import MessageBubble from "./MessageBubble";

export default function ChatWindow({ messages, onSend, loading, error, disabled, provider, onProviderChange }) {
  const [input, setInput] = useState("");
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  function handleSubmit(e) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || loading) return;
    onSend(trimmed);
    setInput("");
  }

  if (disabled) {
    return (
      <div className="chat-window chat-window--empty">
        <p>Select a conversation or start a new one.</p>
      </div>
    );
  }

  return (
    <div className="chat-window">
      <div className="provider-selector">
        <label>LLM Provider:</label>
        <select value={provider} onChange={(e) => onProviderChange(e.target.value)} disabled={loading}>
          <option value="google">Google Gemini (Free)</option>
          <option value="anthropic">Anthropic Claude (Mocked)</option>
          <option value="openai">OpenAI GPT-4 (Mocked)</option>
        </select>
      </div>
    <div className="chat-window-inner">
      <div className="messages">
        {messages.map((m) => (
          <MessageBubble key={m.id} role={m.role} content={m.content} />
        ))}
        {loading && (
          <div className="message-row message-row--assistant">
            <div className="message-bubble message-bubble--assistant message-bubble--loading">
              Thinking…
            </div>
          </div>
        )}
        {error && <div className="chat-error">{error}</div>}
        <div ref={bottomRef} />
      </div>
      </div>
      <form className="chat-input" onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message..."
          disabled={loading}
        />
        <button type="submit" disabled={loading || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
