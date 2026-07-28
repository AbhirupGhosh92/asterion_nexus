"""
In-process tools for LangGraph deep agents.

Dify agents get their tools from installed plugins; a deep agent runs inside
this process, so its tools are plain Python. Everything here is stdlib or
httpx (already a dependency) — no extra packages, and every tool returns a
string, never raises: a tool error the model can read is worth more than a
traceback that kills the turn.

Add a tool: write the function, decorate with @tool, add it to TOOL_CATALOG.
It appears in the admin forge automatically.
"""

from __future__ import annotations

import ast
import logging
import operator
from datetime import datetime, timezone

import httpx
from langchain_core.tools import tool

log = logging.getLogger("ai-platform.agent-tools")

_TIMEOUT = 20.0
_MAX_CHARS = 4000  # keep observations inside the model's context budget


@tool
async def current_time() -> str:
    """Get the current UTC date and time. Use for anything time-relative."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC (%A)")


@tool
async def wikipedia(query: str) -> str:
    """Look up a topic on Wikipedia. Returns the summary of the best match."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as http:
            search = await http.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "query", "list": "search", "srsearch": query,
                        "format": "json", "srlimit": 1},
                headers={"User-Agent": "NEXUS-AI-Platform/1.0"},
            )
            hits = search.json().get("query", {}).get("search", [])
            if not hits:
                return f"No Wikipedia article found for {query!r}."
            title = hits[0]["title"]
            page = await http.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}",
                headers={"User-Agent": "NEXUS-AI-Platform/1.0"},
            )
            data = page.json()
        return f"{data.get('title', title)}: {data.get('extract', '')[:_MAX_CHARS]}"
    except Exception as exc:
        return f"Wikipedia lookup failed: {exc}"


@tool
async def web_search(query: str) -> str:
    """Search the web. Returns the top results with titles, snippets and URLs."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as http:
            r = await http.get(
                "https://duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (compatible; NEXUS-AI-Platform/1.0)"},
            )
            r.raise_for_status()
            html = r.text
    except Exception as exc:
        return f"Web search failed: {exc}. Try the wikipedia or fetch_url tool instead."

    import html as html_mod
    import re

    results = []
    for m in re.finditer(
        r'result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?result__snippet"[^>]*>(.*?)</a>',
        html, re.S,
    ):
        url, title, snippet = (html_mod.unescape(re.sub(r"<[^>]+>", "", g)).strip()
                               for g in m.groups())
        results.append(f"- {title}\n  {snippet}\n  {url}")
        if len(results) == 5:
            break
    return "\n".join(results) if results else f"No results for {query!r}."


@tool
async def fetch_url(url: str) -> str:
    """Fetch a web page and return its readable text. Use after web_search."""
    if not url.startswith(("http://", "https://")):
        return "fetch_url needs a full http(s) URL."
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as http:
            r = await http.get(url, headers={"User-Agent": "NEXUS-AI-Platform/1.0"})
            r.raise_for_status()
            body = r.text
    except Exception as exc:
        return f"Could not fetch {url}: {exc}"

    import html as html_mod
    import re

    body = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", body)
    text = html_mod.unescape(re.sub(r"<[^>]+>", " ", body))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_MAX_CHARS] or "(page had no readable text)"


# Arithmetic only — no names, no calls, no attribute access, so a model can't
# reach the interpreter through this tool.
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("only numbers and + - * / // % ** are allowed")


@tool
async def calculator(expression: str) -> str:
    """Evaluate an arithmetic expression, e.g. "(1234 * 5.5) / 3"."""
    try:
        return str(_eval(ast.parse(expression, mode="eval").body))
    except Exception as exc:
        return f"Could not evaluate {expression!r}: {exc}"


TOOL_CATALOG: dict[str, dict] = {
    "current_time": {"label": "Current Time", "fn": current_time,
                     "description": "Read the current UTC date and time"},
    "web_search": {"label": "Web Search", "fn": web_search,
                   "description": "Search the web (DuckDuckGo)"},
    "wikipedia": {"label": "Wikipedia", "fn": wikipedia,
                  "description": "Look up encyclopedia articles"},
    "fetch_url": {"label": "Fetch URL", "fn": fetch_url,
                  "description": "Fetch and read a web page"},
    "calculator": {"label": "Calculator", "fn": calculator,
                   "description": "Evaluate arithmetic safely"},
}


def resolve(names: list[str]) -> list:
    """Tool objects for these catalog keys; unknown keys are skipped."""
    picked = [TOOL_CATALOG[n]["fn"] for n in names if n in TOOL_CATALOG]
    unknown = [n for n in names if n not in TOOL_CATALOG]
    if unknown:
        log.warning("Ignoring unknown deep-agent tools: %s", unknown)
    return picked
