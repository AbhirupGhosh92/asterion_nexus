# models/ — data and I/O

| File | Contains |
|---|---|
| `types.ts` | Every shared interface: `ChatMessage`, `AgentStep`, `Profile`, `QuotaStatus`, `ConversationMeta`, `UploadMeta`, the admin types, plus UI-only shapes (`UiMessage`, `Attachment`). Pure data, no behaviour. |
| `api.ts` | The single place that talks to the backend. Attaches the Firebase ID token to every request, parses the SSE stream, and exposes `adminApi` for the control plane. Re-exports all types, so `from "../models/api"` works for both. |

## Notes

- `authedFetch` refreshes the ID token automatically; never call `fetch`
  directly from a component.
- Requests are same-origin `/api/**` in dev *and* prod — the Vite proxy
  mirrors the Firebase Hosting rewrite, so no environment branching.
- Without `VITE_FIREBASE_API_KEY`, Firebase is skipped entirely and the app
  runs unauthenticated against a backend started with `AUTH_DISABLED=1`.
- `chatStream` decodes typed SSE frames: `meta`, `token`, `step`, `title`,
  `done`. Add a new frame type here and in the backend together.
