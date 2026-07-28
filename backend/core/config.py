"""
Environment configuration, read once and shared.

Every env var the platform understands is declared here so you can see the
whole surface in one place instead of grepping for os.getenv.
"""

from __future__ import annotations

import os

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")  # vertexai | ollama | mock
GCP_PROJECT = os.getenv("GCP_PROJECT", "")
GCP_REGION = os.getenv("GCP_REGION", "us-central1")
GUARDRAILS_CONFIG_PATH = os.getenv("GUARDRAILS_CONFIG_PATH", "guardrails")
DIFY_BASE_URL = os.getenv("DIFY_BASE_URL", "")
DIFY_ADMIN_EMAIL = os.getenv("DIFY_ADMIN_EMAIL", "")
DIFY_ADMIN_PASSWORD = os.getenv("DIFY_ADMIN_PASSWORD", "")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
STORAGE_BUCKET = os.getenv(
    "STORAGE_BUCKET", f"{GCP_PROJECT}.firebasestorage.app" if GCP_PROJECT else ""
)

# Text the guardrails emit when a rail refuses; used to flag refusals.
REFUSAL_TEXT = "I can't help with that"

# Interaction protocol for raw-LLM paths (multimodal). The rails-wrapped path
# gets this from guardrails/config.yml instead — NeMo builds its own prompt
# and drops arbitrary system messages.
ASK_PROTOCOL = """\
When you need the user to make a choice before you can continue, do not ask \
in prose. Instead reply with ONLY a fenced block like this:

```ask
{"question": "Which database should I use?", "multiSelect": false, "options": [
  {"label": "PostgreSQL", "description": "Relational, great for structured data"},
  {"label": "MongoDB", "description": "Document store, flexible schema"}
]}
```

Rules: 2-4 options, each label under 5 words, description one short line. \
Set "multiSelect": true only when several answers can apply together. Use \
this only for genuine either/or decisions you cannot make yourself — never \
for questions you can answer, and never more than one block per reply."""
