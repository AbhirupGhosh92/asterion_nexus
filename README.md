# NEXUS — your own AI platform

A self-hosted, ChatGPT-class AI platform you fully control: guarded chat on
Google Gemini, per-user conversation history, AI agents with tools (web
search, Wikipedia, any MCP server), image generation, multimodal uploads,
role-based access, and a built-in admin control plane — wrapped in a
cyberpunk UI. **Serverless by default: $0 while idle.**

Built pair-programming with [Claude Code](https://claude.com/claude-code).

## Features

- 💬 **Guarded chat** — every message passes [NVIDIA NeMo Guardrails](https://github.com/NVIDIA/NeMo-Guardrails):
  input rails block jailbreaks *before* the model runs, output rails screen
  responses for leaks.
- 🗂 **ChatGPT-style topics** — conversations saved per user in Firestore,
  auto-titled by the LLM.
- 🧠 **Long-term memory** — Vertex AI Memory Bank recalls facts about each
  user across conversations, isolated per identity.
- ⚡ **Agent Forge** — create AI agents (custom instructions + tools) from
  the admin panel; powered by [Dify](https://github.com/langgenius/dify).
  Tools include web search, Wikipedia, web scraping, time — plus **any MCP
  server** you link by URL.
- 🎨 **Image Studio** — prompt-to-image via Gemini's image model, rendered
  inline, stored privately per user.
- 📎 **Multimodal input** — upload images/audio/video for Gemini to analyze.
- 🛡 **RBAC + admin plane** — free/pro/admin tiers via Firebase custom
  claims; admins (an email allowlist) manage users, models, agents, and MCP
  servers from the UI.
- ⚡ **Monthly API quotas** — cap calls per user (default: 5/month on free),
  set per tier or per user from the admin panel, auto-resetting each month.
  Users see their remaining calls live; failed calls are refunded.
- 🌐 **Serverless deploy** — Cloud Run (scale-to-zero) + Firebase Hosting +
  Firestore + Cloud Storage, provisioned by Terraform, deployed by one script.

## Architecture

```
Browser ── Firebase Hosting ──► Cloud Run (FastAPI)
  React UI     /api/** rewrite      │  Firebase Auth verify → RBAC
                                    │  NeMo Guardrails (in/out rails)
                                    ├─► Vertex AI  (Gemini chat + image)
                                    ├─► Firestore  (history, model registry)
                                    ├─► Storage    (uploads, generated images)
                                    ├─► Memory Bank (per-user long-term memory)
                                    └─► Dify engine (agents + tools; local
                                        docker in dev, optional VM in cloud)
```

Two rules make it secure: clients only ever talk to the FastAPI backend, and
every data access is scoped by the uid inside the *verified* Firebase token.
Docs: [docs/DESIGN.md](docs/DESIGN.md) (architecture & rationale) ·
[docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) (hands-on walkthrough).

## Prerequisites

- A **GCP project with billing enabled** ([console.cloud.google.com](https://console.cloud.google.com))
- A **Firebase web app** in that project: [Firebase console](https://console.firebase.google.com)
  → your project → Add app → Web. Enable **Authentication → Google** provider.
  (Everything else — Firestore, Storage, Hosting sites — the deploy script creates.)
- CLI tools: `gcloud`, `terraform` (≥1.7), `node` (≥20), `python3`
- For local dev with agents: Docker (e.g. [OrbStack](https://orbstack.dev) on macOS)

## Deploy to the cloud (one command)

```bash
git clone https://github.com/AbhirupGhosh92/asterion_nexus && cd asterion_nexus

# 1. Authenticate
gcloud auth login
gcloud auth application-default login

# 2. Configure — your values stay out of git
cp deploy.config.example deploy.config     # edit: project id, site name, admin email
cp frontend/.env.example frontend/.env.local   # paste your Firebase web app config

# 3. Ship it
./deploy.sh
```

The script enables APIs, creates Firestore/Storage/Hosting if missing,
provisions everything with Terraform, builds the backend on Cloud Build,
deploys, and prints your endpoints:

```
Frontend    https://<your-site>.web.app
Backend     https://ai-platform-api-….run.app   (via the frontend's /api/**)
Dify        http://<vm-ip>                       (if WITH_DIFY=true)
```

Sign in with Google — the email(s) in `ADMIN_EMAILS` get the ⚙ ADMIN panel.

### Agents in the cloud (optional, the one non-serverless piece)

Dify needs always-on Postgres/Redis, so cloud agents require a small VM
(~$25–50/mo). Set `WITH_DIFY="true"` in `deploy.config` and re-run
`./deploy.sh` — Terraform creates the VM, and the script boots Dify,
installs the tool plugins, and wires Gemini access automatically. The Dify
admin password is generated and stored only in Secret Manager (the deploy
summary shows how to read it). With `WITH_DIFY="false"`, agent models are
simply hidden — everything else works.

> ⚠ The bundled Dify VM serves HTTP on a public IP. Restrict the firewall
> to your own IP (edit `google_compute_firewall.dify_http` in
> `infra/main.tf`) or front it with a load balancer + TLS for serious use.

To stop paying for it again, tear down **only** the Dify engine:

```bash
./teardown-dify.sh                 # destroys the VM, IP, firewall, service account
./teardown-dify.sh --purge-agents  # also removes agent entries from the registry
```

Everything serverless (chat, history, users, models, uploads, image
generation, the admin panel) keeps running untouched at $0 idle. Agent
models simply disappear from the selector while no engine is reachable.
Flip `WITH_DIFY="true"` and redeploy whenever you want them back.

## Local development

```bash
cd backend && uv venv --python 3.12 .venv \
  && uv pip install --python .venv/bin/python -r requirements.txt \
  && cp .env.example .env                  # edit values
cd ../frontend && npm install && cd ..

./start.sh          # Dify (docker) + backend :8080 + frontend :5173
./stop.sh [--all]   # stop; --all also stops Dify
```

No GCP at all? Set `LLM_PROVIDER=mock` and `AUTH_DISABLED=1` in
`backend/.env` and run `./start.sh --no-auth` — the full UI works against a
placeholder model.

## Extending it

| I want to… | Do this |
|---|---|
| Change usage limits | Admin panel → QUOTAS (tiers) or OPERATIVES (per user) |
| Add a chat model | Admin panel → MODEL GRID (no code) |
| Add an LLM provider | One branch in `backend/providers/llm.py` |
| Create an agent | Admin panel → AGENT FORGE (no code) |
| Add an agent tool | Install the Dify plugin + one `TOOL_CATALOG` entry in `backend/providers/dify.py` |
| Connect an MCP server | Admin panel → MCP LINKS → paste URL (no code) |
| Tune safety rules | Edit the plain-English prompts in `backend/guardrails/config.yml` |
| Re-theme the UI | Edit CSS variables in `frontend/src/theme.css` |

Full recipes: [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md).

## Cost

| Component | Idle | In use |
|---|---|---|
| Cloud Run / Hosting / Auth | $0 | pennies (free tiers are generous) |
| Firestore `(default)` / Storage | $0 | free tier, then pennies |
| Vertex AI (Gemini) | $0 | per token / per image |
| Dify VM (only if `WITH_DIFY=true`) | ~$25–50/mo | same |

## Security notes

- No secrets in the repo: runtime config lives in `deploy.config`,
  `backend/.env`, and `frontend/.env.local` — all gitignored (templates
  provided). Cloud secrets live in Secret Manager.
- Cloud Run is network-open (required by Hosting rewrites) but every route
  verifies a Firebase ID token; unauthenticated calls get 401.
- Admin is an identity allowlist (`ADMIN_EMAILS`), separate from user tiers.

## License

MIT — see [LICENSE](LICENSE).
