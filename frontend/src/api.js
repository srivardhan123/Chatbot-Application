const API_BASE = "http://127.0.0.1:8000/api";

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok && res.status !== 502) {
    throw new Error(data?.detail || `Request failed: ${res.status}`);
  }
  return { ok: res.ok, status: res.status, data };
}

export function listConversations() {
  return request("/conversations/");
}

export function createConversation(title) {
  return request("/conversations/", {
    method: "POST",
    body: JSON.stringify({ title: title || "New Conversation" }),
  });
}

export function listMessages(conversationId) {
  return request(`/conversations/${conversationId}/messages/`);
}

export function sendMessage(conversationId, content) {
  return request(`/conversations/${conversationId}/messages/`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}
