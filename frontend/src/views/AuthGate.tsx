import { useState } from "react";
import { signInWithGoogle } from "../models/api";

/** Sign-in screen shown until Firebase reports an authenticated user. */
export default function AuthGate() {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function login() {
    setBusy(true);
    setError(null);
    try {
      await signInWithGoogle();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="shell gate">
      <div className="gate-panel terminal-panel neon-border">
        <div className="gate-glyph">◢◤</div>
        <h1 className="gate-title">
          NEXUS<span className="hud-dim">://</span>AI
        </h1>
        <p className="gate-text">IDENTITY VERIFICATION REQUIRED</p>
        <p className="gate-sub">access to the grid is gated · sign in to open a channel</p>
        <button className="composer-send gate-btn" onClick={login} disabled={busy}>
          {busy ? "AUTHENTICATING…" : "AUTHENTICATE WITH GOOGLE"}
        </button>
        {error && <p className="gate-error">⚠ {error}</p>}
      </div>
    </div>
  );
}
