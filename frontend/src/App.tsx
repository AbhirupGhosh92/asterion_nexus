import { useAuth } from "./viewmodels/useAuth";
import AuthGate from "./views/AuthGate";
import Workspace from "./views/Workspace";

/** Root: pick a screen from auth state. Everything else lives below. */
export default function App() {
  const auth = useAuth();

  if (auth.status === "loading") {
    return (
      <div className="shell gate">
        <div className="gate-glyph thinking-indicator">◢◤</div>
        <p className="gate-text">ESTABLISHING LINK…</p>
      </div>
    );
  }

  if (auth.status === "out") return <AuthGate />;

  return <Workspace user={auth.user} />;
}
