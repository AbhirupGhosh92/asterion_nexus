# viewmodels/ — state and logic (hooks)

All application state lives here. Hooks return data plus actions; they
contain no JSX.

| Hook | Owns |
|---|---|
| `useAuth.ts` | Firebase sign-in state → `loading` / `out` / `in`. Skips the gate entirely when Firebase isn't configured (offline dev). |
| `useChat.ts` | The live conversation: message list, streaming, model choice, attachments/upload, quota-aware error text, scroll pinning, and `retry`. The busiest file in the UI. |
| `useConversations.ts` | The topics sidebar: list, open, delete, active id. |

## Scroll behaviour (useChat)

Auto-scroll only re-pins when the user is already within 80px of the bottom,
so scrolling up to read isn't yanked back mid-stream; `jump to latest`
appears otherwise. Scrolling is **instant, not smooth** — smooth animations
queue up and visibly lag behind streamed tokens.

## Adding a hook

Take dependencies as arguments (like `useChat` takes the conversation
callbacks) rather than importing another hook's state, so views stay the only
place layers are wired together.

## send vs retry (useChat)

Both call one private `runTurn(history, attachments)`, so they cannot drift.
`retry(messageId)` slices the history to *and including* that user message
and re-runs it — everything after is dropped, so the reply is **regenerated
rather than appended**. Original attachments are reused; their uploads still
exist server-side, so only the ids are re-sent.
