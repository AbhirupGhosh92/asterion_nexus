import { useEffect, useState } from "react";
import type { User } from "firebase/auth";
import { FIREBASE_ENABLED, watchAuth } from "../models/api";

export type AuthState =
  | { status: "loading" }
  | { status: "out" }
  | { status: "in"; user: User | null };

/**
 * Sign-in state for the whole app.
 *
 * With no Firebase config (offline dev) the gate is skipped entirely, so the
 * UI works against a backend started with AUTH_DISABLED=1.
 */
export function useAuth(): AuthState {
  const [auth, setAuth] = useState<AuthState>(
    FIREBASE_ENABLED ? { status: "loading" } : { status: "in", user: null },
  );

  useEffect(() => {
    if (!FIREBASE_ENABLED) return;
    return watchAuth((user) => setAuth(user ? { status: "in", user } : { status: "out" }));
  }, []);

  return auth;
}
