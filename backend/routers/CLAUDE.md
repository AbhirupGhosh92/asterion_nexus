# routers/ — View layer (HTTP)

Endpoints only: parse the request, call a service, return the result. If a
handler contains an `if` about business rules, that logic belongs in
`services/`.

| File | Routes |
|---|---|
| `chat.py` | `POST /api/chat`, `POST /api/chat/stream` (SSE). Both depend on `require_quota` — auth **and** monthly quota. |
| `conversations.py` | `GET/DELETE /api/conversations[/{id}]` — history, uid-scoped. |
| `uploads.py` | `POST/GET /api/uploads`, `GET /api/uploads/{id}/content`. Serves bytes back through the app so Storage is never public. |
| `agents.py` | `GET /api/agents` — the specialist roster (both runtimes) for the homepage gallery. Auth only (no quota): listing costs no model call. Returns agents above the caller's tier too, flagged `locked`. |
| `admin.py` | Everything under `/api/admin/*`: users, quotas, model registry, agent forge, MCP links, engine control. Router-level `Depends(require_admin)`. |

`/healthz`, `/api/healthz` and `/api/me` live in `app.py` — they're one-liners
over app state with no service behind them.

## Conventions

- Prefix every route with `/api/` (Hosting only rewrites that path).
- Take `AuthedUser` via `Depends`; never read a uid from the body.
- Return plain dicts or Pydantic models — no manual `JSONResponse`.
