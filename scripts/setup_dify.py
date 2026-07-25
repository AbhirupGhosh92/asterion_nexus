#!/usr/bin/env python3
"""
Bootstrap a fresh Dify instance so NEXUS agents work out of the box.

Called by deploy.sh after the Dify VM is up. Idempotent — safe to re-run.

  python3 scripts/setup_dify.py <base_url>

Env (set by deploy.sh):
  DIFY_ADMIN_EMAIL, DIFY_ADMIN_PASSWORD   admin account to create/use
  GCP_PROJECT, GCP_REGION                 for the Vertex AI provider
  VERTEX_SA_KEY_B64                       base64 service-account key for Dify→Gemini

Does, via Dify's console API (stdlib only — no pip deps):
  1. First-time setup (admin account)
  2. Install plugins: vertex_ai, duckduckgo, wikipedia, regex
  3. Configure the Vertex AI provider with the SA key
"""

import base64
import json
import os
import sys
import time
import urllib.request
from http.cookiejar import CookieJar

BASE = sys.argv[1].rstrip("/")
EMAIL = os.environ["DIFY_ADMIN_EMAIL"]
PASSWORD = os.environ["DIFY_ADMIN_PASSWORD"]
PROJECT = os.environ.get("GCP_PROJECT", "")
REGION = os.environ.get("GCP_REGION", "us-central1")
SA_KEY_B64 = os.environ.get("VERTEX_SA_KEY_B64", "")

PLUGINS = ["vertex_ai", "duckduckgo", "wikipedia", "regex"]

jar = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def req(method: str, url: str, body: dict | None = None, csrf: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if csrf:
        r.add_header("X-CSRF-Token", csrf)
    try:
        with opener.open(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def wait_for_dify(minutes: int = 15) -> dict:
    print(f"waiting for Dify at {BASE} (VM boot + image pulls can take ~10 min)…")
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        try:
            code, body = req("GET", f"{BASE}/console/api/setup")
            if code == 200:
                return body
        except Exception:
            pass
        time.sleep(15)
    sys.exit("Dify never came up — check the VM's serial console logs.")


def csrf_token() -> str:
    for c in jar:
        if c.name == "csrf_token":
            return c.value
    return ""


def main():
    state = wait_for_dify()
    if state.get("step") == "not_started":
        code, _ = req("POST", f"{BASE}/console/api/setup",
                      {"email": EMAIL, "name": "NEXUS Admin", "password": PASSWORD})
        print(f"setup: {code}")
    else:
        print("setup: already done")

    # Console login is cookie+CSRF; the password field must be base64-encoded.
    code, _ = req("POST", f"{BASE}/console/api/login",
                  {"email": EMAIL,
                   "password": base64.b64encode(PASSWORD.encode()).decode()})
    if code != 200:
        sys.exit(f"Dify login failed ({code}) — wrong DIFY_ADMIN_PASSWORD?")
    csrf = csrf_token()
    print("login: ok")

    # Latest marketplace identifiers, then install.
    idents = []
    for name in PLUGINS:
        with urllib.request.urlopen(
            f"https://marketplace.dify.ai/api/v1/plugins/langgenius/{name}", timeout=30
        ) as r:
            idents.append(json.load(r)["data"]["plugin"]["latest_package_identifier"])
    code, _ = req("POST",
                  f"{BASE}/console/api/workspaces/current/plugin/install/marketplace",
                  {"plugin_unique_identifiers": idents}, csrf)
    print(f"plugin install requested: {code}")

    for _ in range(40):
        code, body = req("GET", f"{BASE}/console/api/workspaces/current/plugin/list",
                         csrf=csrf)
        installed = {p["plugin_id"].split("/")[-1] for p in body.get("plugins", [])}
        if set(PLUGINS) <= installed:
            break
        time.sleep(5)
    print(f"plugins installed: {sorted(installed)}")

    if SA_KEY_B64:
        code, body = req(
            "POST",
            f"{BASE}/console/api/workspaces/current/model-providers/"
            "langgenius/vertex_ai/vertex_ai/credentials",
            {"name": "nexus-vertex",
             "credentials": {"vertex_project_id": PROJECT,
                             "vertex_location": REGION,
                             "vertex_service_account_key": SA_KEY_B64}},
            csrf,
        )
        # 200 = created; 400 with "exist" = already configured from a prior run
        print(f"vertex provider: {code} {str(body)[:80]}")
    print("Dify bootstrap complete.")


if __name__ == "__main__":
    main()
