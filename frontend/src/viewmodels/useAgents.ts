import { useCallback, useEffect, useState } from "react";
import { listSpecialistAgents } from "../models/api";
import type { SpecialistAgent } from "../models/types";

/**
 * The specialist-agent roster for the homepage gallery.
 *
 * Takes the caller's tier so the list re-fetches when it changes (an admin
 * upgrading you mid-session), since `locked` is computed server-side.
 */
export function useAgents(tier: string | undefined) {
  const [agents, setAgents] = useState<SpecialistAgent[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    listSpecialistAgents()
      .then(setAgents)
      .catch(() => setAgents([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, tier]);

  return { agents, loading, refresh };
}
