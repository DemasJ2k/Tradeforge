"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { usePathname } from "next/navigation";
import { api, API_BASE } from "@/lib/api";
import { MessageCircle, Sparkles, FolderOpen, Clock, Plus, X, Trash2, Pencil, Send } from "lucide-react";
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
      api.get<ConversationList>("/api/llm/conversations").then((res) => {
        if (Array.isArray(res)) {
          setConversations(res);
        } else if (res && Array.isArray(res.items)) {
          setConversations(res.items);
        } else {
          setConversations([]);
        }
      }).catch(() => setConversations([]));
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
          <MessageCircle className="h-6 w-6" />
        </button>
      )}

      {/* Sidebar panel */}
      <div
        className={`fixed right-0 top-0 z-40 h-screen w-full sm:w-[380px] flex flex-col bg-sidebar-bg border-l border-card-border shadow-xl transition-transform duration-200 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-card-border px-4 py-3">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-accent" />
            <span className="font-semibold text-foreground">AI Assistant</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setShowMemories(!showMemories)}
              className={`p-1.5 rounded hover:bg-sidebar-hover ${showMemories ? "text-accent" : "text-muted-foreground hover:text-foreground"}`}
              title="Memories"
            >
              <FolderOpen className="h-4 w-4" />
            </button>
            <button
              onClick={() => setShowHistory(!showHistory)}
              className={`p-1.5 rounded hover:bg-sidebar-hover ${showHistory ? "text-accent" : "text-muted-foreground hover:text-foreground"}`}
              title="Chat History"
            >
              <Clock className="h-4 w-4" />
            </button>
            <button
              onClick={newChat}
              className="p-1.5 rounded hover:bg-sidebar-hover text-muted-foreground hover:text-foreground"
              title="New Chat"
            >
              <Plus className="h-4 w-4" />
            </button>
            <button
              onClick={() => setOpen(false)}
              className="p-1.5 rounded hover:bg-sidebar-hover text-muted-foreground hover:text-foreground"
              title="Close (Ctrl+K)"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* History dropdown */}
        {showHistory && (
          <div className="border-b border-card-border max-h-64 overflow-y-auto">
            {conversations.length === 0 ? (
              <div className="p-4 text-center text-xs text-muted-foreground">No conversations yet</div>
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
                    <div className="text-xs text-muted-foreground">{c.message_count} messages · {c.page_context || "general"}</div>
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); deleteConversation(c.id); }}
                    className="p-1 rounded text-muted-foreground hover:text-red-400 hover:bg-red-400/10 shrink-0"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
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
              <div className="text-[10px] text-muted-foreground">What the AI remembers about you</div>
            </div>
            {memoriesLoading ? (
              <div className="p-4 text-center text-xs text-muted-foreground">Loading memories...</div>
            ) : memories.length === 0 ? (
              <div className="p-6 text-center text-xs text-muted-foreground">
                <FolderOpen className="h-8 w-8 mx-auto mb-2 opacity-30" />
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
                              className="rounded border border-card-border px-2 py-1 text-[10px] text-muted-foreground"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <div className="text-xs text-muted-foreground mt-0.5">{mem.value}</div>
                        )}
                      </div>
                      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                        <button
                          onClick={() => togglePin(mem)}
                          className={`p-1 rounded text-xs ${mem.pinned ? "text-yellow-400" : "text-muted-foreground hover:text-yellow-400"}`}
                          title={mem.pinned ? "Unpin" : "Pin"}
                        >
                          📌
                        </button>
                        <button
                          onClick={() => { setEditingMemory(mem.id); setEditValue(mem.value); }}
                          className="p-1 rounded text-muted-foreground hover:text-foreground"
                          title="Edit"
                        >
                          <Pencil className="h-3 w-3" />
                        </button>
                        <button
                          onClick={() => deleteMemory(mem.id)}
                          className="p-1 rounded text-muted-foreground hover:text-red-400"
                          title="Delete"
                        >
                          <Trash2 className="h-3 w-3" />
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
            <div className="flex flex-col items-center justify-center h-full text-center text-muted-foreground">
              <Sparkles className="h-12 w-12 mb-3 opacity-30" />
              <p className="text-sm font-medium">FlowrexAlgo AI</p>
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
              <Send className="h-4 w-4" />
            </button>
          </div>
          <div className="mt-1.5 flex items-center justify-between text-[10px] text-muted-foreground">
            <span>Enter to send · Shift+Enter for new line</span>
            <span className="capitalize">{getPageContext(pathname)} context</span>
          </div>
        </div>
      </div>
    </>
  );
}
