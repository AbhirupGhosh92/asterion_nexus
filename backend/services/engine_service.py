"""
Dify engine operations — status and lifecycle, for the admin panel.

Two deployment shapes are supported:

  docker   the compose stack on this machine (local dev). Controllable when
           DIFY_COMPOSE_DIR points at the compose directory.
  vm       a Compute Engine instance (WITH_DIFY=true). Controllable when
           DIFY_VM_NAME is set; start/stop is what actually pauses billing.

Anything else (a hosted/external Dify) is status-only. Lifecycle commands are
fixed constants — nothing from the request reaches a shell.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys

log = logging.getLogger("ai-platform.dify_ops")

COMPOSE_DIR = os.getenv("DIFY_COMPOSE_DIR", "")
VM_NAME = os.getenv("DIFY_VM_NAME", "")
VM_ZONE = os.getenv("DIFY_VM_ZONE", "")
GCP_PROJECT = os.getenv("GCP_PROJECT", "")

# OrbStack/Docker Desktop aren't on a service's PATH by default.
_EXTRA_PATHS = [
    os.path.expanduser("~/.orbstack/bin"),
    "/usr/local/bin",
    "/opt/homebrew/bin",
]


def _docker_bin() -> str | None:
    path = os.pathsep.join([os.environ.get("PATH", ""), *_EXTRA_PATHS])
    return shutil.which("docker", path=path)


def mode() -> str:
    if VM_NAME:
        return "vm"
    if COMPOSE_DIR and _docker_bin():
        return "docker"
    return "external" if os.getenv("DIFY_BASE_URL") else "none"


async def _run(*args: str, cwd: str | None = None, timeout: int = 180) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "PATH": os.pathsep.join(
            [os.environ.get("PATH", ""), *_EXTRA_PATHS])},
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timed out"
    return proc.returncode or 0, (out or b"").decode(errors="replace")[-4000:]


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #
async def _containers() -> dict | None:
    docker = _docker_bin()
    if not (docker and COMPOSE_DIR):
        return None
    code, out = await _run(docker, "compose", "ps", "--format", "{{.Name}}\t{{.State}}",
                           cwd=COMPOSE_DIR, timeout=30)
    if code != 0:
        return {"running": 0, "total": 0, "error": out.strip()[:200]}
    rows = [line.split("\t") for line in out.strip().splitlines() if "\t" in line]
    return {
        "running": sum(1 for r in rows if r[1].lower().startswith("running")),
        "total": len(rows),
        "names": [r[0] for r in rows][:20],
    }


async def _vm_state(token: str | None = None) -> dict | None:
    """Compute Engine instance state via REST (no extra dependency)."""
    if not (VM_NAME and VM_ZONE and GCP_PROJECT):
        return None
    import google.auth
    import google.auth.transport.requests
    import httpx

    def _token() -> str:
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token

    try:
        access = token or await asyncio.to_thread(_token)
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                f"https://compute.googleapis.com/compute/v1/projects/{GCP_PROJECT}"
                f"/zones/{VM_ZONE}/instances/{VM_NAME}",
                headers={"Authorization": f"Bearer {access}"},
            )
        if r.status_code == 404:
            return {"status": "NOT_FOUND"}
        if r.status_code == 403:
            # The most likely prod misconfiguration: the VM exists but the
            # Cloud Run service account lacks compute.instances.* — say so
            # instead of showing a blank "UNKNOWN".
            return {"status": "FORBIDDEN",
                    "error": "The backend's service account can't read this VM. "
                             "Terraform grants difyVmOperator when with_dify=true; "
                             "re-run ./deploy.sh."}
        if r.status_code != 200:
            return {"status": "UNKNOWN", "error": r.text[:200]}

        data = r.json()
        status_now = data.get("status", "UNKNOWN")
        ip = ""
        for nic in data.get("networkInterfaces") or []:
            for cfg in nic.get("accessConfigs") or []:
                ip = cfg.get("natIP") or ip
        return {
            "status": status_now,
            "ip": ip,
            "machine_type": (data.get("machineType") or "").rsplit("/", 1)[-1],
            # GCE reports these while a start/stop is still settling; the UI
            # keeps polling instead of showing a state that's about to change.
            "transitioning": status_now in (
                "PROVISIONING", "STAGING", "STOPPING", "SUSPENDING", "REPAIRING",
            ),
            "billing": "billed while RUNNING; stopped instances bill only for disk",
        }
    except Exception as exc:
        return {"status": "UNKNOWN", "error": str(exc)[:200]}


async def status(dify, registry) -> dict:
    """Everything the admin panel shows about the engine."""
    base = os.getenv("DIFY_BASE_URL", "")
    m = mode()
    info: dict = {
        "mode": m,
        "configured": bool(dify and dify.enabled),
        "base_url": base,
        "controllable": m in ("docker", "vm"),
        "reachable": False,
        "plugins": [],
        "tools": 0,
        "mcp_servers": 0,
        "agents": 0,
    }

    if dify and dify.enabled:
        # Force a fresh probe so the panel never shows a stale cached value.
        info["reachable"] = await dify.is_up(ttl=0)

    if m == "docker":
        info["containers"] = await _containers()
    elif m == "vm":
        info["vm"] = await _vm_state()

    if info["reachable"]:
        try:
            from providers.dify import TOOL_CATALOG

            r = await dify._console(
                "GET", "/workspaces/current/plugin/list"
            )
            if r.status_code == 200:
                info["plugins"] = [p["plugin_id"] for p in r.json().get("plugins", [])]
            mcp = await dify.list_mcp_servers()
            info["mcp_servers"] = len(mcp)
            info["tools"] = len(TOOL_CATALOG) + sum(len(s["tools"]) for s in mcp)
        except Exception as exc:
            log.warning("engine detail fetch failed: %s", exc)

    try:
        info["agents"] = sum(
            1 for mdl in await registry.list_all() if mdl.get("provider") == "dify"
        )
    except Exception:
        pass
    return info


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
async def _ensure_daemon(docker: str) -> str:
    """
    Bring the Docker daemon up if it isn't. Without this, START fails
    whenever OrbStack/Docker Desktop simply isn't running — the most common
    reason the engine is offline in local dev.
    """
    code, _ = await _run(docker, "info", "--format", "{{.ServerVersion}}", timeout=15)
    if code == 0:
        return ""
    if sys.platform != "darwin":
        return "Docker daemon is not running — start it and try again.\n"

    for app in ("OrbStack", "Docker"):
        if os.path.isdir(f"/Applications/{app}.app"):
            await _run("open", "-a", app, "--background", timeout=30)
            for _ in range(30):
                await asyncio.sleep(2)
                code, _ = await _run(docker, "info", "--format", "{{.ServerVersion}}",
                                     timeout=15)
                if code == 0:
                    return f"Started {app} (Docker daemon).\n"
            return f"{app} did not become ready in time.\n"
    return "No Docker daemon found — install OrbStack or Docker Desktop.\n"


async def control(action: str) -> dict:
    """start | stop | restart. Commands are constants, never request data."""
    if action not in ("start", "stop", "restart"):
        raise ValueError("action must be start, stop or restart")

    m = mode()
    if m == "docker":
        docker = _docker_bin()
        prefix = await _ensure_daemon(docker) if action != "stop" else ""
        args = {
            "start": ["compose", "up", "-d"],
            "stop": ["compose", "down"],
            "restart": ["compose", "restart"],
        }[action]
        code, out = await _run(docker, *args, cwd=COMPOSE_DIR, timeout=600)
        return {"ok": code == 0, "action": action, "mode": m,
                "output": (prefix + out.strip())[-1500:]}

    if m == "vm":
        import google.auth
        import google.auth.transport.requests
        import httpx

        def _token() -> str:
            creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            creds.refresh(google.auth.transport.requests.Request())
            return creds.token

        verb = {"start": "start", "stop": "stop", "restart": "reset"}[action]
        access = await asyncio.to_thread(_token)
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                f"https://compute.googleapis.com/compute/v1/projects/{GCP_PROJECT}"
                f"/zones/{VM_ZONE}/instances/{VM_NAME}/{verb}",
                headers={"Authorization": f"Bearer {access}"},
            )
        return {"ok": r.status_code in (200, 204), "action": action, "mode": m,
                "output": r.text[:1000]}

    return {"ok": False, "action": action, "mode": m,
            "output": "This engine isn't controllable from here. Set DIFY_COMPOSE_DIR "
                      "(local docker) or DIFY_VM_NAME/DIFY_VM_ZONE (Compute Engine)."}
