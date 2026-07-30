import { useCallback, useEffect, useState } from "react";
import Sidebar from "./components/Sidebar";
import ChatWindow from "./components/ChatWindow";
import * as api from "./api";
import "./App.css";

function App() {
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [provider, setProvider] = useState("google");

  const loadConversations = useCallback(async () => {
    const { data } = await api.listConversations();
    setConversations(data || []);
  }, []);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return;
    }
    setError(null);
    api.listMessages(activeId).then(({ data }) => setMessages(data || []));
  }, [activeId]);

  async function handleNewConversation() {
    const { data } = await api.createConversation();
    setConversations((prev) => [data, ...prev]);
    setActiveId(data.id);
    setMessages([]);
  }

  async function handleSend(content) {
    if (!activeId) return;
    setError(null);
    const tempId = `temp-${Date.now()}`;
    setMessages((prev) => [...prev, { id: tempId, role: "user", content }]);
    setLoading(true);
    try {
      const { ok, data } = await api.sendMessage(activeId, content, provider);
      setMessages((prev) => {
        const withoutTemp = prev.filter((m) => m.id !== tempId);
        if (ok && data.assistant_message) {
          return [...withoutTemp, data.user_message, data.assistant_message];
        }
        return [...withoutTemp, data.user_message];
      });
      if (!ok) {
        setError(data.error || "Something went wrong talking to the model.");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={handleNewConversation}
      />
      <ChatWindow
        messages={messages}
        onSend={handleSend}
        loading={loading}
        error={error}
        disabled={!activeId}
        provider={provider}
        onProviderChange={setProvider}
      />
    </div>
  );
}

export default App;
