# core/ — configuration and identity

Cross-cutting concerns every layer depends on. Nothing here may import from
`routers/`, `services/` or `repositories/`.

| File | Contains |
|---|---|
| `config.py` | Every env var the platform reads, in one place — plus `REFUSAL_TEXT` and `ASK_PROTOCOL`. Add new settings here rather than scattering `os.getenv`. |
| `auth.py` | Firebase ID-token verification, `AuthedUser`, tier ranking, `require_tier(...)`, and `require_admin` (the `ADMIN_EMAILS` allowlist). |

## Identity rules

- `AuthedUser.uid` is the **only** acceptable source of a scoping uid.
- `is_admin` is email-allowlist based (`ADMIN_EMAILS`), deliberately separate
  from `tier`: tiers gate features, the allowlist gates the control plane.
- `AUTH_DISABLED=1` bypasses verification for offline dev only. Never set it
  in a deployed environment.
