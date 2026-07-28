# providers/ — Model layer (external brains)

LLMs, the Dify engine, and the adapters that make them all look the same to
`services/chat_service`.

| File | Provides |
|---|---|
| `llm.py` | `build_chat_llm(provider, …, model=None)` → a LangChain chat model. One branch per provider (`vertexai`, `ollama`, `mock`). Pass `model=` rather than mutating env. |
| `deep_agents.py` | `build_agent()` + `DeepAgentRails` — LangGraph/deepagents specialists that run **in this process**. The default runtime for new agents. |
| `agent_tools.py` | The deep agent arsenal: plain Python tools (`current_time`, `web_search`, `wikipedia`, `fetch_url`, `calculator`) + `TOOL_CATALOG`. |
| `dify.py` | `DifyClient` (console API: agents, plugins, MCP servers, `run_agent` streaming) + `DifyRails`, the guarded adapter + `TOOL_CATALOG`. |
| `image_rails.py` | `ImageGenRails` — prompt → Gemini image model → Cloud Storage → `[image:<id>]` token. Retries 429s with backoff. |

## The rails contract

Anything `chat_service` can call must expose:

```python
async def generate_async(messages) -> dict | GenerationResponse
async def stream_async(messages) -> AsyncIterator[str | dict]
```

Adapters needing the caller's identity set `needs_user = True` and accept
`user_id=` on both methods (Dify agents, image generation).

## Two agent runtimes

`langgraph` (deep agents) and `dify` both satisfy the rails contract above,
so `chat_service` cannot tell them apart — `services/registry_service.py`
picks one from `provider` and `AGENT_PROVIDERS` covers both.

| | `langgraph` | `dify` |
|---|---|---|
| Runs | in this process | external engine (docker / GCE VM) |
| Tools | Python, `agent_tools.py` | installed plugins + MCP servers |
| Provisioning | none — the Firestore spec *is* the agent | creates a Dify app, stores its api_key |
| Availability | whenever the backend is up | needs `dify.is_up()` |

New agents default to `langgraph`: no engine to keep alive, no second system
to deploy, and tools are ordinary Python you can test directly.

**Adding a deep-agent tool**: write the function in `agent_tools.py`,
decorate with `@tool`, add a `TOOL_CATALOG` entry. It appears in the admin
forge automatically. Tools must return a string and never raise — an error
the model can read beats a traceback that kills the turn.

Steps stream live, but the **answer is buffered until the output rails pass**
— a half-emitted answer can't be withdrawn if the rails reject it.

## Hard-won notes

- Dify console auth is cookie + CSRF, and the login password must be
  **base64-encoded**. Agent-chat apps are **streaming-only**.
- Classic Imagen publisher models 404 on Vertex since June 2026 — image
  generation uses `gemini-2.5-flash-image` via the `google-genai` SDK.
- NeMo Guardrails **drops arbitrary system messages** (it builds its own
  prompt). Instructions that must reach the model on the rails path belong in
  `guardrails/config.yml`, not a system message.
