# models/ — shared schemas

Pydantic request/response shapes. No behaviour, no I/O — safe to import from
any layer without creating a cycle.

| File | Contains |
|---|---|
| `chat.py` | `ChatMessage`, `ChatRequest`, `ChatResponse`, `AgentStep` (the decision-trace entry). |
| `admin.py` | Every admin control-plane payload: tier/disable updates, quota config and overrides, `ModelSpec`, `AgentSpec`, `MCPServerSpec`, `EngineAction`. |

Keep validation here (regex on ids, tier enums) so routers stay dumb and the
rules live in one place.
