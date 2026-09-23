# Verification record

## Failure recovery (2026-09-22)

- Backend: 54 tests passed; after adding the paused-job recovery command, all 15 failure-specific tests passed again. Coverage includes rejected requests releasing reservations once, recovery on subsequent requests, metered job retry, uncertain partial streams, sanitized logs, search degradation, and bounded outbox retries/resumption.
- Frontend: 9 tests passed, including safe-retry stream errors and memory warnings. TypeScript checks, production build, and the built-web HTTP smoke suite passed.
- Tests use controlled failures; real provider outages, production PostgreSQL concurrency, and external alert delivery were not exercised.


## English interface (2026-09-20)

- Backend: **35 tests passed**, including Chinese, Spanish, Japanese, and Arabic message preservation, the chat language instruction, English email content, and English demo suggestions. Two upstream deprecation warnings remain.
- Frontend: **8 tests passed**; TypeScript checks passed.
- Production build and HTTP/browser/PWA suites passed. Browser checks verify the English interface and language metadata, mixed Chinese/Spanish/Japanese/Arabic messages, Arabic input and message direction, mobile width, and removal of the legacy Chinese offline cache.
- All application-owned UI strings, accessibility labels, dialogs, errors, page/manifest language metadata, installation text, and the offline page use English.
- The offline cache version is advanced to retire the previous Chinese offline page.
- Real model language quality is not verified by controlled-provider tests. Mock mode still returns a fixed English demo reply.

## Frontend architecture and PWA (2026-09-19)

- Production build, HTTP smoke checks, desktop/mobile layouts, cross-device synchronization, history pagination, manual read retries, and all-device sign-out passed.
- Independent browser checks with a real service worker passed manifest/icon delivery, public-cache restrictions, offline draft retention, disabled offline sends, no automatic resends, offline reload, blocked offline account export, reconnection, and account isolation.
- UI fixture tests disable service workers and consequently show the offline-feature fallback notice in screenshots. The independent PWA suite tests real worker behavior.
- Physical iOS installation and operating-system installation dialogs have not been manually verified. Remote CI has not been run from this environment.
- See [Frontend architecture](web/ARCHITECTURE.md) for caching and update boundaries.

## Earlier project verification

The table below is the original project record. Its credentials, network state, and existing-database checks refer to an earlier environment, not this machine. Current local development uses mock AI, development email codes, and SQLite. Real Qwen, SMTP, PostgreSQL, and Elasticsearch are not configured or verified here.

 | Check | Result |
| --- | --- |
 | API and migrations | 31 tests passed on temporary SQLite databases with controlled provider fixtures |
 | TypeScript | Passed during production build; no explicit any types added |
 | Web build | Next.js standalone build passed |
 | Live HTTP | Built frontend proxy + running FastAPI passed OTP, chat SSE, live second-device notifications, memory, archive/export, suggestions, usage, disabled portraits and logout |
 | Existing database | Local v0.1 SQLite database backed up, compared to baseline and migrated; Alembic check passed |
 | Hybrid retrieval | Vector ingestion, metering/cache, query embedding, owner filters, RRF and deletion propagation covered using fixtures |
 | Real Qwen | Server-side credentials configured; authenticated connectivity attempt failed with a network URLError, so credential validity and live model compatibility are unverified |
 | Email | SMTP path tested with a fake SMTP server; no real mailbox credentials configured |
 | Portrait | Intentionally disabled and empty; tests confirm 503 with no quota change |
 | Browser E2E | Script updated but not executed successfully; Chromium unavailable and previous download attempts timed out |
 | Docker/PostgreSQL/ES | Configuration supplied, not run in this environment; Docker unavailable |

The initial cross-device HTTP check exposed proxy compression buffering. Disabling compression and adding no-transform headers resolved it; the updated live test passed.

The suite covers authentication/CSRF, ownership isolation, idempotency, site budgets, uncertain billing reconciliation, disabled portraits, deletion and archive privacy, optimistic profile versions, migration data preservation and equal-timestamp pagination.

Upstream Starlette/HTTPX deprecation warnings remain. No public deployment, browser visual acceptance, production load test or independent security audit has been completed.

Do not describe fixture-based tests as real-service verification or an unconfigured portrait endpoint as a working image-generation integration.
