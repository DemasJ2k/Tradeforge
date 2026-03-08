export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Token refresh state — prevents multiple concurrent refresh attempts
let refreshPromise: Promise<boolean> | null = null;

async function tryRefreshToken(): Promise<boolean> {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  if (!token) return false;

  try {
    const res = await fetch(`${API_BASE}/api/auth/refresh`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    });
    if (!res.ok) return false;
    const data = await res.json();
    if (data.access_token) {
      localStorage.setItem("token", data.access_token);
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

function redirectToLogin() {
  if (typeof window === "undefined") return;
  // Store current path for post-login redirect
  const currentPath = window.location.pathname + window.location.search;
  if (currentPath !== "/login" && currentPath !== "/register") {
    localStorage.setItem("redirect_after_login", currentPath);
  }
  localStorage.removeItem("token");
  window.location.href = "/login";
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  isRetry = false,
): Promise<T> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("token") : null;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  // Handle 401 — try token refresh once, then redirect to login
  if (res.status === 401 && !isRetry && token) {
    // Deduplicate concurrent refresh attempts
    if (!refreshPromise) {
      refreshPromise = tryRefreshToken().finally(() => {
        refreshPromise = null;
      });
    }
    const refreshed = await refreshPromise;
    if (refreshed) {
      return request<T>(path, options, true);
    }
    redirectToLogin();
    throw new Error("Session expired. Please log in again.");
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = body.detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d: Record<string, unknown>) => d.msg ?? JSON.stringify(d)).join("; ") : `HTTP ${res.status}`;
    throw new Error(msg || `HTTP ${res.status}`);
  }

  return res.json();
}

async function uploadFile<T>(path: string, file: File): Promise<T> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("token") : null;

  const form = new FormData();
  form.append("file", file);

  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: form,
  });

  // Handle 401 for uploads too
  if (res.status === 401 && token) {
    if (!refreshPromise) {
      refreshPromise = tryRefreshToken().finally(() => {
        refreshPromise = null;
      });
    }
    const refreshed = await refreshPromise;
    if (refreshed) {
      return uploadFile<T>(path, file);
    }
    redirectToLogin();
    throw new Error("Session expired. Please log in again.");
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }

  return res.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, data?: unknown) =>
    request<T>(path, {
      method: "POST",
      ...(data !== undefined ? { body: JSON.stringify(data) } : {}),
    }),
  put: <T>(path: string, data?: unknown) =>
    request<T>(path, {
      method: "PUT",
      ...(data !== undefined ? { body: JSON.stringify(data) } : {}),
    }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: <T>(path: string, file: File) => uploadFile<T>(path, file),
};
