import { useCallback, useEffect, useRef, useState } from "react";
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

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="engine-stat">
      <span className="engine-stat-value">{value}</span>
      <span className="quota-field-label">{label}</span>
    </div>
  );
}

// A cloud VM reaches RUNNING in ~30 s, but Dify's containers need another
// minute or two on top of that. Poll across the whole window, or the panel
// reports OFFLINE for a boot that is going fine.
const POLL_MS = 5000;
const POLL_LIMIT = 36; // ~3 minutes

export default function EngineTab({ onError }: { onError: (e: string | null) => void }) {
  const [st, setSt] = useState<EngineStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [output, setOutput] = useState<string>("");
  const [polling, setPolling] = useState(false);
  const pollsLeft = useRef(0);

  const refresh = useCallback(
    () =>
      adminApi
        .engineStatus()
        .then((s) => {
          setSt(s);
          return s;
        })
        .catch((e) => {
          onError(String(e));
          return null;
        }),
    [onError],
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Keep polling while the engine is visibly mid-transition: GCE still
  // settling, or the VM up but Dify not yet answering.
  useEffect(() => {
    if (!polling) return;
    const id = setInterval(async () => {
      const s = await refresh();
      const settled = s && (s.reachable || (!s.vm?.transitioning && s.vm?.status === "TERMINATED"));
      if (settled || --pollsLeft.current <= 0) setPolling(false);
    }, POLL_MS);
    return () => clearInterval(id);
  }, [polling, refresh]);

  async function run(action: "start" | "stop" | "restart") {
    onError(null);
    setBusy(action);
    setOutput("");
    try {
      const r = await adminApi.engineControl(action);
      setOutput(r.output || (r.ok ? "done" : "failed"));
      if (!r.ok) onError(`Engine ${action} failed — see the log below.`);
      await refresh();
      // The command only *asks* GCE to change state; watch until it has.
      pollsLeft.current = POLL_LIMIT;
      setPolling(r.ok);
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(null);
    }
  }

  if (!st) return <div className="admin-scroll"><p className="cell-dim">loading…</p></div>;

  // Local dev and the deployed app need different advice when there's nothing
  // to control, and the hostname is the honest signal for which one this is.
  const isCloud = !/^(localhost|127\.0\.0\.1|\[::1\])$/.test(window.location.hostname);

  const MODE_LABEL: Record<string, string> = {
    docker: "local docker compose",
    vm: "compute engine vm",
    external: "external / hosted",
    none: "not configured",
  };

  return (
    <div className="admin-scroll">
      <div className="agent-form">
        <div className="engine-head">
          <span className={`pill ${st.reachable ? "pill-on" : "pill-off"}`}>
            {st.reachable ? "● ONLINE" : "● OFFLINE"}
          </span>
          <span className="cell-dim">{MODE_LABEL[st.mode] ?? st.mode}</span>
          {st.base_url && (
            <a
              className="engine-link"
              href={st.base_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {st.base_url} ↗
            </a>
          )}
        </div>

        <div className="engine-stats">
          <Stat label="AGENTS" value={st.agents} />
          <Stat label="TOOLS" value={st.tools} />
          <Stat label="MCP LINKS" value={st.mcp_servers} />
          <Stat label="PLUGINS" value={st.plugins.length} />
          {st.containers && (
            <Stat
              label="CONTAINERS"
              value={`${st.containers.running}/${st.containers.total}`}
            />
          )}
          {st.vm && <Stat label="VM" value={st.vm.status} />}
        </div>

        {st.vm && (
          <div className="engine-vm">
            {st.vm.ip && (
              <span className="cell-dim">
                {st.vm.machine_type ? `${st.vm.machine_type} · ` : ""}
                <a
                  className="engine-link"
                  href={`http://${st.vm.ip}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {st.vm.ip} ↗
                </a>
              </span>
            )}
            {st.vm.billing && <span className="cell-dim">💲 {st.vm.billing}</span>}
            {st.vm.error && <span className="engine-warn">⚠ {st.vm.error}</span>}
          </div>
        )}

        {polling && (
          <p className="cell-dim thinking-indicator">
            ◢ watching the engine come up — the VM boots in ~30s, Dify's
            containers take a minute or two more…
          </p>
        )}

        {st.plugins.length > 0 && (
          <div className="tool-row">
            <span className="tool-row-label">PLUGINS:</span>
            {st.plugins.map((p) => (
              <span key={p} className="tool-chip">
                {p.split("/").pop()}
              </span>
            ))}
          </div>
        )}

        <div className="engine-actions">
          <button
            className={`admin-btn ${busy === "start" ? "thinking-indicator" : ""}`}
            disabled={!st.controllable || busy !== null}
            onClick={() => run("start")}
          >
            {busy === "start" ? "STARTING…" : "▶ START"}
          </button>
          <button
            className={`admin-btn ${busy === "restart" ? "thinking-indicator" : ""}`}
            disabled={!st.controllable || busy !== null}
            onClick={() => run("restart")}
          >
            {busy === "restart" ? "RESTARTING…" : "⟲ RESTART"}
          </button>
          <button
            className={`admin-btn admin-btn-danger ${busy === "stop" ? "thinking-indicator" : ""}`}
            disabled={!st.controllable || busy !== null}
            onClick={() => run("stop")}
          >
            {busy === "stop" ? "STOPPING…" : "■ STOP"}
          </button>
          <button className="admin-btn" onClick={refresh} disabled={busy !== null}>
            ⟳ REFRESH
          </button>
        </div>

        {!st.controllable && (
          <p className="cell-dim">
            {isCloud ? (
              <>
                Status only — no engine VM is deployed. Set{" "}
                <code className="md-code-inline">WITH_DIFY="true"</code> in{" "}
                <code className="md-code-inline">deploy.config</code> and run{" "}
                <code className="md-code-inline">./deploy.sh</code>. Terraform creates
                the VM, wires <code className="md-code-inline">DIFY_VM_NAME</code>/
                <code className="md-code-inline">DIFY_VM_ZONE</code> into this service
                and grants it permission to start and stop the instance — then these
                buttons go live.
              </>
            ) : (
              <>
                Status only. Lifecycle control needs DIFY_COMPOSE_DIR (local docker) or
                DIFY_VM_NAME + DIFY_VM_ZONE (Compute Engine) in the backend env.
              </>
            )}
          </p>
        )}
        {st.vm?.status === "RUNNING" && !st.reachable && !polling && (
          <p className="cell-dim">
            VM is running but Dify isn't answering yet. Its containers start on boot
            and take a minute or two; if it stays offline, check the VM's serial
            console for the startup script.
          </p>
        )}
        {!st.reachable && st.configured && (
          <p className="cell-dim">
            Dify agents are hidden from the model selector while the engine is
            offline. Deep agents are unaffected — they run inside this backend.
          </p>
        )}
        {output && <pre className="engine-output">{output}</pre>}
      </div>
    </div>
  );
}
