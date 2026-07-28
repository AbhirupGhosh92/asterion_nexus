# backend/ — FastAPI service

Server-side MVVM. **Read this before opening files; each layer has its own
CLAUDE.md with a per-file map.**

```
routers/       View       HTTP in/out. No decisions, no business logic.
services/      ViewModel  Orchestration — what actually happens per request.
repositories/  Model      Data access: Firestore, Cloud Storage, Memory Bank.
providers/     Model      LLMs, Dify, and the guardrail adapters.
models/        Model      Pydantic schemas shared across layers.
core/          —          Config + auth, used by every layer.
guardrails/    —          NeMo config (YAML/Colang, no Python).
app.py         —          Composition root: builds the object graph, mounts routers.
```

Entrypoint is `app:app` (`uvicorn app:app --port 8080`). Referenced by
`../start.sh`, `Dockerfile` and CI — change all three together.

## Dependency rule

Dependencies point **inward and downward only**:

    routers → services → repositories / providers → models / core

A router never touches Firestore directly; a repository never imports a
router. If you need something two layers away, pass it in at construction
time in `app.py` rather than importing across.

## Where things live

| Task | File |
|---|---|
| Add/modify an endpoint | `routers/` (+ a service method if it has logic) |
| Change what a chat turn does | `services/chat_service.py` |
| Change persistence shape | `repositories/` |
| Add an LLM provider | `providers/llm.py` |
| Change safety policy | `guardrails/config.yml` (plain English, no code) |
| Add an env var | `core/config.py` (declare it there, not inline `os.getenv`) |

## Invariants (do not weaken)

1. Every uid used for scoping comes from the **verified** Firebase token
   (`core/auth.verify_firebase_token`), never from a request body.
2. All LLM traffic passes NeMo Guardrails. Text turns use the full pipeline;
   multimodal/agent/image turns use staged rails (`options={"rails": [...]}`)
   because NeMo drops media parts.
3. `/api/admin/*` is gated by `ADMIN_EMAILS` — an identity allowlist. Tiers
   do **not** grant admin.
4. Model-calling routes depend on `require_quota` (auth + monthly quota), not
   bare token verification — otherwise the call is uncapped.
5. New routes must live under `/api/` — Firebase Hosting only rewrites those.
