# providers/ — Model layer (external brains)

LLMs, the Dify engine, and the adapters that make them all look the same to
`services/chat_service`.

| File | Provides |
|---|---|
| `llm.py` | `build_chat_llm(provider)` → a LangChain chat model. One branch per provider (`vertexai`, `ollama`, `mock`). Add providers here. |
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

## Hard-won notes

- Dify console auth is cookie + CSRF, and the login password must be
  **base64-encoded**. Agent-chat apps are **streaming-only**.
- Classic Imagen publisher models 404 on Vertex since June 2026 — image
  generation uses `gemini-2.5-flash-image` via the `google-genai` SDK.
- NeMo Guardrails **drops arbitrary system messages** (it builds its own
  prompt). Instructions that must reach the model on the rails path belong in
  `guardrails/config.yml`, not a system message.
