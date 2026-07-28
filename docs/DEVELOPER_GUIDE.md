# NEXUS Developer Guide — from zero to contributor

You know basic coding but nothing about this project? This guide is for you.
By the end you'll understand every moving part and know exactly where to go
to change or extend anything. (The companion `DESIGN.md` explains *why* the
architecture is this way; this doc explains *what* and *how*.)

---

## 1. What is this thing?

NEXUS is a self-hosted "personal ChatGPT": a chat website with login, where
messages go to Google's Gemini models, conversations are saved per user
(with auto-generated titles like ChatGPT), users can upload images/audio/
video for the AI to analyze, generate images, and talk to "agents" — AI
personas with tools (web search, Wikipedia, custom connectors). An admin
panel controls users, models, agents, and tools.

Three big pieces:

```
┌──────────────┐   HTTPS    ┌───────────────┐   APIs   ┌──────────────────┐
│  React UI    │ ─────────► │ FastAPI       │ ───────► │ Google Cloud      │
│  (frontend/) │  /api/...  │ backend       │          │  Gemini, Firestore│
│              │            │ (backend/)    │          │  Storage, Auth    │
└──────────────┘            │       │       │          └──────────────────┘
                            │       └─────────────────► Dify (local Docker)
                            └───────────────┘            agents + tools
```

The golden rule of the codebase: **the browser only ever talks to the
FastAPI backend.** Never directly to the database, storage, or AI models.
The backend checks who you are on every request and only lets you touch
your own data.

## 2. Run it locally (10 minutes)

Prereqs: Node 20+, Python 3.12 (`uv` recommended), OrbStack or Docker
Desktop, `gcloud` CLI authenticated (`gcloud auth application-default login`).

```bash
# one-time setup
cd backend && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env        # then fill in values (see comments inside)
cd ../frontend && npm install

# every day after that
./start.sh                  # starts Dify + backend + frontend
# open http://localhost:5173
./stop.sh                   # tears it down (Dify keeps running; --all stops it too)
```

No Google Cloud yet? `./start.sh --no-auth` + `LLM_PROVIDER=mock` in
`backend/.env` runs everything with a fake AI — good for pure UI work.

## 3. The backend, file by file (`backend/`)

| File | What it does | Touch it when… |
|---|---|---|
| `app.py` | The entry point. Defines every route (`/api/chat`, `/api/conversations`, …), wires everything together at startup (the `lifespan` function). | adding/changing API endpoints |
| `auth.py` | Verifies the Firebase login token on every request; defines user tiers (free/pro/admin) and the `ADMIN_EMAILS` allowlist. | changing who can do what |
| `providers.py` | Builds the actual LLM client — Gemini (`vertexai`), local (`ollama`), or fake (`mock`). One function, one switch. | adding a new AI provider |
| `models_registry.py` | The catalog of models users can pick in the chat dropdown. Stored in Firestore, managed from the admin UI, tier-gated. Each model gets wrapped in guardrails, lazily, once. | changing how models are resolved/cached |
| `store.py` | Chat history in Firestore: `users/{uid}/conversations/{id}/messages`. | changing what gets saved per conversation |
| `memory.py` | Long-term memory (Vertex AI Memory Bank): extracts facts about a user and recalls them in later chats. Fails soft — no GCP, no memory, no crash. | changing memory behavior |
| `uploads.py` | File uploads (image/audio/video) to Firebase Storage under `uploads/{uid}/`, 25 MB cap. Serves file bytes back through an authenticated route. | changing upload rules/types |
| `imagegen.py` | The "🎨 Image Studio" model: prompt → guardrail check → `gemini-2.5-flash-image` → saves PNG → returns `[image:<id>]` token. | changing image generation |
| `dify.py` | Everything Dify: console client (create/delete agent apps, register MCP servers), the tool catalog, and `DifyRails` — the adapter that makes a Dify agent look like a normal model. | agents, tools, MCP |
| `quota.py` | Monthly per-user API call limits: tier defaults + per-user overrides in Firestore, usage counted in `users/{uid}/usage/{YYYY-MM}` (auto-resets monthly), enforced by the `require_quota` dependency and refunded on errors. | changing rate limits / billing rules |
| `admin.py` | All `/api/admin/*` routes: user management, quotas, model registry CRUD, agent forge, MCP links. Every route requires an allowlisted admin email. | adding admin features |
| `guardrails/` | NeMo Guardrails config: `config.yml` (safety policies as prompts) + `rails.co` (the refusal message). No Python — it's configuration. | tuning safety rules |

### How one chat message flows

1. UI POSTs to `/api/chat/stream` with the message list + chosen model id.
2. `verify_firebase_token` decodes the login token → `user.uid`, `user.tier`.
3. `registry.get_rails(model_id, tier)` returns the guardrail-wrapped model
   (403 if the user's tier isn't allowed to use it).
4. Long-term memories for this uid get prepended as a system message.
5. The message runs through NeMo Guardrails: an "input rail" asks a small
   LLM "should this be blocked?" → if yes, a refusal comes back and the main
   model is never called. Otherwise the model generates, and an "output
   rail" screens the answer the same way.
6. Tokens stream back as JSON SSE events (`{"type":"token","text":…}`).
7. The exchange is saved to Firestore; a new conversation gets an
   auto-generated title; facts get stored in Memory Bank.

Special cases branch at step 5: messages with attachments and image/agent
models run the rails *stages* explicitly (input rail → engine → output rail)
because NeMo's full pipeline only handles plain text.

## 4. The frontend, file by file (`frontend/src/`)

| File | What it does |
|---|---|
| `App.tsx` | Nearly the whole UI: auth gate, sidebar (conversation topics), chat panel, streaming rendering, model selector, attachments, `[image:id]` token rendering. |
| `Admin.tsx` | The admin panel: OPERATIVES (users), MODEL GRID, AGENT FORGE, MCP LINKS tabs. |
| `Markdown.tsx` | Renders assistant output as Markdown (tables, links, code, lists) via react-markdown + remark-gfm. Raw HTML is deliberately NOT enabled, so model output can't inject markup; links are forced to `target=_blank` + `rel=noopener`. User messages stay plain text. |
| `lib/apiClient.ts` | Every backend call lives here. Attaches the Firebase token, parses SSE streams, caches image blob URLs. **Never `fetch` directly from components — add a function here.** |
| `theme.css` | Design tokens: colors, fonts, glows. Change the whole look here. |
| `app.css` | Component styles + the responsive breakpoint (`@media (max-width: 820px)` turns the sidebar into a drawer). |

State is plain `useState` — no Redux/router. The app has exactly two screens
(gate and workspace) toggled by auth state, and the admin panel is an overlay.

## 5. Common changes, step by step

**Branch first.** Every change starts on its own branch off `main`
(`git checkout -b feat/my-thing`); `main` stays releasable and each change
stays reviewable.


**Add an API endpoint**
```python
# app.py (must start with /api/ — the prod proxy only forwards /api/**)
@app.get("/api/hello")
async def hello(user: AuthedUser = Depends(verify_firebase_token)):
    return {"hi": user.uid}   # ALWAYS scope data by user.uid
```
Then add a caller in `apiClient.ts` and use it from a component.

**Add a chat model** — admin panel → MODEL GRID → fill id/label/provider/
model-name/tier → DEPLOY. No code. For a brand-new *provider* (say,
Anthropic), add a branch in `providers.py::build_chat_llm` and add the
provider name to `PROVIDERS` in `models_registry.py` + `Admin.tsx`.

**Add an agent tool** — if it's a Dify marketplace plugin: install it (see
`DESIGN.md §5.1e` for the console API calls) and add one entry to
`TOOL_CATALOG` in `dify.py`. If it's an MCP server: admin panel → MCP LINKS
→ paste URL. Done — no code at all.

**Change the safety policy** — edit the prompts in
`backend/guardrails/config.yml`. They're plain English questions the
screening model answers Yes/No to. Restart the backend.

**Change the look** — edit CSS variables in `theme.css` (`--neon-cyan`,
`--bg-void`, fonts). Everything derives from them.

**Give a user pro/admin tier** — admin panel → OPERATIVES → dropdown. The
change lands at their next token refresh (≤1 h) or re-login.

## 6. Testing without a real login

You can't type your Google password into scripts — instead mint a *custom
token* for a synthetic user with the Admin SDK and exchange it for a real ID
token. Full recipe in `CLAUDE.md` ("E2E testing recipe"). In the dev UI,
`window.__signInWithToken(token)` logs the browser in as that user (dev
builds only).

## 7. Deploying

```bash
./deploy.sh            # everything: Terraform infra + backend image + Cloud Run + Hosting
```
- Backend → Cloud Run (`ai-platform-api`), built by Cloud Build with a
  timestamp tag, infra defined in `infra/main.tf` (read it — it's commented).
- Frontend → the Firebase Hosting site named in `deploy.config`
  (`FIREBASE_SITE`) → `https://<site>.web.app`. The deploy script writes the
  site name into `frontend/firebase.json`, so a project's *default* Hosting
  site (which may host something else) is never touched by accident.
- Secrets: never in the image (`.dockerignore` excludes `.env`); prod config
  arrives via Cloud Run env vars / Secret Manager (see `main.tf`).
- Dify is optional (it isn't serverless): `WITH_DIFY="true"` in
  `deploy.config` provisions a small always-on VM; `./teardown-dify.sh`
  destroys just that VM again, leaving every serverless piece running. With
  no reachable engine, agent models are hidden automatically.

## 8. Debugging crib sheet

| Symptom | Look at |
|---|---|
| 401 on everything | Frontend not logged in, or backend missing `GCP_PROJECT` (token verification needs the project id) |
| 403 on a model | User's tier below the model's `min_tier` |
| Guardrails refuse everything | `guardrails/config.yml` prompts too strict; check backend log — each rail decision is logged |
| 429 on chat | Monthly quota exhausted — admin → QUOTAS to raise tier limits, or OPERATIVES to override/reset that user |
| Dify calls fail | Is the stack up? (`docker compose ps` in `infra/dify/docker`) Login quirk: password must be base64'd (handled in `dify.py`) |
| Image gen 404s the model | Vertex model names drift; probe with `google-genai` SDK (classic Imagen is gone since June 2026) |
| Works locally, 404 in prod | Route not under `/api/` — the Hosting rewrite only forwards `/api/**` |
| Backend logs | local: `logs/backend.log`; prod: Cloud Console → Cloud Run → ai-platform-api → Logs |
