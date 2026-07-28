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
│    MVVM      │            │ (backend/)    │          │  Storage, Auth    │
└──────────────┘            │   MVVM  │     │          └──────────────────┘
                            │         ├───────────────► LangGraph deep agents
                            │         │     │            (inside this process)
                            │         └───────────────► Dify (optional Docker/VM)
                            └───────────────┘            second agent runtime
```

The golden rule of the codebase: **the browser only ever talks to the
FastAPI backend.** Never directly to the database, storage, or AI models.
The backend checks who you are on every request and only lets you touch
your own data.

The second rule: **both halves are MVVM-layered, and every layer has its own
`CLAUDE.md`** with a per-file map. Read the one for the layer you're touching
instead of scanning the tree — this guide gives you the shape, those files
stay current with the code.

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

## 3. The backend, layer by layer (`backend/`)

Server-side MVVM. Dependencies point one way:
`routers → services → repositories/providers → models/core`.

| Layer | Role | Files |
|---|---|---|
| `routers/` | **View** — HTTP in, HTTP out, no decisions | `chat.py`, `conversations.py`, `uploads.py`, `agents.py`, `admin.py` |
| `services/` | **ViewModel** — what actually happens per request | `chat_service.py`, `registry_service.py`, `quota_service.py`, `engine_service.py` |
| `repositories/` | **Model** — data access | `chat_repo.py` (Firestore history), `media_repo.py` (Storage), `memory_repo.py` (Memory Bank) |
| `providers/` | **Model** — external brains | `llm.py`, `deep_agents.py`, `agent_tools.py`, `dify.py`, `image_rails.py` |
| `models/`, `core/` | schemas, config, auth | `core/auth.py` (token verify + tiers + `ADMIN_EMAILS`), `core/config.py` (every env var) |
| `guardrails/` | NeMo config — YAML/Colang, no Python | `config.yml`, `rails.co` |
| `app.py` | composition root: builds the object graph, mounts routers | — |

Where to go for a given change:

| Task | File |
|---|---|
| Add/modify an endpoint | `routers/` (+ a service method if it has logic) |
| Change what a chat turn does | `services/chat_service.py` |
| Add an LLM provider | `providers/llm.py` |
| Add a deep-agent tool | `providers/agent_tools.py` |
| Change how models/agents resolve | `services/registry_service.py` |
| Change rate limits | `services/quota_service.py` |
| Tune safety rules | `guardrails/config.yml` (plain English, no code) |
| Add an env var | `core/config.py` — declare it there, not inline `os.getenv` |

### The two agent runtimes

Both satisfy one duck-typed contract (`generate_async` / `stream_async`), so
`chat_service` can't tell them apart:

| | `langgraph` (default) | `dify` |
|---|---|---|
| Runs | in this process, `providers/deep_agents.py` | external engine over HTTP |
| Tools | plain Python in `agent_tools.py` | installed plugins + MCP servers |
| Provisioning | none — the Firestore spec *is* the agent | creates a Dify app, stores its api_key |
| Available when | the backend is up | `dify.is_up()` says so |

`AGENT_PROVIDERS` in `registry_service.py` is the only place that knows which
providers are agents; it drives the Pro tier floor, the composer's model list
and the homepage gallery. A third runtime = one entry there plus a branch in
`_build_rails`.

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

An **agent** turn adds one thing: as the agent decides, `step` events stream
ahead of the answer and render as the expandable DECISION TRACE. The answer
itself is buffered until the output rails pass — a half-emitted answer can't
be withdrawn if the rails reject it.

## 4. The frontend, layer by layer (`frontend/src/`)

Same MVVM split, enforced by one rule: **views never fetch and never hold
business state.** A `fetch(` inside `views/` (outside `views/admin/`) means
the logic is in the wrong layer.

| Layer | Role | Files |
|---|---|---|
| `models/` | types + the only place that talks to the backend | `types.ts`, `api.ts` (token, SSE parsing, `adminApi`) |
| `viewmodels/` | hooks holding state and logic, no JSX | `useChat.ts` (the busiest file), `useAuth.ts`, `useConversations.ts`, `useAgents.ts`, `useCopy.ts` |
| `views/` | components: render props, call callbacks | `Workspace.tsx`, `Sidebar.tsx`, `MessageBubble.tsx`, `Composer.tsx`, `Markdown.tsx`, `CodeBlock.tsx`, `AgentGallery.tsx`, `UpgradeDialog.tsx`, `AskCard.tsx`, `admin/` |
| `styles/` | one stylesheet per feature area | `chat.css`, `code.css`, `gallery.css`, `admin.css`, … |
| `theme.css` | design tokens: colors, fonts, glows — re-theme here | — |
| `app.css` | **manifest only**: `@import`s `styles/` in cascade order | — |

Notes worth knowing before you edit:

- `views/admin/*` is the deliberate exception to the no-fetch rule: each tab
  is a small CRUD screen calling `adminApi` directly rather than each having
  a near-identical hook.
- Markdown renders **raw HTML disabled** (no `rehype-raw`), so model output
  can't inject markup; links are forced to `target=_blank rel=noopener`.
- Code blocks are intercepted at `pre`, not `code` — react-markdown no longer
  passes an `inline` flag, so "is my parent a `pre`?" is the only reliable
  block-vs-inline test. Highlighting runs via lowlight inside `CodeBlock`
  with a curated language set in `languages.ts` (the obvious plugin bundles
  ~37 languages, +53 kB gzip on the critical path).
- **Adding styles for a feature means a new file in `styles/` plus one
  `@import`** — never appending to a shared tail. Two branches that both
  appended to the old single `app.css` produced a conflict whose resolution
  silently deleted a whole feature's styling.

State is plain `useState` in hooks — no Redux/router. The app has exactly two
screens (gate and workspace) toggled by auth state; the admin panel is an
overlay, and the agent gallery renders on the empty (home) conversation.

## 5. Common changes, step by step

**Branch first.** Every change starts on its own branch off `main`
(`git checkout -b feat/my-thing`); `main` stays releasable and each change
stays reviewable.


**Add an API endpoint**
```python
# backend/routers/hello.py — must start with /api/ (the prod proxy only
# forwards /api/**). Register it in app.py with include_router.
router = APIRouter(prefix="/api")

@router.get("/hello")
async def hello(user: AuthedUser = Depends(verify_firebase_token)):
    return {"hi": user.uid}   # ALWAYS scope data by user.uid
```
Model-calling routes use `Depends(require_quota)` instead — auth *and*
monthly quota; bare token verification leaves the call uncapped. Then add a
function in `models/api.ts` and call it from a hook in `viewmodels/`.

**Add a chat model** — admin panel → MODEL GRID → fill id/label/provider/
model-name/tier → DEPLOY. No code. For a brand-new *provider* (say,
Anthropic), add a branch in `providers/llm.py::build_chat_llm` and add the
provider name to `PROVIDERS` in `services/registry_service.py` +
`views/admin/ModelsTab.tsx`.

**Create an agent** — admin panel → AGENT FORGE → choose a runtime (DEEP
AGENT or DIFY), give it an id, name, instructions and a tool loadout → FORGE.
No code. It appears on the homepage gallery for Pro users immediately.

**Add a deep-agent tool** — write the function in
`backend/providers/agent_tools.py`, decorate with `@tool`, add a
`TOOL_CATALOG` entry:

```python
@tool
async def stock_price(symbol: str) -> str:
    """Look up a stock price. One line of docstring — the model reads it."""
    ...           # return a string; never raise
```
It shows up in the forge arsenal automatically. Tools must return a string
and swallow their own errors — an error message the model can read beats a
traceback that kills the turn.

**Add a Dify agent tool** — install the marketplace plugin (see
`DESIGN.md §5.1e` for the console API calls) and add one entry to
`TOOL_CATALOG` in `providers/dify.py`. If it's an MCP server: admin panel →
MCP LINKS → paste URL. Done — no code at all.

**Gate a feature behind Pro** — tiers live in Firebase custom claims and
`TIER_RANK` orders them. Specialist agents are floored at `pro` by
`effective_min_tier`; the UI shows locked cards with an upgrade dialog, and
the backend independently 403s. Never rely on the UI half alone.

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
| Deep agent answers without using tools | Instructions too soft — say "use your tools for every fact, never answer from memory". Check the trace: no steps means no tool calls were made |
| Deep agent loops | `RECURSION_LIMIT` in `providers/deep_agents.py` caps the loop; a hit means the task needs sub-agents or tighter instructions |
| Agent missing from the gallery | Agents are Pro-floored — check the user's tier; Dify agents also vanish when the engine is unreachable, deep agents never do |
| Styles vanished after a merge | Check `app.css` is still only `@import`s and no `styles/*.css` block was dropped in conflict resolution |
| Image gen 404s the model | Vertex model names drift; probe with `google-genai` SDK (classic Imagen is gone since June 2026) |
| Works locally, 404 in prod | Route not under `/api/` — the Hosting rewrite only forwards `/api/**` |
| Backend logs | local: `logs/backend.log`; prod: Cloud Console → Cloud Run → ai-platform-api → Logs |
