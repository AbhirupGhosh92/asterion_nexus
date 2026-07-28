# views/ — presentational components

Render props, call callbacks. No data fetching, no business state (local UI
state like "is this panel open" is fine).

| File | Renders |
|---|---|
| `AuthGate.tsx` | Sign-in screen. Owns only its own busy/error state. |
| `Workspace.tsx` | The signed-in shell: wires `useChat` + `useConversations` to the sidebar, chat panel and composer. The one place layers meet. |
| `Sidebar.tsx` | Conversation topics list. Fully driven by props. |
| `MessageBubble.tsx` | One message: attachments, decision trace, markdown/plain content, generated images, the ask-card, plus copy/retry actions (user messages) and image download. |
| `Composer.tsx` | Model picker, attachment chips, input and TRANSMIT. |
| `Markdown.tsx` | Assistant markdown → HTML. Raw HTML deliberately **not** enabled; links forced to `target=_blank rel=noopener`. |
| `AskCard.tsx` | Parses ```ask blocks into clickable option buttons. |
| `admin/` | The admin panel — see `admin/CLAUDE.md`. |

## Gotchas

- `MessageBubble` renders markdown only for assistant messages; user text is
  shown verbatim, and guardrail notices stay plain to keep their alert style.
- A half-streamed ```ask block is hidden behind "preparing options…" rather
  than flashing raw JSON.
- `.md` opts out of the bubble's `white-space: pre-wrap`, or every markdown
  paragraph double-spaces.

- Copy/retry appear on **user** messages only; retry is hidden while a turn is
  streaming. Copy falls back to a hidden textarea when the Clipboard API is
  unavailable (it needs a secure context).
- Image download uses the object URL already fetched for display, so it costs
  no extra request. Hover-only on pointer devices, always visible under
  `@media (hover: none)` so touch users can reach both.
