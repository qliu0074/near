# Near Companion · v0.2

An independent full-stack AI companion application with explicit memory, hybrid retrieval and auditable usage controls.

## Quick start

### Windows / Local development without Docker

Requires Python 3.10+ and Node.js 20.9+ (Node 22 recommended). Run from the project root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r api/requirements.txt
cd web
npm ci
cd ..
.\.venv\Scripts\python.exe scripts/run-local.py --build
```

If `py` cannot find Python, use the full path to your installed `python.exe` for the first command.
Open http://localhost:3000. Sign-in codes appear on the login page; demo chat needs no API key.
The launcher migrates `.local/near.db` and starts the API, cleanup worker, and built frontend. Press Ctrl+C to stop them together.
Omit `--build` on subsequent runs unless you have changed the frontend. Normal startup reads the AI provider from `.env`; `--provider mock` explicitly selects demo mode. Smoke/browser tests always use mock. The launcher does not overwrite `.env`.
It does not start Elasticsearch or provide real vector retrieval. Use Compose below for PostgreSQL, SMTP, and retrieval services.

```powershell
# Run HTTP checks in a temporary database, then stop services and clean up.
.\.venv\Scripts\python.exe scripts/run-local.py --smoke
# Run desktop, mobile-layout, cross-device, and PWA checks using installed Edge.
$env:NEAR_BROWSER_CHANNEL = 'msedge'
.\.venv\Scripts\python.exe scripts/run-local.py --browser
```

Without Edge, run `npx playwright install chromium` in `web` and leave `NEAR_BROWSER_CHANNEL` unset.
On Linux/macOS use the same launcher with `.venv/bin/python`.

### Real chat with Alibaba Cloud Model Studio (Singapore)

Set these values in the project-root `.env` file. Keep the API key private and use a key created in the Singapore region:

```dotenv
AI_PROVIDER=qwen
QWEN_API_KEY=
QWEN_BASE_URL=https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1
QWEN_CHAT_MODEL=qwen-plus
```

Replace `{WorkspaceId}` with your actual workspace ID and fill in `QWEN_API_KEY`. The endpoint format follows the [official Alibaba Cloud documentation](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope).

```powershell
.\.venv\Scripts\python.exe scripts/run-local.py --provider qwen --check-config
.\.venv\Scripts\python.exe scripts/run-local.py --provider qwen
```

Stop an already running local server with Ctrl+C first. Configuration checks do not call the model or validate the key remotely. Real chat, profile generation, and topic suggestions use your model quota. Local sign-in still uses visible development codes, and local mode does not run Elasticsearch.

### Docker Compose

```bash
cp .env.example .env
# Configure server-side Qwen variables privately, or keep AI_PROVIDER=mock.
docker compose up --build
```

Open http://localhost:3000. Compose runs database migrations and initializes the search mapping before starting the API.

The source package excludes private credentials, local databases and dependencies. An existing private configuration should not be overwritten with the example.

For local verification without Docker:

```bash
python3 -m venv .venv
.venv/bin/pip install -r api/requirements.txt
cd api
../.venv/bin/python -m alembic upgrade head
AI_PROVIDER=mock EMAIL_MODE=development ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
# In another terminal, from the repository root:
cd web
npm ci
npm run dev
```

The standalone fallback uses SQLite for development. PostgreSQL is the deployment database; SQLite tests do not prove PostgreSQL concurrency behavior.

## Architecture

The interface, emails, installation flow, generated profiles, and topic suggestions use English. Chat accepts Unicode text and instructs the real model to follow the user's language or explicit language preference. Existing user content is preserved. Mock mode uses a fixed English demo reply, not a multilingual model.

The frontend uses feature components and hooks, deduplicated reads, a 15-second in-memory cache, session invalidation, local retry controls, and PWA installation/offline support. See [Frontend architecture](web/ARCHITECTURE.md).

 | Layer | Technology and responsibility |
| --- | --- |
 | Web | Next.js, React, strict TypeScript; same-origin API proxy, streamed chat and EventSource sync |
 | API | FastAPI, Pydantic, SQLAlchemy; authentication, ownership, lifecycle, admission and accounting |
 | Business data | PostgreSQL; users, hashed sessions, companions, messages, memories, budgets and durable events |
 | Retrieval | Elasticsearch dense_vector + cosine kNN, CJK BM25, application-side RRF |
 | Background work | Celery + Redis; leased database outbox, vector ingestion, retention |
 | Models | Qwen-compatible chat and embedding endpoints; profile review/generation and optional topics |
 | Delivery | Alembic migrations, Dockerfiles, Compose, pytest, TypeScript checks and HTTP smoke tests |

The project uses ordinary framework dependencies, without Supabase, Cloudflare application hosting, pgvector or an agent framework.

## Implemented behavior

- Email-code registration/login, single-use codes, attempt limits, HMAC code hashes, hashed sessions, HttpOnly cookies, Origin/CSRF checks, current-device and all-device logout.
- Real SMTP adapter and explicitly marked local test mailbox. Real email requires SMTP settings; development mode displays the code and sends no email.
- Human/animal companions, fictional identity declaration, Qwen-reviewed original backgrounds, editable versioned profiles, optional three-topic suggestions.
- Streaming replies, paged history, explicit memory consent/deletion, private archive/restore, account export/deletion and companion deletion.
- Real-time device notifications with persisted cursors, reconnect and session revocation. Finalized messages synchronize; intermediate generated tokens are shown only on the initiating device.
- Normal mode retrieves memory and retains up to 12 recent messages; fast mode skips retrieval and retains up to 4 messages.

Portrait generation remains intentionally unconfigured: the button is disabled, the endpoint returns 503 and no quota is consumed. The schema reserves an initial-plus-three-revisions limit, but actual image generation, storage and quota settlement are not enabled.

## Retrieval and privacy

1. Explicitly saved source messages become memory records; a transaction writes both the record and an outbox event.
2. A worker creates a metered embedding and indexes its vector, text, owner, companion, model and version in Elasticsearch.
3. Normal chat embeds the current query, retrieves BM25 and cosine-kNN candidates with matching ownership/deletion filters, then fuses rankings using RRF.
4. The API rechecks candidate ownership and deletion in PostgreSQL and places at most five short memory excerpts into the Qwen prompt.

Vector search runs only in Elasticsearch. PostgreSQL temporarily caches operation results, including embedding arrays, for paid-call idempotency; it does not perform vector search and needs no vector extension.

If only kNN fails, retrieval falls back to BM25. If Elasticsearch is unavailable, chat continues without retrieved memory. An uncertain embedding call retains its reservation and stops the request instead of silently retrying.

Unarchived messages expire after three days; archived messages persist but are excluded from prompts. Explicitly saved memories survive automatic source expiry. Explicit deletion or archiving removes derived memory, with ES cleanup delivered asynchronously. Account deletion removes application data while preserving aggregate site usage and content-free deletion tombstones until cleanup.

Completed provider-result caches are scrubbed after three days. Backup expiry and external-provider retention must be configured separately by the deployment operator.

## Usage controls

All paid paths—chat, profile generation, topic suggestions and embeddings—share atomic per-user and site-level reservations. Each user may have only one paid operation in flight. Chat is limited to ten admitted calls per minute.

The input estimate uses serialized UTF-8 bytes plus a margin, not an exact tokenizer. Reserve input plus maximum output, then settle the provider's actual total_tokens. Retrieved text is already part of input and is not counted twice. Actual usage above an estimate is still recorded.

TOKEN_LIMIT and SITE_TOKEN_LIMIT are lifetime aggregate token admission caps, not currency limits or the provider's remaining free quota. Chat and embeddings may have different prices and free allowances. Configure billing alerts and hard stops in the provider console separately.

Timeouts and incomplete streams retain reservations. Never automatically refund or retry an uncertain paid request. After checking provider billing and stopping the affected API/worker processes, an operator can reconcile a request:

```bash
cd api
../.venv/bin/python -m app.admin OPERATION_ID --actual-tokens 123 --evidence BILLING_REFERENCE --workers-stopped
```

This creates a reconciliation record, releases the reservation and keeps the original request non-replayable. It is a local operator command, not a public administrative API.

## Deployment notes

Compose is an isolated local-development configuration, including disposable database credentials and an unauthenticated internal Elasticsearch instance. Production requires HTTPS, PostgreSQL migrations, a private AUTH_SECRET of at least 32 characters, SMTP with TLS and authenticated Elasticsearch; startup validates these prerequisites.

SSE must remain unbuffered and uncompressed through the reverse proxy. The Next proxy disables compression, and the API sends no-transform and X-Accel-Buffering headers. The synchronization service reads the durable event table roughly once per second per connection; Redis pub/sub fan-out is not implemented.

Authentication rate limits use the observed network peer. Shared proxies can therefore share a bucket; production ingress must normalize trusted client addresses and apply perimeter limits. Never trust arbitrary forwarded headers. Horizontal-load testing, observability, backup restore and independent security review remain deployment gates.

For an existing v0.1 database, back up first and verify its schema matches migration 0001 before stamping that baseline and upgrading. Never stamp an unknown schema. Fresh installations run `alembic upgrade head` directly.

## Verification

```bash
cd api
../.venv/bin/python -m pytest -q
cd ../web
npm run typecheck
npm run build
cd ..
bash tests/run-http-smoke.sh
# With the services running and Playwright/Chromium installed:
node tests/browser-smoke.cjs
```

See VERIFICATION.md for executed checks and unverified external dependencies. The identity review is a model-based check, not a guaranteed identity detector. Mock mode bypasses semantic profile review and must not be deployed publicly.

## References

- [Qwen embedding API](https://www.alibabacloud.com/help/en/model-studio/embedding)
- [Qwen OpenAI compatibility](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope)
- [Elasticsearch dense_vector](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/dense-vector)


## Failure recovery

Provider connection establishment has at most two retries; read/write timeouts and interrupted generations are never automatically replayed. Authentication/access/model-not-found/rate-limit HTTP rejections (401/403/404/429) and failures before connection establishment release the application's reservation. Other provider failures remain uncertain, including 400 inspection errors and 5xx responses. Classification follows the [Model Studio error reference](https://www.alibabacloud.com/help/en/model-studio/error-code); application token reservations are not a provider billing statement.

Failed chat attempts remain recorded. The UI preserves the draft and uses a new request ID on a manual retry after a confirmed rejection. Failed metered operations can retry the same operation key; completed results remain cached. Uncertain operations require the existing operator reconciliation command and include a reference ID in errors. Historical uncertain records are not automatically refunded.

Search outages continue without retrieved memory and display an English warning during streamed chat. Keyword fallback remains available when only vector search fails. An uncertain paid embedding still stops the request.

Sanitized warning logs contain an event name, request/job reference and exception class, never exception text, provider bodies, credentials or chat content. Mail failures also return a reference. Memory synchronization retries with exponential backoff, logs attention on attempt five, and pauses after ten failed attempts without discarding the job. After repairing the service (and reconciling uncertain usage if needed), run `python -m app.worker retry-outbox --job-id JOB_ID` from `api`. This resumes only a paused job and preserves its original payload, including deleted-account tombstones. External log collection and alert delivery must still be configured by the operator.
