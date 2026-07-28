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
| `Markdown.tsx` | Assistant markdown → HTML. Raw HTML deliberately **not** enabled; links forced to `target=_blank rel=noopener`. Fenced blocks are replaced at the `pre` level. |
| `CodeBlock.tsx` | A code panel: language label, copy button, syntax-highlighted body. Runs lowlight itself. |
| `languages.ts` | The highlighting language set — deliberately curated, see below. |
| `AskCard.tsx` | Parses ```ask blocks into clickable option buttons. |
| `AgentGallery.tsx` | The homepage roster of specialist agents. Locked cards route to the upgrade dialog; unlocked ones set the composer's model. |
| `UpgradeDialog.tsx` | The Pro placeholder: plan comparison with a deliberately inert CTA — there's no billing integration yet. |
| `admin/` | The admin panel — see `admin/CLAUDE.md`. |

## Gotchas

- `MessageBubble` renders markdown only for assistant messages; user text is
  shown verbatim, and guardrail notices stay plain to keep their alert style.
- A half-streamed ```ask block is hidden behind "preparing options…" rather
  than flashing raw JSON.
- `.md` opts out of the bubble's `white-space: pre-wrap`, or every markdown
  paragraph double-spaces.

- **Code blocks are intercepted at `pre`, not `code`.** react-markdown no
  longer passes an `inline` flag, so "is my parent a `pre`?" is the only
  reliable block-vs-inline test. Replacing `pre` means the inner `code`
  component never renders for fenced blocks.
- Highlighting runs inside `CodeBlock` via lowlight rather than through
  `rehype-highlight`, which statically imports highlight.js's ~37-language
  `common` set (+53 kB gzip on the critical path — every message renders
  through `Markdown`) with no option to opt out. Add a language in
  `languages.ts`; unregistered ones render as plain text, never throw.
- The `hljs-*` colours live in `app.css` on the theme tokens, so no hljs
  stylesheet ships. `.md pre` must stay unstyled: it would match
  `.code-body` and beat it on specificity.
- The gallery only renders on an empty conversation (the homepage), and a
  locked card is a *display* state — the server enforces the same rule, so
  the dialog is UX, not security.
- Copy/retry appear on **user** messages only; retry is hidden while a turn is
  streaming. Copy falls back to a hidden textarea when the Clipboard API is
  unavailable (it needs a secure context).
- Image download uses the object URL already fetched for display, so it costs
  no extra request. Hover-only on pointer devices, always visible under
  `@media (hover: none)` so touch users can reach both.
