# NEXUS AI Platform — Claude Code guide

Personal ChatGPT-class AI platform: cyberpunk React UI + FastAPI backend +
NeMo Guardrails + Vertex AI (Gemini chat & image) + Dify agents + MCP tools.
Serverless in prod. Read `docs/DESIGN.md` for architecture rationale,
`docs/DEVELOPER_GUIDE.md` for a file-by-file walkthrough.

Deployment-specific facts (project ids, accounts, URLs) live in
`CLAUDE.local.md` (gitignored) and `deploy.config` — read those first if
they exist; never commit their contents.

## Commands

```bash
./start.sh [--no-auth]    # local stack: Dify (docker), backend :8080, frontend :5173
./stop.sh [--all]         # stop backend+frontend; --all also stops Dify
./deploy.sh [backend|frontend|all]   # cloud deploy, driven by deploy.config

# Backend alone (venv is Python 3.12 via uv — don't use system python if newer)
cd backend && set -a && source .env && set +a && .venv/bin/uvicorn fast_api_app:app --port 8080

# Type checks
cd frontend && npx tsc -b
cd backend && .venv/bin/python -c "import fast_api_app"
```

## Security invariants (do not weaken)

1. Every uid used for data scoping comes from the **verified Firebase token**
   (`auth.verify_firebase_token`), never from request bodies.
2. All LLM traffic passes NeMo Guardrails. Text turns: full rails. Multimodal
   / Dify / image turns: staged rails via `options={"rails": ["input"|"output"]}`
   (NeMo drops media parts, hence the hybrid path in `fast_api_app._guarded_multimodal`).
3. Admin surface (`/api/admin/*`) is gated by `ADMIN_EMAILS` (.env), an
   identity allowlist — tiers do NOT grant admin.
4. Clients never talk to Firestore/Storage/Dify directly — everything goes
   through FastAPI with uid scoping.

## Gotchas learned the hard way

- Dify console auth: cookie + CSRF (`X-CSRF-Token` header), and the login
  password must be **base64-encoded** (`dify.py` handles it).
- Dify agent-chat apps are **streaming-only** (`response_mode: streaming`).
- Classic Imagen models 404 on Vertex since June 2026 — image gen uses
  `gemini-2.5-flash-image` via the `google-genai` SDK (`imagegen.py`).
- NeMo `stream_async` requires `rails.output.streaming.enabled: True` in
  `backend/guardrails/config.yml`.
- Firebase Hosting rewrites cover `/api/**` only — new backend routes must
  live under `/api/` (healthz has an `/api/healthz` alias for this reason).
- Vite dev proxy (vite.config.ts) mirrors the prod rewrite; frontend code is
  identical in dev and prod. Frontend Firebase config: `frontend/.env.local`.
- Firestore free tier applies ONLY to the `(default)` database.
- Dify agents are per-engine: agents forged against local Dify don't exist in
  a cloud Dify (and vice versa) — re-forge from the admin panel after switching.

## E2E testing recipe (no user password ever)

Mint a custom token for a synthetic uid (e.g. `e2e-tester`) with
firebase-admin (`serviceAccountId` pointing at the project's
`firebase-adminsdk-*` SA — user creds can't sign, IAM signBlob can), exchange
it via identitytoolkit `accounts:signInWithCustomToken` (web API key from
`frontend/.env.local`), use the resulting ID token as Bearer. In the dev UI:
`window.__signInWithToken(token)`. For admin-endpoint tests, temporarily add
the test user's email to `ADMIN_EMAILS` in the shell env — never in `.env`.

## Extension points

- New LLM/provider → `backend/providers.py` + entry via admin MODEL GRID.
- New built-in agent tool → install Dify plugin + one `TOOL_CATALOG` entry in `backend/dify.py`.
- New MCP connector → admin MCP LINKS tab (URL, optional headers). Tools join the arsenal automatically.
- New route → keep under `/api/`, take `AuthedUser` via Depends, scope by `user.uid`.
