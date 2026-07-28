/**
 * Frontend bridge: Firebase Auth → Cloud Run API.
 *
 * How the secure path works:
 *   1. Firebase Hosting rewrites /api/** to the Cloud Run service
 *      (see firebase.json) — same origin, so no CORS, and the Cloud Run URL
 *      is never exposed to users.
 *   2. Every request carries the signed Firebase ID token; the FastAPI
 *      backend verifies it (signature + expiry) and derives uid/tier from it.
 *   3. getIdToken() auto-refreshes — no manual token management.
 */

import type { User } from "firebase/auth";
import type {
  AdminModel,
  AdminUser,
  AgentStep,
  ChatMessage,
  ConversationMeta,
  EngineStatus,
  McpServer,
  ModelOption,
  Profile,
  QuotaConfig,
  QuotaStatus,
  StreamCallbacks,
  UploadMeta,
} from "./types";

export type * from "./types";

// Firebase is optional in local dev: without VITE_FIREBASE_API_KEY the app
// runs unauthenticated against a backend started with AUTH_DISABLED=1.
export const FIREBASE_ENABLED = Boolean(import.meta.env.VITE_FIREBASE_API_KEY);

let authPromise: Promise<import("firebase/auth").Auth> | null = null;

async function getFirebaseAuth() {
  if (!authPromise) {
    authPromise = (async () => {
      const { initializeApp } = await import("firebase/app");
      const { getAuth } = await import("firebase/auth");
      const app = initializeApp({
        apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
        authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
        projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
        appId: import.meta.env.VITE_FIREBASE_APP_ID,
      });
      return getAuth(app);
    })();
  }
  return authPromise;
}

/**
 * Same-origin in dev AND prod: the Vite proxy (dev) and the Firebase Hosting
 * rewrite (prod) both map /api/** to the backend.
 */
const API_BASE = "";

async function authedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  let token: string | null = null;
  if (FIREBASE_ENABLED) {
    const user = await currentUser();
    token = user ? await user.getIdToken() : null;
  }

  // Don't force a JSON content-type on FormData bodies — the browser must
  // set the multipart boundary itself.
  const isForm = init.body instanceof FormData;
  return fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
}

async function currentUser(): Promise<User | null> {
  const auth = await getFirebaseAuth();
  const { onAuthStateChanged } = await import("firebase/auth");
  return new Promise((resolve) => {
    const unsub = onAuthStateChanged(auth, (u) => {
      unsub();
      resolve(u);
    });
  });
}

export async function fetchProfile(): Promise<Profile | null> {
  const res = await authedFetch("/api/me");
  if (!res.ok) return null;
  return res.json();
}

// ---------------------------------------------------------------------------
// Uploads (image / audio / video → Firebase Storage via the backend)
// ---------------------------------------------------------------------------

const blobUrlCache = new Map<string, string>();

/** Fetch a stored/generated media file with auth and return an object URL. */
export async function fetchUploadUrl(id: string): Promise<string> {
  const cached = blobUrlCache.get(id);
  if (cached) return cached;
  const res = await authedFetch(`/api/uploads/${id}/content`);
  if (!res.ok) throw new Error(`Media fetch failed: ${res.status}`);
  const url = URL.createObjectURL(await res.blob());
  blobUrlCache.set(id, url);
  return url;
}

export async function uploadFile(file: File): Promise<UploadMeta> {
  const form = new FormData();
  form.append("file", file);
  const res = await authedFetch("/api/uploads", { method: "POST", body: form });
  if (!res.ok) throw new Error(`Upload failed: ${res.status} ${await res.text()}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Admin control plane
// ---------------------------------------------------------------------------

export const adminApi = {
  listUsers: async (): Promise<AdminUser[]> => {
    const res = await authedFetch("/api/admin/users");
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
    return res.json();
  },
  setTier: async (uid: string, tier: string): Promise<void> => {
    const res = await authedFetch(`/api/admin/users/${uid}/tier`, {
      method: "POST",
      body: JSON.stringify({ tier }),
    });
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
  },
  setDisabled: async (uid: string, disabled: boolean): Promise<void> => {
    const res = await authedFetch(`/api/admin/users/${uid}/disabled`, {
      method: "POST",
      body: JSON.stringify({ disabled }),
    });
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
  },
  getQuotaConfig: async (): Promise<QuotaConfig> => {
    const res = await authedFetch("/api/admin/quota");
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
    return res.json();
  },
  setQuotaConfig: async (cfg: Partial<QuotaConfig>): Promise<QuotaConfig> => {
    const res = await authedFetch("/api/admin/quota", {
      method: "POST",
      body: JSON.stringify(cfg),
    });
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
    return res.json();
  },
  setUserQuota: async (uid: string, limit: number | null): Promise<void> => {
    const res = await authedFetch(`/api/admin/users/${uid}/quota`, {
      method: "POST",
      body: JSON.stringify({ limit }),
    });
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
  },
  resetUserQuota: async (uid: string): Promise<void> => {
    const res = await authedFetch(`/api/admin/users/${uid}/quota/reset`, {
      method: "POST",
    });
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
  },
  listModels: async (): Promise<AdminModel[]> => {
    const res = await authedFetch("/api/admin/models");
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
    return res.json();
  },
  upsertModel: async (spec: AdminModel): Promise<void> => {
    const res = await authedFetch("/api/admin/models", {
      method: "POST",
      body: JSON.stringify(spec),
    });
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
  },
  deleteModel: async (id: string): Promise<void> => {
    const res = await authedFetch(`/api/admin/models/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
  },
  listAgents: async (): Promise<AdminModel[]> => {
    const res = await authedFetch("/api/admin/agents");
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
    return res.json();
  },
  listTools: async (): Promise<{ id: string; label: string; description: string }[]> => {
    const res = await authedFetch("/api/admin/tools");
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
    return res.json();
  },
  createAgent: async (spec: {
    id: string;
    name: string;
    instructions: string;
    model: string;
    min_tier: string;
    tools: string[];
  }): Promise<void> => {
    const res = await authedFetch("/api/admin/agents", {
      method: "POST",
      body: JSON.stringify(spec),
    });
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
  },
  deleteAgent: async (id: string): Promise<void> => {
    const res = await authedFetch(`/api/admin/agents/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
  },
  engineStatus: async (): Promise<EngineStatus> => {
    const res = await authedFetch("/api/admin/engine");
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
    return res.json();
  },
  engineControl: async (
    action: "start" | "stop" | "restart",
  ): Promise<{ ok: boolean; output: string }> => {
    const res = await authedFetch("/api/admin/engine", {
      method: "POST",
      body: JSON.stringify({ action }),
    });
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
    return res.json();
  },
  listMcp: async (): Promise<McpServer[]> => {
    const res = await authedFetch("/api/admin/mcp");
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
    return res.json();
  },
  addMcp: async (spec: { name: string; server_url: string }): Promise<McpServer> => {
    const res = await authedFetch("/api/admin/mcp", {
      method: "POST",
      body: JSON.stringify(spec),
    });
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
    return res.json();
  },
  deleteMcp: async (providerId: string): Promise<void> => {
    const res = await authedFetch(`/api/admin/mcp/${providerId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`(${res.status}) ${await res.text()}`);
  },
};

// ---------------------------------------------------------------------------
// Auth session helpers
// ---------------------------------------------------------------------------

export async function signInWithGoogle(): Promise<void> {
  const auth = await getFirebaseAuth();
  const { GoogleAuthProvider, signInWithPopup } = await import("firebase/auth");
  await signInWithPopup(auth, new GoogleAuthProvider());
}

export async function signOutUser(): Promise<void> {
  const auth = await getFirebaseAuth();
  const { signOut } = await import("firebase/auth");
  await signOut(auth);
}

// Dev-only: lets e2e tests sign in with an Admin-SDK custom token instead of
// the interactive Google popup. Stripped from production builds.
if (import.meta.env.DEV) {
  (window as never as Record<string, unknown>).__signInWithToken = async (token: string) => {
    const auth = await getFirebaseAuth();
    const { signInWithCustomToken } = await import("firebase/auth");
    await signInWithCustomToken(auth, token);
  };
}

/** Subscribe to auth state; returns an unsubscribe function. */
export function watchAuth(cb: (user: User | null) => void): () => void {
  if (!FIREBASE_ENABLED) {
    cb(null);
    return () => {};
  }
  let unsub: (() => void) | null = null;
  let cancelled = false;
  (async () => {
    const auth = await getFirebaseAuth();
    const { onAuthStateChanged } = await import("firebase/auth");
    if (!cancelled) unsub = onAuthStateChanged(auth, cb);
  })();
  return () => {
    cancelled = true;
    unsub?.();
  };
}

// ---------------------------------------------------------------------------
// API surface
// ---------------------------------------------------------------------------

/** One autonomous decision an agent made: why, which tool, and what it got. */

export async function chat(messages: ChatMessage[], conversationId?: string) {
  const res = await authedFetch("/api/chat", {
    method: "POST",
    body: JSON.stringify({ messages, conversation_id: conversationId }),
  });
  if (!res.ok) throw new Error(`Chat failed: ${res.status} ${await res.text()}`);
  return res.json() as Promise<{
    content: string;
    conversation_id: string | null;
    guardrail_triggered: boolean;
  }>;
}

/** Streaming chat over SSE. Events are JSON: token / meta / title / done. */
export async function chatStream(
  messages: ChatMessage[],
  cbs: StreamCallbacks,
  conversationId?: string | null,
  options?: { model?: string | null; attachments?: string[] },
): Promise<void> {
  const res = await authedFetch("/api/chat/stream", {
    method: "POST",
    body: JSON.stringify({
      messages,
      conversation_id: conversationId ?? null,
      model: options?.model ?? null,
      attachments: options?.attachments ?? [],
    }),
  });
  if (!res.ok || !res.body) {
    // Surface the server's explanation (e.g. the quota message) verbatim.
    const detail = await res.text().catch(() => "");
    throw new Error(`Stream failed: ${res.status} ${detail}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const evt of events) {
      if (!evt.startsWith("data: ")) continue;
      const payload = JSON.parse(evt.slice(6));
      if (payload.type === "token") cbs.onToken(payload.text);
      else if (payload.type === "step") cbs.onStep?.(payload.step);
      else if (payload.type === "meta") cbs.onMeta?.(payload.conversation_id);
      else if (payload.type === "title") cbs.onTitle?.(payload.title);
      else if (payload.type === "done") return;
    }
  }
}

// ---------------------------------------------------------------------------
// Conversation history
// ---------------------------------------------------------------------------

export async function listConversations(): Promise<ConversationMeta[]> {
  const res = await authedFetch("/api/conversations");
  if (!res.ok) return [];
  return res.json();
}

export async function getConversation(id: string): Promise<{ id: string; messages: ChatMessage[] }> {
  const res = await authedFetch(`/api/conversations/${id}`);
  if (!res.ok) throw new Error(`Load failed: ${res.status}`);
  return res.json();
}

export async function deleteConversation(id: string): Promise<void> {
  await authedFetch(`/api/conversations/${id}`, { method: "DELETE" });
}

export async function runWorkflow(workflowId: string, inputs: Record<string, unknown>) {
  const res = await authedFetch(`/api/workflows/${workflowId}/run`, {
    method: "POST",
    body: JSON.stringify(inputs),
  });
  if (res.status === 403) throw new Error("This workflow requires a Pro tier.");
  if (!res.ok) throw new Error(`Workflow failed: ${res.status}`);
  return res.json();
}
