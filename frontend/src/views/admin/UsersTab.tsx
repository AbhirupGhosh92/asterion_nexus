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

export default function UsersTab({ onError }: { onError: (e: string | null) => void }) {
  const [users, setUsers] = useState<AdminUser[]>([]);

  const refresh = () => adminApi.listUsers().then(setUsers).catch((e) => onError(String(e)));
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function applyOverride(uid: string, raw: string) {
    onError(null);
    const trimmed = raw.trim();
    try {
      await adminApi.setUserQuota(uid, trimmed === "" ? null : Number(trimmed));
      refresh();
    } catch (e) {
      onError(String(e));
    }
  }

  async function resetUsage(uid: string) {
    onError(null);
    try {
      await adminApi.resetUserQuota(uid);
      refresh();
    } catch (e) {
      onError(String(e));
    }
  }

  async function changeTier(uid: string, tier: string) {
    onError(null);
    try {
      await adminApi.setTier(uid, tier);
      refresh();
    } catch (e) {
      onError(String(e));
    }
  }

  async function toggleDisabled(u: AdminUser) {
    onError(null);
    try {
      await adminApi.setDisabled(u.uid, !u.disabled);
      refresh();
    } catch (e) {
      onError(String(e));
    }
  }

  return (
    <div className="admin-scroll">
      <table className="admin-table">
        <thead>
          <tr>
            <th>IDENTITY</th>
            <th>TIER</th>
            <th>USAGE</th>
            <th>OVERRIDE</th>
            <th>STATUS</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.uid} className={u.disabled ? "row-disabled" : ""}>
              <td>
                <div className="cell-id">
                  <span>{u.email ?? u.display_name ?? "—"}</span>
                  <span className="cell-uid">{u.uid}</span>
                </div>
              </td>
              <td>
                <select
                  className="admin-select"
                  value={u.tier}
                  onChange={(e) => changeTier(u.uid, e.target.value)}
                >
                  {TIERS.map((t) => (
                    <option key={t} value={t}>
                      {t.toUpperCase()}
                    </option>
                  ))}
                </select>
              </td>
              <td className="cell-dim">
                {u.quota_limit === undefined ? (
                  "—"
                ) : (
                  <span
                    className={
                      u.quota_limit >= 0 && (u.quota_used ?? 0) >= u.quota_limit
                        ? "quota-exhausted"
                        : ""
                    }
                  >
                    {u.quota_used ?? 0} / {u.quota_limit < 0 ? "∞" : u.quota_limit}
                  </span>
                )}
              </td>
              <td>
                <input
                  className="admin-input quota-override-input"
                  type="number"
                  placeholder="tier"
                  defaultValue={u.quota_override ?? ""}
                  title="Per-user monthly limit. Blank = use tier default, −1 = unlimited."
                  onBlur={(e) => {
                    const next = e.target.value.trim();
                    const cur = u.quota_override === null || u.quota_override === undefined
                      ? "" : String(u.quota_override);
                    if (next !== cur) applyOverride(u.uid, next);
                  }}
                />
              </td>
              <td>
                <span className={u.disabled ? "pill pill-off" : "pill pill-on"}>
                  {u.disabled ? "LOCKED" : "ACTIVE"}
                </span>
              </td>
              <td className="row-actions">
                <button className="admin-btn" onClick={() => resetUsage(u.uid)} title="Reset this month's usage to 0">
                  RESET
                </button>
                <button className="admin-btn" onClick={() => toggleDisabled(u)}>
                  {u.disabled ? "UNLOCK" : "LOCK"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
