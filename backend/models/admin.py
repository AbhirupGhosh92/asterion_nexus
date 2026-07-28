"""Admin control-plane schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TierUpdate(BaseModel):
    tier: str


class DisabledUpdate(BaseModel):
    disabled: bool


class QuotaConfigUpdate(BaseModel):
    enabled: bool | None = None
    limits: dict[str, int] | None = None  # {"free": 5, "pro": 100, "admin": -1}


class QuotaOverrideUpdate(BaseModel):
    limit: int | None = None  # None clears the override; -1 = unlimited


class ModelSpec(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9\-_.]{1,40}$")
    label: str
    provider: str
    model: str
    min_tier: str = "free"
    enabled: bool = True
    extra: dict = Field(default_factory=dict)


class AgentSpec(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9\-_.]{1,40}$")
    name: str
    instructions: str
    model: str = "gemini-2.5-flash"
    min_tier: str = "free"
    tools: list[str] = Field(default_factory=list)


class MCPServerSpec(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9\-_.]{1,40}$")
    server_url: str
    headers: dict[str, str] = Field(default_factory=dict)


class EngineAction(BaseModel):
    action: str  # start | stop | restart
