# views/admin/ — the control plane UI

`AdminPanel.tsx` is the shell: tab chrome plus a shared error banner. Each
tab is an independent screen taking a single `onError` prop and calling
`adminApi` directly (see the exception noted in `../../CLAUDE.md`).

| Tab | Controls |
|---|---|
| `UsersTab.tsx` | Firebase users: tier, lock/unlock, per-user quota override and usage reset. |
| `QuotasTab.tsx` | Global monthly limits per tier + the enforcement on/off switch. |
| `ModelsTab.tsx` | The model registry — add/remove models from any provider, set min tier, toggle online. |
| `AgentsTab.tsx` | Agent Forge: create Dify agents with instructions + a tool loadout (built-ins and MCP tools). |
| `McpTab.tsx` | Link MCP servers by URL; discovered tools join the forge arsenal automatically. |
| `EngineTab.tsx` | Dify engine health and START/STOP/RESTART — local docker compose or the Compute Engine VM. |

## Adding a tab

Create the component, add one entry to the `TABS` array in `AdminPanel.tsx`,
and add its calls to `adminApi` in `models/api.ts`. Nothing else changes.
