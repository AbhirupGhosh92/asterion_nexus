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

export default function QuotasTab({ onError }: { onError: (e: string | null) => void }) {
  const [cfg, setCfg] = useState<QuotaConfig | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    adminApi.getQuotaConfig().then(setCfg).catch((e) => onError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function save(next: Partial<QuotaConfig>) {
    onError(null);
    setBusy(true);
    try {
      setCfg(await adminApi.setQuotaConfig(next));
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!cfg) return <div className="admin-scroll"><p className="cell-dim">loading…</p></div>;

  return (
    <div className="admin-scroll">
      <div className="agent-form">
        <div className="quota-toggle">
          <button
            className={`pill pill-btn ${cfg.enabled ? "pill-on" : "pill-off"}`}
            onClick={() => save({ enabled: !cfg.enabled })}
            disabled={busy}
          >
            {cfg.enabled ? "ENFORCEMENT ON" : "ENFORCEMENT OFF"}
          </button>
          <span className="cell-dim">
            monthly API calls per user · −1 = unlimited · admins always bypass
          </span>
        </div>
        <div className="agent-form-row">
          {TIERS.map((t) => (
            <label key={t} className="quota-field">
              <span className="quota-field-label">{t.toUpperCase()}</span>
              <input
                className="admin-input"
                type="number"
                value={cfg.limits[t] ?? 0}
                onChange={(e) =>
                  setCfg({ ...cfg, limits: { ...cfg.limits, [t]: Number(e.target.value) } })
                }
              />
            </label>
          ))}
        </div>
        <button
          className={`composer-send ${busy ? "thinking-indicator" : ""}`}
          onClick={() => save({ limits: cfg.limits })}
          disabled={busy}
        >
          {busy ? "SAVING…" : "SAVE LIMITS"}
        </button>
      </div>
      <p className="cell-dim">
        Usage resets automatically at the start of each UTC month. Per-user
        overrides and one-off resets live in the OPERATIVES tab.
      </p>
    </div>
  );
}
