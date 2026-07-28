# frontend/src — React UI (MVVM)

**Read this before opening files; each layer has its own CLAUDE.md.**

```
models/       Model      Types + the API client. Data shapes and I/O.
viewmodels/   ViewModel  Hooks holding state and logic. No JSX.
views/        View       Components. Render props, call callbacks, no fetching.
App.tsx       —          Root: picks a screen from auth state.
main.tsx      —          Mount point + stylesheet imports.
theme.css     —          Design tokens (colors, fonts, glows). Re-theme here.
app.css       —          Manifest: @imports styles/ in cascade order.
styles/       —          One stylesheet per feature area.
```

## Styles

`app.css` holds no rules — it imports `styles/*.css` in cascade order
(structure → chrome → content → features → `responsive.css` last, since it
overrides everything above it).

One file per area — `chat.css`, `composer.css`, `code.css`, `gallery.css`,
`admin.css` and so on. **Adding a feature means a new file plus one import
line**, not appending to a shared tail: two branches that both appended to
the end of the old single `app.css` produced a merge conflict whose
resolution silently deleted an entire feature's styling (PR #19). Separate
files make those conflicts impossible.

## The rule that keeps this clean

**Views never fetch and never hold business state.** If a component needs
data, a hook in `viewmodels/` provides it; if it needs to act, it calls a
callback the hook exposed. A `fetch(` or `adminApi.` call inside `views/`
(outside `views/admin/`) means the logic is in the wrong layer.

`views/admin/*` is the pragmatic exception: each tab is a small, self-
contained CRUD screen that calls `adminApi` directly rather than each having
a near-identical hook.

## Where things live

| Task | File |
|---|---|
| Add a backend call | `models/api.ts` (+ its type in `models/types.ts`) |
| Change chat behaviour (send, stream, scroll, attachments) | `viewmodels/useChat.ts` |
| Change how a message looks | `views/MessageBubble.tsx` |
| Add an admin screen | `views/admin/` + a tab entry in `AdminPanel.tsx` |
| Re-theme | `theme.css` variables |
