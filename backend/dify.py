"""
Dify integration — NEXUS is the control plane, Dify is the engine.

Two API surfaces of a self-hosted Dify:
  - Console API (what Dify's own web UI uses): create/configure/delete apps,
    mint per-app Service API keys. We authenticate with the Dify admin
    account from .env and never expose this surface to end users.
  - Service API (/v1): run an app (chat-messages). Called per-request with
    the app's own API key, passing the NEXUS user's uid as the Dify `user`
    for attribution — identity propagation into the engine.

Agents created here are registered in the NEXUS model registry with
provider="dify", so they appear in the chat model selector like any LLM and
run inside the same guardrail stages (input rails -> Dify -> output rails).
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger("ai-platform.dify")


class DifyError(RuntimeError):
    pass


# Curated tool catalog: what the AGENT FORGE offers. Keys are stable NEXUS
# ids; values map to Dify tool-provider/tool names (all credential-free).
TOOL_CATALOG: dict[str, dict] = {
    "web_search": {
        "label": "Web Search",
        "provider": "langgenius/duckduckgo/duckduckgo",
        "tool": "ddgo_search",
        "description": "Search the web (DuckDuckGo)",
    },
    "wikipedia": {
        "label": "Wikipedia",
        "provider": "langgenius/wikipedia/wikipedia",
        "tool": "wikipedia_search",
        "description": "Look up encyclopedia articles",
    },
    "web_scraper": {
        "label": "Web Scraper",
        "provider": "webscraper",
        "tool": "webscraper",
        "description": "Fetch and read a web page",
    },
    "current_time": {
        "label": "Current Time",
        "provider": "time",
        "tool": "current_time",
        "description": "Get the current date and time",
    },
}


class DifyClient:
    def __init__(self, base_url: str, admin_email: str, admin_password: str):
        self.base = base_url.rstrip("/")
        self._email = admin_email
        self._password = admin_password
        # Console auth is cookie-based (access_token/csrf_token cookies); the
        # csrf_token must also be echoed as the X-CSRF-Token header.
        self._http = httpx.AsyncClient(timeout=60)
        self._authed = False
        self._up = False
        self._up_at = 0.0

    @property
    def enabled(self) -> bool:
        """Configured — not necessarily reachable (see is_up)."""
        return bool(self.base and self._email and self._password)

    async def is_up(self, ttl: float = 60.0) -> bool:
        """Cheap cached reachability probe, so a stopped engine hides its
        agents from the model list instead of 500-ing at chat time."""
        import time as _time

        if not self.enabled:
            return False
        now = _time.monotonic()
        if self._up_at and (now - self._up_at) < ttl:
            return self._up
        try:
            r = await self._http.get(f"{self.base}/console/api/setup", timeout=3)
            self._up = r.status_code == 200
        except Exception:
            self._up = False
        self._up_at = now
        return self._up

    # ---- console auth ------------------------------------------------------

    async def _login(self) -> None:
        import base64

        r = await self._http.post(
            f"{self.base}/console/api/login",
            # Dify's console expects the password field base64-encoded.
            json={"email": self._email,
                  "password": base64.b64encode(self._password.encode()).decode()},
        )
        if r.status_code != 200:
            raise DifyError(f"Dify console login failed: {r.status_code} {r.text[:200]}")
        self._authed = True

    def _csrf_headers(self) -> dict:
        token = self._http.cookies.get("csrf_token", "")
        return {"X-CSRF-Token": token} if token else {}

    async def _console(self, method: str, path: str, **kwargs) -> httpx.Response:
        if not self._authed:
            await self._login()
        r = await self._http.request(
            method, f"{self.base}/console/api{path}",
            headers=self._csrf_headers(), **kwargs,
        )
        if r.status_code == 401:  # session expired — re-login once
            await self._login()
            r = await self._http.request(
                method, f"{self.base}/console/api{path}",
                headers=self._csrf_headers(), **kwargs,
            )
        return r

    # ---- agent lifecycle (console) ----------------------------------------

    async def create_agent(self, name: str, instructions: str, model: str,
                           description: str = "", tools: list[str] | None = None) -> dict:
        """Create a Dify agent-chat app and mint its Service API key.

        `tools` are keys from TOOL_CATALOG or the dynamic MCP catalog
        (`mcp/<server>/<tool>`); unknown keys are ignored.
        """
        catalog = {**TOOL_CATALOG, **(await self.mcp_tool_catalog() if tools else {})}
        r = await self._console("POST", "/apps", json={
            "name": name,
            "description": description,
            "mode": "agent-chat",
            "icon_type": "emoji",
            "icon": "🤖",
            "icon_background": "#0d0e1a",
        })
        if r.status_code != 201:
            raise DifyError(f"App create failed: {r.status_code} {r.text[:300]}")
        app = r.json()
        app_id = app["id"]

        # Configure the agent: system prompt + model.
        r = await self._console("POST", f"/apps/{app_id}/model-config", json={
            "pre_prompt": instructions,
            "prompt_type": "simple",
            "model": {
                "provider": "langgenius/vertex_ai/vertex_ai",
                "name": model,
                "mode": "chat",
                "completion_params": {},
            },
            "agent_mode": {
                "enabled": True,
                "strategy": "function_call",
                "tools": [
                    {
                        "provider_id": spec["provider"],
                        "provider_type": spec.get("provider_type", "builtin"),
                        "provider_name": spec["provider"],
                        "tool_name": spec["tool"],
                        "tool_label": spec["label"],
                        "tool_parameters": {},
                        "enabled": True,
                    }
                    for key in (tools or [])
                    if (spec := catalog.get(key))
                ],
                # Room for multi-step missions: retries after a tool error and
                # strategy changes after a bad result both cost iterations.
                "max_iteration": 12,
            },
            "user_input_form": [],
        })
        if r.status_code != 200:
            log.warning("model-config failed (%s): %s", r.status_code, r.text[:200])

        # Mint the Service API key used to run this app.
        r = await self._console("POST", f"/apps/{app_id}/api-keys")
        if r.status_code not in (200, 201):
            raise DifyError(f"API key mint failed: {r.status_code} {r.text[:200]}")
        api_key = r.json()["token"]

        return {"app_id": app_id, "api_key": api_key, "name": name}

    async def delete_agent(self, app_id: str) -> None:
        r = await self._console("DELETE", f"/apps/{app_id}")
        if r.status_code not in (200, 204):
            raise DifyError(f"App delete failed: {r.status_code} {r.text[:200]}")

    async def list_apps(self) -> list[dict]:
        r = await self._console("GET", "/apps", params={"page": 1, "limit": 50})
        if r.status_code != 200:
            raise DifyError(f"App list failed: {r.status_code}")
        return [
            {"id": a["id"], "name": a["name"], "mode": a["mode"]}
            for a in r.json().get("data", [])
        ]

    # ---- MCP servers (console) --------------------------------------------

    async def add_mcp_server(self, name: str, server_url: str, server_identifier: str,
                             headers: dict[str, str] | None = None) -> dict:
        """Register an MCP server as a Dify tool provider and discover its tools."""
        r = await self._console("POST", "/workspaces/current/tool-provider/mcp", json={
            "server_url": server_url,
            "name": name,
            "icon": "🔌",
            "icon_type": "emoji",
            "icon_background": "#0d0e1a",
            "server_identifier": server_identifier,
            "headers": headers or {},
        })
        if r.status_code not in (200, 201):
            raise DifyError(f"MCP server add failed: {r.status_code} {r.text[:300]}")
        provider = r.json()
        provider_id = provider.get("id")

        # Trigger connection/refresh so the tool list is populated.
        r2 = await self._console(
            "GET", f"/workspaces/current/tool-provider/mcp/update/{provider_id}"
        )
        if r2.status_code != 200:
            log.warning("MCP tool refresh returned %s: %s", r2.status_code, r2.text[:200])

        detail = await self._console(
            "GET", f"/workspaces/current/tool-provider/mcp/tools/{provider_id}"
        )
        tools = detail.json().get("tools", []) if detail.status_code == 200 else []
        return {
            "provider_id": provider_id,
            "name": name,
            "server_identifier": server_identifier,
            "tools": [{"name": t.get("name"),
                       "description": (t.get("description") or {}).get("en_US", "")
                       if isinstance(t.get("description"), dict) else str(t.get("description", ""))}
                      for t in tools],
        }

    async def list_mcp_servers(self) -> list[dict]:
        r = await self._console("GET", "/workspaces/current/tools/mcp")
        if r.status_code != 200:
            raise DifyError(f"MCP list failed: {r.status_code} {r.text[:200]}")
        out = []
        for p in r.json():
            tools = p.get("tools") or []
            out.append({
                "provider_id": p.get("id"),
                "name": (p.get("name") or "").split("/")[-1],
                "server_url": p.get("server_url", ""),
                "tools": [t.get("name") for t in tools],
            })
        return out

    async def delete_mcp_server(self, provider_id: str) -> None:
        r = await self._console(
            "DELETE", "/workspaces/current/tool-provider/mcp",
            json={"provider_id": provider_id},
        )
        if r.status_code not in (200, 204):
            raise DifyError(f"MCP delete failed: {r.status_code} {r.text[:200]}")

    async def mcp_tool_catalog(self) -> dict[str, dict]:
        """Dynamic catalog entries for every registered MCP server's tools.

        Keys look like `mcp/<server>/<tool>`; entries carry provider_type
        "mcp" so create_agent equips them correctly.
        """
        catalog: dict[str, dict] = {}
        try:
            for server in await self.list_mcp_servers():
                for tool in server["tools"]:
                    catalog[f"mcp/{server['name']}/{tool}"] = {
                        "label": f"{server['name']}: {tool}",
                        "provider": server["provider_id"],
                        "tool": tool,
                        "provider_type": "mcp",
                        "description": f"MCP tool {tool} from {server['name']}",
                    }
        except Exception as exc:
            log.warning("MCP catalog fetch failed: %s", exc)
        return catalog

    # ---- running (service API) --------------------------------------------

    async def run_agent(self, api_key: str, query: str, *, user_id: str,
                        conversation_id: str | None = None):
        """
        Run an agent, streaming its work as it happens.

        Yields ("step", {...}) each time the agent finishes a tool call — its
        reasoning, which tool it picked, the arguments it chose and what came
        back — and ("token", str) for the answer text. Agent apps are
        streaming-only, so this is the only way to run them.
        """
        import json as _json

        steps: dict[int, dict] = {}
        async with httpx.AsyncClient(timeout=300) as c:
            async with c.stream(
                "POST", f"{self.base}/v1/chat-messages",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "query": query,
                    "inputs": {},
                    "user": user_id,  # identity propagation
                    "response_mode": "streaming",
                    **({"conversation_id": conversation_id} if conversation_id else {}),
                },
            ) as r:
                if r.status_code != 200:
                    body = (await r.aread()).decode(errors="replace")
                    raise DifyError(f"Dify chat failed: {r.status_code} {body[:300]}")

                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        evt = _json.loads(line[6:])
                    except ValueError:
                        continue

                    kind = evt.get("event")
                    if kind == "agent_thought":
                        # Dify updates the same position as the step unfolds
                        # (thought → tool+input → observation), so merge.
                        pos = int(evt.get("position") or 0)
                        step = steps.setdefault(pos, {"position": pos})
                        for field in ("thought", "tool", "tool_input", "observation"):
                            value = evt.get(field)
                            if value:
                                step[field] = value
                        # Emit once the round-trip is complete.
                        if step.get("tool") and step.get("observation") and not step.get("_sent"):
                            step["_sent"] = True
                            yield ("step", {k: v for k, v in step.items()
                                            if not k.startswith("_")})
                    elif kind in ("message", "agent_message"):
                        yield ("token", evt.get("answer", ""))
                    elif kind == "error":
                        raise DifyError(f"Dify run error: {evt.get('message', '')[:300]}")

    async def chat(self, api_key: str, query: str, *, user_id: str,
                   conversation_id: str | None = None) -> dict:
        """Blocking convenience wrapper over run_agent."""
        answer, steps = [], []
        async for kind, payload in self.run_agent(
            api_key, query, user_id=user_id, conversation_id=conversation_id
        ):
            (steps if kind == "step" else answer).append(payload)
        return {"answer": "".join(answer), "steps": steps,
                "conversation_id": conversation_id}


REFUSAL_TEXT = "I can't help with that"


def _text(content) -> str:
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if p.get("type") == "text")
    return content


class DifyRails:
    """
    Rails-shaped adapter so a Dify agent slots into the chat pipeline like
    any model: NeMo INPUT rails screen the text (using the platform's default
    screening rails), the agent runs in Dify, OUTPUT rails screen the answer.
    """

    needs_user = True  # generate_async/stream_async take user_id

    def __init__(self, client: DifyClient, api_key: str, screen_rails):
        self._client = client
        self._api_key = api_key
        self._screen = screen_rails

    def _build_query(self, messages: list[dict]) -> str:
        """Dify chat-messages takes a single query; fold in recent context."""
        turns = [m for m in messages if m["role"] in ("user", "assistant")]
        last = _text(turns[-1]["content"])
        prior = turns[:-1][-6:]  # up to 3 prior exchanges for context
        if not prior:
            return last
        transcript = "\n".join(f"{m['role']}: {_text(m['content'])[:400]}" for m in prior)
        return f"(Conversation so far:\n{transcript})\n\nuser: {last}"

    async def _screen_input(self, text_msgs: list[dict]) -> str | None:
        """Returns the refusal text if the input rails blocked this turn."""
        checked = await self._screen.generate_async(
            messages=text_msgs, options={"rails": ["input"]}
        )
        inp = checked.response[0]["content"]
        return inp if REFUSAL_TEXT in inp else None

    async def _screen_output(self, text_msgs: list[dict], content: str) -> str:
        out = await self._screen.generate_async(
            messages=text_msgs + [{"role": "assistant", "content": content}],
            options={"rails": ["output"]},
        )
        return out.response[0]["content"]

    async def generate_async(self, messages: list[dict], *, user_id: str = "anonymous") -> dict:
        text_msgs = [{"role": m["role"], "content": _text(m["content"])} for m in messages]

        refusal = await self._screen_input(text_msgs)
        if refusal:
            return {"role": "assistant", "content": refusal, "steps": []}

        result = await self._client.chat(
            self._api_key, self._build_query(messages), user_id=user_id
        )
        return {
            "role": "assistant",
            "content": await self._screen_output(text_msgs, result["answer"]),
            "steps": result["steps"],
        }

    async def stream_async(self, messages: list[dict], *, user_id: str = "anonymous"):
        """
        Yields {"kind": "step", ...} as the agent makes each decision, then
        {"kind": "token", ...} for the guarded answer. Decisions surface live;
        the answer is still screened by the output rails before any of it is
        emitted.
        """
        text_msgs = [{"role": m["role"], "content": _text(m["content"])} for m in messages]

        refusal = await self._screen_input(text_msgs)
        if refusal:
            yield {"kind": "token", "text": refusal}
            return

        answer, steps = [], []
        async for kind, payload in self._client.run_agent(
            self._api_key, self._build_query(messages), user_id=user_id
        ):
            if kind == "step":
                steps.append(payload)
                yield {"kind": "step", "step": payload}
            else:
                answer.append(payload)

        content = await self._screen_output(text_msgs, "".join(answer))
        for i in range(0, len(content), 24):
            yield {"kind": "token", "text": content[i:i + 24]}
