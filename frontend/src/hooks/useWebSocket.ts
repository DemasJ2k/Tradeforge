"use client";

import { create } from "zustand";

type WSStatus = "disconnected" | "connecting" | "connected" | "reconnecting";
type MessageHandler = (data: Record<string, unknown>) => void;

interface WSState {
  status: WSStatus;
  ws: WebSocket | null;
  /** Subscribe to a channel. Returns unsubscribe function. */
  subscribe: (channel: string, handler: MessageHandler) => () => void;
  /** Unsubscribe all handlers for a channel. */
  unsubscribeChannel: (channel: string) => void;
  /** Connect to WebSocket server. */
  connect: () => void;
  /** Disconnect from WebSocket server. */
  disconnect: () => void;
}

const WS_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/^http/, "ws");

// Internal state not stored in Zustand (avoids reactivity overhead for high-frequency data)
let _ws: WebSocket | null = null;
let _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let _connectTimeout: ReturnType<typeof setTimeout> | null = null;
let _reconnectDelay = 1000;
let _intentionalClose = false;
let _pingTimer: ReturnType<typeof setInterval> | null = null;

// Channel → set of handlers
const _handlers = new Map<string, Set<MessageHandler>>();

// Channels we want to be subscribed to (tracks desired state across reconnects)
const _desiredChannels = new Set<string>();

// Max time (ms) to wait for a WebSocket connection before retrying
const CONNECTION_TIMEOUT = 10000;

function _sendJSON(data: Record<string, unknown>) {
  if (_ws && _ws.readyState === WebSocket.OPEN) {
    _ws.send(JSON.stringify(data));
  }
}

function _dispatch(channel: string, data: Record<string, unknown>) {
  const handlers = _handlers.get(channel);
  if (handlers) {
    for (const h of handlers) {
      try {
        h(data);
      } catch (e) {
        console.error("[WS] Handler error:", e);
      }
    }
  }
}

function _resubscribeAll() {
  for (const ch of _desiredChannels) {
    _sendJSON({ type: "subscribe", channel: ch });
  }
}

function _cleanupConnection() {
  if (_connectTimeout) {
    clearTimeout(_connectTimeout);
    _connectTimeout = null;
  }
  if (_pingTimer) {
    clearInterval(_pingTimer);
    _pingTimer = null;
  }
}

export const useWebSocket = create<WSState>((set, get) => ({
  status: "disconnected",
  ws: null,

  connect: () => {
    // If already connected, nothing to do
    if (_ws && _ws.readyState === WebSocket.OPEN) {
      return;
    }

    // If stuck in CONNECTING state, force-close and retry
    if (_ws && _ws.readyState === WebSocket.CONNECTING) {
      console.log("[WS] Force-closing stuck CONNECTING socket");
      try { _ws.close(); } catch { /* ignore */ }
      _ws = null;
    }

    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
    if (!token) return;

    _intentionalClose = false;
    _cleanupConnection();
    set({ status: "connecting" });

    const ws = new WebSocket(`${WS_BASE}/ws?token=${token}`);
    _ws = ws;

    // Connection timeout — if onopen doesn't fire within 10s, force close and retry
    _connectTimeout = setTimeout(() => {
      if (ws.readyState === WebSocket.CONNECTING) {
        console.warn("[WS] Connection timeout — force closing");
        try { ws.close(); } catch { /* ignore */ }
        // onclose will handle reconnect logic
      }
    }, CONNECTION_TIMEOUT);

    ws.onopen = () => {
      _cleanupConnection();
      console.log("[WS] Connected");
      _reconnectDelay = 1000;
      set({ status: "connected", ws });
      _resubscribeAll();
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        const type = msg.type as string;

        if (type === "ping") {
          _sendJSON({ type: "pong" });
          return;
        }

        if (type === "subscribed" || type === "unsubscribed" || type === "error") {
          // Protocol acknowledgements
          if (type === "error") {
            console.warn("[WS] Server error:", msg.message);
          }
          return;
        }

        // Route data messages to channel handlers
        const channel = msg.channel as string | undefined;
        if (channel) {
          _dispatch(channel, msg);
        }
      } catch {
        // ignore parse errors
      }
    };

    ws.onclose = () => {
      _cleanupConnection();
      _ws = null;
      set({ ws: null });

      if (!_intentionalClose) {
        set({ status: "reconnecting" });
        console.log(`[WS] Disconnected, reconnecting in ${_reconnectDelay}ms...`);
        if (_reconnectTimer) clearTimeout(_reconnectTimer);
        _reconnectTimer = setTimeout(() => {
          get().connect();
        }, _reconnectDelay);
        _reconnectDelay = Math.min(_reconnectDelay * 2, 30000);
      } else {
        set({ status: "disconnected" });
      }
    };

    ws.onerror = (err) => {
      console.error("[WS] Error:", err);
      // onerror is always followed by onclose, so reconnect is handled there
    };
  },

  disconnect: () => {
    _intentionalClose = true;
    _cleanupConnection();
    if (_reconnectTimer) {
      clearTimeout(_reconnectTimer);
      _reconnectTimer = null;
    }
    if (_ws) {
      _ws.close();
      _ws = null;
    }
    _desiredChannels.clear();
    _handlers.clear();
    set({ status: "disconnected", ws: null });
  },

  subscribe: (channel: string, handler: MessageHandler) => {
    // Register handler
    if (!_handlers.has(channel)) {
      _handlers.set(channel, new Set());
    }
    _handlers.get(channel)!.add(handler);

    // Track desired subscription
    const wasSubscribed = _desiredChannels.has(channel);
    _desiredChannels.add(channel);

    // Send subscribe if this is the first handler for this channel
    if (!wasSubscribed) {
      _sendJSON({ type: "subscribe", channel });
    }

    // Return unsubscribe function
    return () => {
      const handlers = _handlers.get(channel);
      if (handlers) {
        handlers.delete(handler);
        if (handlers.size === 0) {
          _handlers.delete(channel);
          _desiredChannels.delete(channel);
          _sendJSON({ type: "unsubscribe", channel });
        }
      }
    };
  },

  unsubscribeChannel: (channel: string) => {
    _handlers.delete(channel);
    _desiredChannels.delete(channel);
    _sendJSON({ type: "unsubscribe", channel });
  },
}));
