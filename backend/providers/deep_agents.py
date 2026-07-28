"""
LangGraph deep agents — in-process specialist agents.

The second agent runtime, alongside Dify. A Dify agent lives in an external
engine reached over HTTP; a deep agent is a LangGraph graph built here from a
Firestore spec, with tools that are plain Python (`agent_tools.py`). Nothing
outside this file changes: `DeepAgentRails` exposes the same rails contract as
`DifyRails`, so `chat_service` cannot tell them apart.

Guardrails work exactly as they do for Dify: NeMo INPUT rails screen the
prompt, the agent runs, OUTPUT rails screen the answer before a single token
reaches the user.
"""

from __future__ import annotations

import logging

from core.config import REFUSAL_TEXT
from providers import agent_tools

log = logging.getLogger("ai-platform.deep-agents")

# A deep agent plans, calls tools and reflects, so it needs room to loop —
# but not unbounded room, since every step is a model call the user pays for.
RECURSION_LIMIT = 40


def _text(content) -> str:
    """Flatten a possibly-multimodal content field down to its text."""
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict)
                        and p.get("type") == "text")
    return content or ""


def build_agent(llm, instructions: str, tools: list[str], subagents: list[dict] | None = None):
    """Compile a deep agent: planner + tool loop + optional sub-agents."""
    from deepagents import create_deep_agent

    return create_deep_agent(
        model=llm,
        tools=agent_tools.resolve(tools),
        system_prompt=instructions,
        subagents=subagents or [],
    )


class DeepAgentRails:
    """
    Rails-shaped adapter around a compiled LangGraph deep agent.

    Steps stream live as the agent decides; the answer is buffered, screened
    by the output rails, and only then chunked out — the same ordering Dify
    agents use, because a half-emitted answer cannot be un-emitted if the
    rails reject it.
    """

    needs_user = True  # generate_async/stream_async take user_id

    def __init__(self, agent, screen_rails):
        self._agent = agent
        self._screen = screen_rails

    # ---- guardrail stages -------------------------------------------------

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

    # ---- graph plumbing ---------------------------------------------------

    @staticmethod
    def _to_langchain(messages: list[dict]) -> list:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        cls = {"user": HumanMessage, "assistant": AIMessage, "system": SystemMessage}
        return [cls.get(m["role"], HumanMessage)(content=_text(m["content"]))
                for m in messages]

    async def _run(self, messages: list[dict], user_id: str):
        """
        Drive the graph, yielding ("step", step) as decisions land and
        returning the final answer text.

        Tool calls and their results arrive in separate updates, so calls are
        held by id until the matching ToolMessage shows up — that's what
        turns two events into one complete step for the UI's decision trace.
        """
        pending: dict[str, dict] = {}
        answer = ""
        position = 0

        stream = self._agent.astream(
            {"messages": self._to_langchain(messages)},
            config={"recursion_limit": RECURSION_LIMIT,
                    "metadata": {"user_id": user_id}},
            stream_mode="updates",
        )

        async for update in stream:
            for node_state in (update or {}).values():
                for msg in (node_state or {}).get("messages", []) or []:
                    tool_calls = getattr(msg, "tool_calls", None) or []
                    if tool_calls:
                        for call in tool_calls:
                            position += 1
                            pending[call["id"]] = {
                                "position": position,
                                "thought": _text(getattr(msg, "content", "")),
                                "tool": call["name"],
                                "tool_input": str(call.get("args", ""))[:600],
                                "observation": "",
                            }
                        continue

                    call_id = getattr(msg, "tool_call_id", None)
                    if call_id:  # ToolMessage: completes an earlier decision
                        step = pending.pop(call_id, None)
                        if step:
                            step["observation"] = str(getattr(msg, "content", ""))[:1200]
                            yield "step", step
                        continue

                    text = _text(getattr(msg, "content", ""))
                    if text:
                        answer = text  # last plain AIMessage wins

        # A tool that never returned still deserves a trace entry.
        for step in pending.values():
            step["observation"] = "(no result)"
            yield "step", step

        yield "answer", answer

    # ---- rails contract ---------------------------------------------------

    async def generate_async(self, messages: list[dict], *, user_id: str = "anonymous") -> dict:
        text_msgs = [{"role": m["role"], "content": _text(m["content"])} for m in messages]

        refusal = await self._screen_input(text_msgs)
        if refusal:
            return {"role": "assistant", "content": refusal, "steps": []}

        steps, answer = [], ""
        async for kind, payload in self._run(messages, user_id):
            if kind == "step":
                steps.append(payload)
            else:
                answer = payload

        return {
            "role": "assistant",
            "content": await self._screen_output(text_msgs, answer),
            "steps": steps,
        }

    async def stream_async(self, messages: list[dict], *, user_id: str = "anonymous"):
        text_msgs = [{"role": m["role"], "content": _text(m["content"])} for m in messages]

        refusal = await self._screen_input(text_msgs)
        if refusal:
            yield {"kind": "token", "text": refusal}
            return

        answer = ""
        async for kind, payload in self._run(messages, user_id):
            if kind == "step":
                yield {"kind": "step", "step": payload}
            else:
                answer = payload

        content = await self._screen_output(text_msgs, answer)
        for i in range(0, len(content), 24):
            yield {"kind": "token", "text": content[i:i + 24]}
