"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api";
import type {
  ChatMessage,
  ConversationSummary,
  ConversationList,
  ConversationDetail,
  MemoryItem,
} from "@/types";

// ── Markdown-lite renderer (bold, code, headers, lists) ──
function renderMarkdown(text: string) {
  // Split into lines for block processing
  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];
  let inCodeBlock = false;
  let codeLines: string[] = [];
  // codeLang is extracted for future syntax highlighting support

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Code blocks
    if (line.startsWith("```")) {
      if (inCodeBlock) {
        elements.push(
          <pre key={`code-${i}`} className="bg-black/30 rounded-md p-3 my-2 overflow-x-auto text-xs font-mono">
            <code>{codeLines.join("\n")}</code>
          </pre>
        );
        codeLines = [];
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
        // language hint: line.slice(3).trim()
      }
      continue;
    }
    if (inCodeBlock) {
      codeLines.push(line);
      continue;
    }

    // Headers
    if (line.startsWith("### ")) {
      elements.push(<h4 key={i} className="font-semibold text-sm mt-3 mb-1">{line.slice(4)}</h4>);
      continue;
    }
    if (line.startsWith("## ")) {
      elements.push(<h3 key={i} className="font-semibold text-sm mt-3 mb-1">{line.slice(3)}</h3>);
      continue;
    }
    if (line.startsWith("# ")) {
      elements.push(<h2 key={i} className="font-bold text-base mt-3 mb-1">{line.slice(2)}</h2>);
      continue;
    }

    // Bullet lists
    if (line.match(/^[-*]\s/)) {
      elements.push(<li key={i} className="ml-4 list-disc text-sm">{inlineFormat(line.slice(2))}</li>);
      continue;
    }
    // Numbered lists
    if (line.match(/^\d+\.\s/)) {
      const content = line.replace(/^\d+\.\s/, "");
      elements.push(<li key={i} className="ml-4 list-decimal text-sm">{inlineFormat(content)}</li>);
      continue;
    }

    // Empty line
    if (line.trim() === "") {
      elements.push(<div key={i} className="h-2" />);
      continue;
    }

    // Normal paragraph
    elements.push(<p key={i} className="text-sm leading-relaxed">{inlineFormat(line)}</p>);
  }

  return <>{elements}</>;
}

function inlineFormat(text: string): React.ReactNode {
  // Bold + inline code
  const parts: React.ReactNode[] = [];
  const regex = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let lastIndex = 0;
  let match;
  let key = 0;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const m = match[0];
    if (m.startsWith("`")) {
      parts.push(<code key={key++} className="bg-black/30 px-1 rounded text-xs font-mono">{m.slice(1, -1)}</code>);
    } else if (m.startsWith("**")) {
      parts.push(<strong key={key++}>{m.slice(2, -2)}</strong>);
    }
    lastIndex = match.index + m.length;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts.length === 1 ? parts[0] : <>{parts}</>;
}

// ── Page context detection ──
function getPageContext(pathname: string): string {
  if (pathname === "/") return "dashboard";
  const segment = pathname.split("/")[1];
  return segment || "dashboard";
}

// ── SSE streaming helper ──
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function* streamChat(
  body: { message: string; conversation_id?: number | null; page_context?: string; context_data?: Record<string, unknown> }
): AsyncGenerator<{ type: string; content?: string; conversation_id?: number; title?: string; tokens_in?: number; tokens_out?: number; model?: string }> {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const res = await fetch(`${API_BASE}/api/llm/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6));
        } catch {
          // ignore parse errors
        }
      }
    }
  }
}

// ══════════════════════════════════════════════════════════════════════
// ChatSidebar Component
// ══════════════════════════════════════════════════════════════════════

export default function ChatSidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [showMemories, setShowMemories] = useState(false);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [memoriesLoading, setMemoriesLoading] = useState(false);
  const [editingMemory, setEditingMemory] = useState<number | null>(null);
  const [editValue, setEditValue] = useState("");
  const [streamingText, setStreamingText] = useState("");
  const [error, setError] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText]);

  // Load conversation list when history panel opens
  useEffect(() => {
    if (showHistory) {
      setShowMemories(false);
      api.get<ConversationList>("/api/llm/conversations").then(setConversations as never).catch(() => {});
    }
  }, [showHistory]);

  // Load memories when memories panel opens
  useEffect(() => {
    if (showMemories) {
      setShowHistory(false);
      setMemoriesLoading(true);
      api.get<{ items: MemoryItem[]; total: number }>("/api/llm/memories")
        .then((res) => setMemories(res.items))
        .catch(() => setMemories([]))
        .finally(() => setMemoriesLoading(false));
    }
  }, [showMemories]);

  // Keyboard shortcut: Ctrl+K to toggle
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === "k") {
        e.preventDefault();
        setOpen((p) => !p);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Focus input when opened
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const loadConversation = useCallback(async (id: number) => {
    try {
      const detail = await api.get<ConversationDetail>(`/api/llm/conversations/${id}`);
      setMessages(detail.messages);
      setConversationId(id);
      setShowHistory(false);
    } catch {
      setError("Failed to load conversation");
    }
  }, []);

  const deleteConversation = useCallback(async (id: number) => {
    try {
      await api.delete(`/api/llm/conversations/${id}`);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (conversationId === id) {
        setMessages([]);
        setConversationId(null);
      }
    } catch {
      setError("Failed to delete conversation");
    }
  }, [conversationId]);

  const newChat = useCallback(() => {
    setMessages([]);
    setConversationId(null);
    setShowHistory(false);
    setShowMemories(false);
    setError("");
    setStreamingText("");
  }, []);

  const togglePin = useCallback(async (mem: MemoryItem) => {
    try {
      const updated = await api.put<MemoryItem>(`/api/llm/memories/${mem.id}`, { pinned: !mem.pinned });
      setMemories((prev) => prev.map((m) => (m.id === mem.id ? updated : m)));
    } catch { setError("Failed to update memory"); }
  }, []);

  const saveMemoryEdit = useCallback(async (mem: MemoryItem) => {
    try {
      const updated = await api.put<MemoryItem>(`/api/llm/memories/${mem.id}`, { value: editValue });
      setMemories((prev) => prev.map((m) => (m.id === mem.id ? updated : m)));
      setEditingMemory(null);
    } catch { setError("Failed to update memory"); }
  }, [editValue]);

  const deleteMemory = useCallback(async (id: number) => {
    try {
      await api.delete(`/api/llm/memories/${id}`);
      setMemories((prev) => prev.filter((m) => m.id !== id));
    } catch { setError("Failed to delete memory"); }
  }, []);

  const sendMessage = useCallback(async () => {
    const msg = input.trim();
    if (!msg || loading) return;

    setInput("");
    setError("");
    setLoading(true);

    const userMsg: ChatMessage = { role: "user", content: msg, timestamp: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg]);

    try {
      const pageCtx = getPageContext(pathname);
      let fullReply = "";
      setStreamingText("");

      // Load page-specific context data
      let contextData: Record<string, unknown> | undefined;
      if (pageCtx === "ml") {
        try {
          const mlCtx = await api.get<Record<string, unknown>>("/api/llm/ml-context");
          contextData = mlCtx;
        } catch { /* skip context if fetch fails */ }
      }

      for await (const event of streamChat({
        message: msg,
        conversation_id: conversationId,
        page_context: pageCtx,
        context_data: contextData,
      })) {
        if (event.type === "error") {
          setError(event.content || "LLM error");
          setStreamingText("");
          break;
        } else if (event.type === "chunk" && event.content) {
          fullReply += event.content;
          setStreamingText(fullReply);
        } else if (event.type === "done") {
          setConversationId(event.conversation_id ?? null);
          setStreamingText("");
          const assistantMsg: ChatMessage = {
            role: "assistant",
            content: fullReply,
            timestamp: new Date().toISOString(),
          };
          setMessages((prev) => [...prev, assistantMsg]);
        }
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
      setStreamingText("");
    } finally {
      setLoading(false);
    }
  }, [input, loading, conversationId, pathname]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // ── Prefill from helper buttons ──
  const prefill = useCallback((text: string) => {
    setOpen(true);
    setInput(text);
    setTimeout(() => inputRef.current?.focus(), 100);
  }, []);

  // Expose prefill globally for contextual buttons
  useEffect(() => {
    (window as unknown as Record<string, unknown>).__chatPrefill = prefill;
    return () => { delete (window as unknown as Record<string, unknown>).__chatPrefill; };
  }, [prefill]);

  return (
    <>
      {/* Toggle button (floating) */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed right-4 bottom-4 z-50 flex h-12 w-12 items-center justify-center rounded-full bg-accent text-black shadow-lg hover:scale-105 transition-transform"
          title="Open AI Assistant (Ctrl+K)"
        >
          <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" />
          </svg>
        </button>
      )}

      {/* Sidebar panel */}
      <div
        className={`fixed right-0 top-0 z-40 h-screen flex flex-col bg-sidebar-bg border-l border-card-border shadow-xl transition-transform duration-200 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
        style={{ width: "380px" }}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-card-border px-4 py-3">
          <div className="flex items-center gap-2">
            <svg className="h-5 w-5 text-accent" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z" />
            </svg>
            <span className="font-semibold text-foreground">AI Assistant</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setShowMemories(!showMemories)}
              className={`p-1.5 rounded hover:bg-sidebar-hover ${showMemories ? "text-accent" : "text-muted hover:text-foreground"}`}
              title="Memories"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 9.776c.112-.017.227-.026.344-.026h15.812c.117 0 .232.009.344.026m-16.5 0a2.25 2.25 0 00-1.883 2.542l.857 6a2.25 2.25 0 002.227 1.932H19.05a2.25 2.25 0 002.227-1.932l.857-6a2.25 2.25 0 00-1.883-2.542m-16.5 0V6A2.25 2.25 0 016 3.75h3.879a1.5 1.5 0 011.06.44l2.122 2.12a1.5 1.5 0 001.06.44H18A2.25 2.25 0 0120.25 9v.776" />
              </svg>
            </button>
            <button
              onClick={() => setShowHistory(!showHistory)}
              className={`p-1.5 rounded hover:bg-sidebar-hover ${showHistory ? "text-accent" : "text-muted hover:text-foreground"}`}
              title="Chat History"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </button>
            <button
              onClick={newChat}
              className="p-1.5 rounded hover:bg-sidebar-hover text-muted hover:text-foreground"
              title="New Chat"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
            </button>
            <button
              onClick={() => setOpen(false)}
              className="p-1.5 rounded hover:bg-sidebar-hover text-muted hover:text-foreground"
              title="Close (Ctrl+K)"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* History dropdown */}
        {showHistory && (
          <div className="border-b border-card-border max-h-64 overflow-y-auto">
            {conversations.length === 0 ? (
              <div className="p-4 text-center text-xs text-muted">No conversations yet</div>
            ) : (
              conversations.map((c) => (
                <div
                  key={c.id}
                  className={`flex items-center justify-between px-4 py-2 hover:bg-sidebar-hover cursor-pointer text-sm ${
                    c.id === conversationId ? "bg-sidebar-active text-accent" : "text-foreground"
                  }`}
                >
                  <div className="flex-1 truncate mr-2" onClick={() => loadConversation(c.id)}>
                    <div className="truncate font-medium">{c.title}</div>
                    <div className="text-xs text-muted">{c.message_count} messages · {c.page_context || "general"}</div>
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); deleteConversation(c.id); }}
                    className="p-1 rounded text-muted hover:text-red-400 hover:bg-red-400/10 shrink-0"
                  >
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                    </svg>
                  </button>
                </div>
              ))
            )}
          </div>
        )}

        {/* Memories panel */}
        {showMemories && (
          <div className="border-b border-card-border max-h-80 overflow-y-auto">
            <div className="px-4 py-2 border-b border-card-border/50">
              <div className="text-xs font-semibold text-foreground">AI Memories</div>
              <div className="text-[10px] text-muted">What the AI remembers about you</div>
            </div>
            {memoriesLoading ? (
              <div className="p-4 text-center text-xs text-muted">Loading memories...</div>
            ) : memories.length === 0 ? (
              <div className="p-6 text-center text-xs text-muted">
                <svg className="h-8 w-8 mx-auto mb-2 opacity-30" fill="none" viewBox="0 0 24 24" strokeWidth={1} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 9.776c.112-.017.227-.026.344-.026h15.812c.117 0 .232.009.344.026m-16.5 0a2.25 2.25 0 00-1.883 2.542l.857 6a2.25 2.25 0 002.227 1.932H19.05a2.25 2.25 0 002.227-1.932l.857-6a2.25 2.25 0 00-1.883-2.542m-16.5 0V6A2.25 2.25 0 016 3.75h3.879a1.5 1.5 0 011.06.44l2.122 2.12a1.5 1.5 0 001.06.44H18A2.25 2.25 0 0120.25 9v.776" />
                </svg>
                No memories yet. Chat with the AI to build your trading profile.
              </div>
            ) : (
              <div className="divide-y divide-card-border/30">
                {memories.map((mem) => (
                  <div key={mem.id} className="px-4 py-2.5 hover:bg-sidebar-hover/50 group">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5 mb-0.5">
                          <span className="text-[10px] rounded px-1.5 py-0.5 bg-accent/10 text-accent font-medium uppercase">
                            {mem.category}
                          </span>
                          {mem.pinned && (
                            <span className="text-[10px] text-yellow-400">📌</span>
                          )}
                        </div>
                        <div className="text-xs font-medium text-foreground">{mem.key}</div>
                        {editingMemory === mem.id ? (
                          <div className="mt-1 flex gap-1">
                            <input
                              value={editValue}
                              onChange={(e) => setEditValue(e.target.value)}
                              className="flex-1 rounded border border-card-border bg-input-bg px-2 py-1 text-xs text-foreground"
                              autoFocus
                              onKeyDown={(e) => {
                                if (e.key === "Enter") saveMemoryEdit(mem);
                                if (e.key === "Escape") setEditingMemory(null);
                              }}
                            />
                            <button
                              onClick={() => saveMemoryEdit(mem)}
                              className="rounded bg-accent px-2 py-1 text-[10px] text-black font-medium"
                            >
                              Save
                            </button>
                            <button
                              onClick={() => setEditingMemory(null)}
                              className="rounded border border-card-border px-2 py-1 text-[10px] text-muted"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <div className="text-xs text-muted mt-0.5">{mem.value}</div>
                        )}
                      </div>
                      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                        <button
                          onClick={() => togglePin(mem)}
                          className={`p-1 rounded text-xs ${mem.pinned ? "text-yellow-400" : "text-muted hover:text-yellow-400"}`}
                          title={mem.pinned ? "Unpin" : "Pin"}
                        >
                          📌
                        </button>
                        <button
                          onClick={() => { setEditingMemory(mem.id); setEditValue(mem.value); }}
                          className="p-1 rounded text-muted hover:text-foreground"
                          title="Edit"
                        >
                          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125" />
                          </svg>
                        </button>
                        <button
                          onClick={() => deleteMemory(mem.id)}
                          className="p-1 rounded text-muted hover:text-red-400"
                          title="Delete"
                        >
                          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                          </svg>
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {messages.length === 0 && !streamingText && (
            <div className="flex flex-col items-center justify-center h-full text-center text-muted">
              <svg className="h-12 w-12 mb-3 opacity-30" fill="none" viewBox="0 0 24 24" strokeWidth={1} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
              </svg>
              <p className="text-sm font-medium">TradeForge AI</p>
              <p className="text-xs mt-1">Ask me anything about trading,<br />strategies, or the platform.</p>
              <p className="text-xs mt-3 opacity-50">Ctrl + K to toggle</p>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[90%] rounded-xl px-3 py-2 ${
                  msg.role === "user"
                    ? "bg-accent text-black"
                    : "bg-card-bg border border-card-border text-foreground"
                }`}
              >
                {msg.role === "assistant" ? renderMarkdown(msg.content) : (
                  <p className="text-sm">{msg.content}</p>
                )}
              </div>
            </div>
          ))}

          {/* Streaming text */}
          {streamingText && (
            <div className="flex justify-start">
              <div className="max-w-[90%] rounded-xl px-3 py-2 bg-card-bg border border-card-border text-foreground">
                {renderMarkdown(streamingText)}
                <span className="inline-block w-2 h-4 bg-accent animate-pulse ml-0.5" />
              </div>
            </div>
          )}

          {/* Loading indicator */}
          {loading && !streamingText && (
            <div className="flex justify-start">
              <div className="rounded-xl px-3 py-2 bg-card-bg border border-card-border">
                <div className="flex gap-1">
                  <div className="w-2 h-2 rounded-full bg-muted animate-bounce" style={{ animationDelay: "0ms" }} />
                  <div className="w-2 h-2 rounded-full bg-muted animate-bounce" style={{ animationDelay: "150ms" }} />
                  <div className="w-2 h-2 rounded-full bg-muted animate-bounce" style={{ animationDelay: "300ms" }} />
                </div>
              </div>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="rounded-lg bg-red-500/10 border border-red-500/30 px-3 py-2 text-xs text-red-400">
              {error}
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="border-t border-card-border p-3">
          <div className="flex items-end gap-2">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything..."
              rows={1}
              className="flex-1 resize-none rounded-lg border border-card-border bg-input-bg px-3 py-2 text-sm text-foreground placeholder-muted focus:outline-none focus:border-accent"
              style={{ maxHeight: "120px" }}
              onInput={(e) => {
                const target = e.target as HTMLTextAreaElement;
                target.style.height = "auto";
                target.style.height = Math.min(target.scrollHeight, 120) + "px";
              }}
            />
            <button
              onClick={sendMessage}
              disabled={loading || !input.trim()}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent text-black disabled:opacity-40 hover:brightness-110 transition"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
              </svg>
            </button>
          </div>
          <div className="mt-1.5 flex items-center justify-between text-[10px] text-muted">
            <span>Enter to send · Shift+Enter for new line</span>
            <span className="capitalize">{getPageContext(pathname)} context</span>
          </div>
        </div>
      </div>
    </>
  );
}
