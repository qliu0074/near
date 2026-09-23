# Frontend architecture and PWA

`app/page.tsx` renders the application entry point. UI, data access, synchronization, and transport are maintained separately.

| Location | Responsibility |
| --- | --- |
| `components/near-app.tsx` | Session recovery, offline notices, login/workspace switching |
| `components/workspace.tsx` | Selected companion, creation entry, usage panel, shared workspace context |
| `components/login-form.tsx`, `sidebar.tsx`, `create-companion.tsx` | Login, account actions, companion creation |
| `components/companion-panel.tsx`, `usage-panel.tsx` | Profiles, memories, archives, usage, local loading/retry states |
| `components/chat-panel.tsx`, `message-list.tsx` | Composer, topics, streamed replies, pagination, chat scrolling |
| `hooks/use-session.ts`, `use-actions.ts` | Session boundaries, action locking, error feedback |
| `hooks/use-resource.ts`, `use-history.ts` | Reusable read states, stale-response cancellation, pagination depth |
| `hooks/use-chat.ts`, `use-live-sync.ts`, `use-network.ts` | Request IDs, SSE lifecycle, connectivity |
| `lib/api.ts`, `query-cache.ts`, `types.ts` | HTTP/SSE parsing, in-memory reads, shared types |
| `components/pwa-controls.tsx`, `app/manifest.ts`, `public/sw.js` | Installation, manifest, public static cache, offline fallback |

## Language

The application interface is English, including validation feedback, confirmations, accessibility labels, timestamps, installation guidance, and offline screens. Page and manifest language metadata are `en`.

Chat remains multilingual: text is preserved as Unicode, the real model is instructed to follow the latest user message or explicit language preference, and message content and the composer use automatic text direction for right-to-left languages. Memories and archives preserve the original message text. Existing user-authored names, profiles, and messages are not rewritten.

Generated profiles, suggested-topic buttons, and sign-in emails use English. Mock mode has a fixed English demonstration reply; real multilingual generation requires a configured model.

## Cache and consistency

Read responses live only in the current page's JavaScript memory, with a 15-second freshness window and a 100-entry least-recently-used limit. Concurrent reads for the same key share one request. The next read after expiry revalidates. Switching components can reuse fresh data; read failures preserve existing content and expose a retry button.

Completed or failed writes, cross-device events, sync reconnection, and returning to a visible tab invalidate the cache. Mounted views re-read their data, including open archives and usage panels. History refreshes retain the loaded page count; loading older messages does not force the chat to the bottom.

Invalidation cancels pending reads and advances a generation counter. Even a loader that ignores cancellation cannot restore an obsolete response. Sign-out or session revocation clears the cache and unmounts the workspace, removing drafts and private view state. All API fetches use `cache: no-store`; account exports bypass the read cache.

Writes and paid calls are never automatically retried. A manual resend of the same draft and mode retains its pending request ID. A stream without a completion event reports an error. Offline users can edit the draft but cannot send it; reconnecting refreshes reads only. Drafts are not stored in localStorage or IndexedDB and are lost when the page is closed or reloaded.

## PWA

- Includes a manifest, 192/512 PNG icons, a maskable icon, an Apple touch icon, an install button when supported, and browser-menu instructions otherwise.
- Registers the service worker only in production builds, over HTTPS or localhost.
- Cache Storage holds only the public offline page, manifest, icons, and `/_next/static/` build assets, with at most 60 additional static assets.
- `/v1/**`, including SSE and account export, always uses the network. Normal page HTML, RSC responses, and private business data are never persisted by the worker.
- An offline page load displays the public `offline.html`, not conversation history. There is no offline message queue.
- Updates do not force-refresh an active conversation. Close all Near windows and reopen to activate a waiting update. Bump the `CACHE` version in `public/sw.js` when changing offline pages or fixed-path icons. Activation removes only this application's obsolete caches.
- Local standalone startup and the Docker image both copy `public/` so installation and offline resources are served.

## Verification

```powershell
# In web:
npm test
npm run typecheck
npm run build
# From the project root, using installed Edge:
$env:NEAR_BROWSER_CHANNEL = 'msedge'
.\.venv\Scripts\python.exe scripts/run-local.py --browser
```

Without Edge, install Playwright Chromium and omit `NEAR_BROWSER_CHANNEL`.

`web/tests/` covers deduplication, expiry/LRU, invalidation and account isolation, no automatic retries, fragmented UTF-8/SSE, and incomplete streams.
`tests/browser-smoke.cjs` checks core UI actions, retry after read failure, cross-device sync, pagination, English interface labels, multilingual text preservation, and RTL input. It disables service workers to allow precise network fixtures.
`tests/pwa-smoke.cjs` uses a real worker to check installation resources, public-cache boundaries, old-cache cleanup, offline drafts/reloads, blocked offline account export, reconnection, and account switching.
Automated browser checks do not replace physical-device installation acceptance; iOS home-screen installation and OS install dialogs still require manual checks.

The icon source is `public/icons/icon.svg`. After editing it, run `npm run icons` with a Playwright browser installed to regenerate the PNG files.
