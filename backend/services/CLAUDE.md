# services/ — ViewModel layer

Orchestration: what happens on a request. Services own the decisions, call
repositories and providers, and return plain data. They never touch HTTP
(no `Request`, no status codes except via `HTTPException` for real faults).

| File | Responsibility |
|---|---|
| `chat_service.py` | A conversation turn end to end: model resolution, memory recall, attachment handling, the three guardrail paths, persistence, title generation. The biggest and most important file here. |
| `registry_service.py` | The admin-managed model catalog (Firestore `models`). Resolves a model id + tier to a guardrail-wrapped instance, cached per model. Hides Dify agents when the engine is unreachable, and floors every agent at the Pro tier (`effective_min_tier`). |
| `quota_service.py` | Monthly per-user call limits: tier defaults, per-user overrides, usage counters (`users/{uid}/usage/{YYYY-MM}`), the `require_quota` dependency and the refund middleware. |
| `engine_service.py` | Dify engine lifecycle for the admin ENGINE tab: status plus start/stop/restart, for local docker compose or a Compute Engine VM. |

## Chat's three guarded paths

`chat_service` branches once, deliberately:

- **text** — full NeMo pipeline (`rails.generate_async(messages=…)`).
- **multimodal** — staged rails, because NeMo strips media parts: input rails
  on the text → raw model call with media intact → output rails on the result.
- **needs_user** — Dify agents and image generation. These adapters expose
  `needs_user = True` and take `user_id`, because the engine call carries the
  caller's identity for scoping and attribution.

Adding a fourth path? Give the adapter the same duck-typed shape
(`generate_async` / `stream_async`) rather than adding a branch upstream.

## Two ordering rules worth knowing

- `chat_service.stream()` is an `async def` that **returns** the frame
  generator; the router awaits it. Resolution therefore happens before
  `StreamingResponse` sends headers — otherwise a tier/quota `HTTPException`
  can only truncate the body and the client sees an empty `200`.
- Specialist agents are a Pro capability. `effective_min_tier` raises any
  model whose provider is in `AGENT_PROVIDERS` (`dify`, `langgraph`) to at
  least `pro`, and both `list_for_tier` (what the composer offers, and what
  `get_rails` allows) and `list_agents` (the gallery's `locked` flag) go
  through it — so the gate can't disagree with the badge.
- `AGENT_PROVIDERS` is the single place that knows which providers are
  agents. Adding a third runtime means adding it there and a branch in
  `_build_rails`; nothing above the registry changes.
