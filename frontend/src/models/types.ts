/**
 * Shared domain types — the Model layer.
 *
 * Pure data shapes with no behaviour, imported by the API client,
 * the viewmodels (hooks) and the views alike.
 */

export interface ModelOption {
  id: string;
  label: string;
  provider: string;
}

export interface QuotaStatus {
  used: number;
  limit: number; // -1 = unlimited
  remaining: number;
  period: string; // YYYY-MM
  resets_on: string; // YYYY-MM-DD
  enforced: boolean;
}

export interface Profile {
  uid: string;
  email: string | null;
  tier: string;
  is_admin: boolean;
  models: ModelOption[];
  quota: QuotaStatus;
}

export interface UploadMeta {
  id: string;
  name: string;
  content_type: string;
  size: number;
}

export interface AdminUser {
  uid: string;
  email: string | null;
  display_name: string | null;
  tier: string;
  disabled: boolean;
  last_sign_in: number | null;
  quota_used?: number;
  quota_limit?: number;
  quota_override?: number | null;
}

export interface QuotaConfig {
  enabled: boolean;
  limits: Record<string, number>;
}

export interface AdminModel {
  id: string;
  label: string;
  provider: string;
  model: string;
  min_tier: string;
  enabled: boolean;
  extra: Record<string, string>;
}

export interface EngineStatus {
  mode: "docker" | "vm" | "external" | "none";
  configured: boolean;
  base_url: string;
  controllable: boolean;
  reachable: boolean;
  plugins: string[];
  tools: number;
  mcp_servers: number;
  agents: number;
  containers?: { running: number; total: number; names?: string[]; error?: string };
  vm?: { status: string; error?: string };
}

export interface McpServer {
  provider_id: string;
  name: string;
  server_url: string;
  tools: string[];
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  steps?: AgentStep[];
}

export interface AgentStep {
  position: number;
  thought?: string;
  tool?: string;
  tool_input?: string;
  observation?: string;
}

export interface StreamCallbacks {
  onToken: (token: string) => void;
  /** Fired first with the (possibly newly created) conversation id. */
  onMeta?: (conversationId: string | null) => void;
  /** Fired when a new conversation gets its generated title. */
  onTitle?: (title: string) => void;
  /** Fired each time an agent completes a tool decision. */
  onStep?: (step: AgentStep) => void;
}

export interface ConversationMeta {
  id: string;
  title: string;
  updated_at: string | null;
  message_count: number;
}

/** A file the user attached, with a local preview URL for images. */
export interface Attachment {
  meta: UploadMeta;
  previewUrl: string | null;
}

/** A message as the UI holds it: domain fields plus render state. */
export interface UiMessage extends ChatMessage {
  id: number;
  streaming?: boolean;
  guardrail?: boolean;
  attachments?: Attachment[];
}
