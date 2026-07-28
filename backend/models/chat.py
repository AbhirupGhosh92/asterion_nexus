"""Chat domain schemas — the "Model" layer for conversation traffic."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant|system)$")
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    conversation_id: str | None = None
    use_memory: bool = True
    model: str | None = None      # registry model id; None = default
    attachments: list[str] = []   # upload ids attached to the last message


class AgentStep(BaseModel):
    """One autonomous decision an agent made, surfaced as a trace."""

    position: int = 0
    thought: str | None = None
    tool: str | None = None
    tool_input: str | None = None
    observation: str | None = None


class ChatResponse(BaseModel):
    content: str
    conversation_id: str | None
    guardrail_triggered: bool = False
    steps: list[AgentStep] = []
