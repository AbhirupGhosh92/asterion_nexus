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

export default function ModelsTab({ onError }: { onError: (e: string | null) => void }) {
  const [models, setModels] = useState<AdminModel[]>([]);
  const [draft, setDraft] = useState<AdminModel>(EMPTY_MODEL);

  const refresh = () => adminApi.listModels().then(setModels).catch((e) => onError(String(e)));
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function save() {
    onError(null);
    if (!draft.id || !draft.label || !draft.model) {
      onError("id, label, and model name are required");
      return;
    }
    try {
      await adminApi.upsertModel(draft);
      setDraft(EMPTY_MODEL);
      refresh();
    } catch (e) {
      onError(String(e));
    }
  }

  async function toggle(m: AdminModel) {
    onError(null);
    try {
      await adminApi.upsertModel({ ...m, enabled: !m.enabled });
      refresh();
    } catch (e) {
      onError(String(e));
    }
  }

  async function remove(id: string) {
    onError(null);
    try {
      await adminApi.deleteModel(id);
      refresh();
    } catch (e) {
      onError(String(e));
    }
  }

  return (
    <div className="admin-scroll">
      <div className="model-form">
        <input
          className="admin-input"
          placeholder="id (e.g. gemini-pro)"
          value={draft.id}
          onChange={(e) => setDraft({ ...draft, id: e.target.value })}
        />
        <input
          className="admin-input"
          placeholder="label (e.g. Gemini 2.5 Pro)"
          value={draft.label}
          onChange={(e) => setDraft({ ...draft, label: e.target.value })}
        />
        <select
          className="admin-select"
          value={draft.provider}
          onChange={(e) => setDraft({ ...draft, provider: e.target.value })}
        >
          {PROVIDERS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <input
          className="admin-input"
          placeholder="model name (e.g. gemini-2.5-pro)"
          value={draft.model}
          onChange={(e) => setDraft({ ...draft, model: e.target.value })}
        />
        <select
          className="admin-select"
          value={draft.min_tier}
          onChange={(e) => setDraft({ ...draft, min_tier: e.target.value })}
        >
          {TIERS.map((t) => (
            <option key={t} value={t}>
              min: {t}
            </option>
          ))}
        </select>
        <button className="composer-send" onClick={save}>
          + DEPLOY
        </button>
      </div>

      <table className="admin-table">
        <thead>
          <tr>
            <th>MODEL</th>
            <th>PROVIDER</th>
            <th>MIN TIER</th>
            <th>STATE</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.id}>
              <td>
                <div className="cell-id">
                  <span>{m.label}</span>
                  <span className="cell-uid">
                    {m.id} · {m.model}
                  </span>
                </div>
              </td>
              <td className="cell-dim">{m.provider}</td>
              <td className="cell-dim">{m.min_tier.toUpperCase()}</td>
              <td>
                <button
                  className={m.enabled ? "pill pill-on pill-btn" : "pill pill-off pill-btn"}
                  onClick={() => toggle(m)}
                >
                  {m.enabled ? "ONLINE" : "OFFLINE"}
                </button>
              </td>
              <td>
                <button className="admin-btn admin-btn-danger" onClick={() => remove(m.id)}>
                  PURGE
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
