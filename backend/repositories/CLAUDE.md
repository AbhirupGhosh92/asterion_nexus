# repositories/ — Model layer (data access)

Persistence only. No guardrails, no LLM calls, no HTTP. Every method takes a
uid and scopes by it — that scoping *is* the access-control boundary, since
clients never reach Firestore or Storage directly.

| File | Stores |
|---|---|
| `chat_repo.py` | Conversations and messages: `users/{uid}/conversations/{cid}/messages`. Also persists agent decision traces on assistant messages. |
| `media_repo.py` | Uploads and generated images in Cloud Storage under `uploads/{uid}/…`, with metadata in Firestore. 25 MB cap, image/audio/video only. |
| `memory_repo.py` | Vertex AI Memory Bank — long-term per-user facts, scoped `{"user_id": uid}`. Degrades to a no-op without GCP so local dev works offline. |

## Gotcha

Firestore's `DocumentSnapshot.get(field)` **raises** on a missing field — it
is not `dict.get`. Convert with `doc.to_dict()` first before reading optional
fields, or old documents blow up. This has bitten this codebase before.
