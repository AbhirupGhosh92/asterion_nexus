import { useEffect, useState } from "react";
import { adminApi } from "../../models/api";
import type {
  AdminModel, AdminUser, EngineStatus, McpServer, QuotaConfig,
} from "../../models/types";

const TIERS = ["free", "pro", "admin"];
const PROVIDERS = ["vertexai", "vertexai_image", "ollama", "mock"];
const EMPTY_MODEL: AdminModel = {
  id: "", label: "", provider: "vertexai", model: "",
  min_tier: "free", enabled: true, extra: {},
};

export default function McpTab({ onError }: { onError: (e: string | null) => void }) {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({ name: "", server_url: "" });

  const refresh = () => adminApi.listMcp().then(setServers).catch((e) => onError(String(e)));
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function link() {
    onError(null);
    if (!draft.name || !draft.server_url) {
      onError("name and server URL are required");
      return;
    }
    setBusy(true);
    try {
      const created = await adminApi.addMcp(draft);
      setDraft({ name: "", server_url: "" });
      refresh();
      if (created.tools.length === 0) {
        onError("Linked, but no tools discovered — check the server URL/transport.");
      }
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function unlink(id: string) {
    onError(null);
    try {
      await adminApi.deleteMcp(id);
      refresh();
    } catch (e) {
      onError(String(e));
    }
  }

  return (
    <div className="admin-scroll">
      <div className="agent-form">
        <div className="agent-form-row">
          <input
            className="admin-input"
            placeholder="name (e.g. deepwiki)"
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
          <input
            className="admin-input"
            placeholder="server URL (streamable HTTP / SSE endpoint)"
            value={draft.server_url}
            onChange={(e) => setDraft({ ...draft, server_url: e.target.value })}
          />
        </div>
        <button
          className={`composer-send ${busy ? "thinking-indicator" : ""}`}
          onClick={link}
          disabled={busy}
        >
          {busy ? "LINKING…" : "🔌 LINK SERVER"}
        </button>
      </div>

      <table className="admin-table">
        <thead>
          <tr>
            <th>SERVER</th>
            <th>TOOLS</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {servers.length === 0 && (
            <tr>
              <td colSpan={3} className="cell-dim">
                no MCP servers linked — linked tools join the AGENT FORGE arsenal automatically
              </td>
            </tr>
          )}
          {servers.map((s) => (
            <tr key={s.provider_id}>
              <td>
                <div className="cell-id">
                  <span>🔌 {s.name}</span>
                  <span className="cell-uid">{s.server_url}</span>
                </div>
              </td>
              <td className="cell-dim">{s.tools.join(", ") || "—"}</td>
              <td>
                <button className="admin-btn admin-btn-danger" onClick={() => unlink(s.provider_id)}>
                  UNLINK
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface ToolInfo {
  id: string;
  label: string;
  description: string;
}
