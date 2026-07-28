# NEXUS AI Platform — Claude Code guide

Personal ChatGPT-class AI platform: cyberpunk React UI + FastAPI backend +
NeMo Guardrails + Vertex AI (Gemini chat & image) + Dify agents + MCP tools.
Serverless in prod. Read `docs/DESIGN.md` for architecture rationale,
`docs/DEVELOPER_GUIDE.md` for a file-by-file walkthrough.

Deployment-specific facts (project ids, accounts, URLs) live in
`CLAUDE.local.md` (gitignored) and `deploy.config` — read those first if
they exist; never commit their contents.

## Git workflow (required)

**Every change request starts on its own branch — never commit to `main`.**

```bash
git checkout main && git pull        # start from current main
git checkout -b feat/<short-slug>    # feat| fix| chore| docs| refactor
```

Commit the work there and report the branch name when done. Do **not** merge
or push unless asked — that's the user's call. Follow-up tweaks to the same
in-flight work stay on the same branch.

`main` is protected on GitHub: no force-push, no deletion, a PR is required,
and the `ci` check (`.github/workflows/ci.yml` — frontend build + backend
import) must pass. Approvals aren't required, so the maintainer can merge
their own PRs; admins can bypass in an emergency.

Note: `./deploy.sh` builds from the working tree, so deploying while on a
feature branch ships that branch's code.

## Architecture — read the nested CLAUDE.md files first

The codebase is MVVM-layered, and **every layer has its own CLAUDE.md with a
per-file map**. Read the one for the layer you're touching instead of
scanning the tree:

```
backend/CLAUDE.md            layering + invariants      (start here for API work)
  routers/     View          HTTP only
  services/    ViewModel     orchestration (chat_service is the big one)
  repositories/ Model        Firestore / Storage / Memory Bank
  providers/   Model         LLMs, Dify, guardrail adapters
  models/ core/              schemas, config, auth

frontend/src/CLAUDE.md       layering + the no-fetch-in-views rule
  models/      Model         types + API client
  viewmodels/  ViewModel     hooks: useChat, useAuth, useConversations
  views/       View          components (views/admin/ = control plane)
```

Dependencies point one way: `routers → services → repositories/providers →
models/core`, and in the UI `views → viewmodels → models`.

## Commands

```bash
./start.sh [--no-auth]    # local stack: Dify (docker), backend :8080, frontend :5173
./stop.sh [--all]         # stop backend+frontend; --all also stops Dify
./deploy.sh [backend|frontend|all]   # cloud deploy, driven by deploy.config
./teardown-dify.sh [--yes] [--purge-agents]   # destroy ONLY the Dify VM (the
                                              # sole always-on billed resource)

# Backend alone (venv is Python 3.12 via uv — don't use system python if newer)
cd backend && set -a && source .env && set +a && .venv/bin/uvicorn app:app --port 8080

# Type checks
cd frontend && npx tsc -b
cd backend && .venv/bin/python -c "import app"
```

## Security invariants (do not weaken)

1. Every uid used for data scoping comes from the **verified Firebase token**
   (`core/auth.verify_firebase_token`), never from request bodies.
2. All LLM traffic passes NeMo Guardrails. Text turns: full rails. Multimodal
   / Dify / image turns: staged rails via `options={"rails": ["input"|"output"]}`
   (NeMo drops media parts, hence the hybrid path in `services/chat_service._guarded_multimodal`).
3. Admin surface (`/api/admin/*`) is gated by `ADMIN_EMAILS` (.env), an
   identity allowlist — tiers do NOT grant admin.
4. Clients never talk to Firestore/Storage/Dify directly — everything goes
   through FastAPI with uid scoping.
5. Model-calling routes use `Depends(require_quota)` (auth + monthly quota),
   not bare `verify_firebase_token` — otherwise the call is uncapped.

## Gotchas learned the hard way

- Dify console auth: cookie + CSRF (`X-CSRF-Token` header), and the login
  password must be **base64-encoded** (`providers/dify.py` handles it).
- Dify agent-chat apps are **streaming-only** (`response_mode: streaming`).
- Classic Imagen models 404 on Vertex since June 2026 — image gen uses
  `gemini-2.5-flash-image` via the `google-genai` SDK (`providers/image_rails.py`).
- NeMo `stream_async` requires `rails.output.streaming.enabled: True` in
  `backend/guardrails/config.yml`.
- Firebase Hosting rewrites cover `/api/**` only — new backend routes must
  live under `/api/` (healthz has an `/api/healthz` alias for this reason).
- Vite dev proxy (vite.config.ts) mirrors the prod rewrite; frontend code is
  identical in dev and prod. Frontend Firebase config: `frontend/.env.local`.
- Firestore free tier applies ONLY to the `(default)` database.
- Dify agents are per-engine: agents forged against local Dify don't exist in
  a cloud Dify (and vice versa) — re-forge from the admin panel after switching.
- Quotas: admins (ADMIN_EMAILS) always bypass, so testing enforcement means
  running the backend WITHOUT the test email in the allowlist.
- `registry.get_rails(None, …)` defaults to the `default` model id and never
  auto-picks an agent/image model; `dify.is_up()` (60 s cached probe) hides
  agents when the engine is unreachable.

## E2E testing recipe (no user password ever)

Mint a custom token for a synthetic uid (e.g. `e2e-tester`) with
firebase-admin (`serviceAccountId` pointing at the project's
`firebase-adminsdk-*` SA — user creds can't sign, IAM signBlob can), exchange
it via identitytoolkit `accounts:signInWithCustomToken` (web API key from
`frontend/.env.local`), use the resulting ID token as Bearer. In the dev UI:
`window.__signInWithToken(token)`. For admin-endpoint tests, temporarily add
the test user's email to `ADMIN_EMAILS` in the shell env — never in `.env`.

## Extension points

- New LLM/provider → `backend/providers/llm.py` + entry via admin MODEL GRID.
- New built-in agent tool → install Dify plugin + one `TOOL_CATALOG` entry in `backend/providers/dify.py`.
- New MCP connector → admin MCP LINKS tab (URL, optional headers). Tools join the arsenal automatically.
- New route → keep under `/api/`, take `AuthedUser` via Depends, scope by `user.uid`.
