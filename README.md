# Video Translate

Private workspace API for the approved Video Translate SaaS. This increment provides accounts,
sessions, projects, source uploads and private downloads. Remote inference is provider-neutral;
Hugging Face is the primary ecosystem for subsequent provider adapters. There are no local AI
models, model weights, torch, transformers, ASR or TTS runtimes in this package.

## Run locally

Python 3.12 and [uv](https://docs.astral.sh/uv/) are required. Tests also require FFmpeg on PATH;
the test fixture generates an actual tiny MP4 rather than labelling invented bytes as decoded media.

```sh
uv sync --python 3.12 --extra dev
cp .env.example .env
mkdir -p var
uv run uvicorn videotranslate.app:create_app --factory --host 127.0.0.1 --port 8000
```

The API is under `/api`; OpenAPI is available at `/docs`. Development/test may explicitly use
SQLite and local filesystem storage and the factory creates missing development tables. No
production database or storage is provisioned by these commands.

## Production configuration

Set `VT_ENVIRONMENT=production`, `VT_DATABASE_URL` to a PostgreSQL `postgresql+psycopg://`
connection, `VT_STORAGE_BACKEND=s3`, a random `VT_SERVER_SECRET` of at least 32 characters,
`VT_PUBLIC_ORIGIN` to the public HTTPS origin, and `VT_DEBUG=false`. Fill every S3 field from
`.env.example`: HTTPS endpoint, bucket, region, access key and secret key. Production refuses
SQLite, filesystem storage, missing S3 configuration, development secrets, private/loopback
origins and debug mode. Credentials are server-side only; never put provider tokens in project settings.

Provision a private S3-compatible bucket with public access blocked, no anonymous bucket policy,
and a service credential restricted to the application's object prefix. The adapter never requests
public ACLs or returns object keys. Bucket policy and real cloud connectivity must be verified
against the deployed account; the isolated S3 contract fake is not evidence of either.

Apply schema migrations explicitly before starting production; the factory never migrates production:

```sh
uv run alembic upgrade head
uv run uvicorn videotranslate.app:create_app --factory --host 0.0.0.0 --port 8000 --no-proxy-headers
```

Terminate HTTPS at a trusted proxy and keep the API private behind it. Throttling uses the ASGI
network peer, never an arbitrary forwarded-IP header. `--no-proxy-headers` preserves this behavior;
if many clients share one reverse proxy, they share its login limit until a trusted proxy policy is
implemented. Do not enable arbitrary proxy header trust. Avoid request body/header or exception
dumps in gateway, application or tracing logs. Use sanitized diagnostics instead. Session/hash
stability requires the same server secret across workers and restarts; rotate it to revoke all sessions.

## API behavior

Register with `POST /api/auth/register` and JSON `email`, `password` (10–128 characters), `name`.
Login accepts email/password. Register/login set an opaque HttpOnly `vt_session` cookie and return
`{user, workspace, csrf_token}`. Session and CSRF hashes alone are stored. The paired `vt_csrf`
cookie is readable for browser CSRF use; keep the JSON token in memory. Reload via
`GET /api/auth/me`; it verifies the cookie before returning the same token. Cookies are SameSite=Lax
and Secure in production. Send `X-CSRF-Token` on every mutation after register/login, including logout.

Projects support list/create/detail/patch/soft-delete. PATCH accepts the current `revision` for explicit
optimistic concurrency; stale revisions return 409 `REVISION_CONFLICT`. Every update also uses an
atomic revision predicate internally. Fields are flat and follow the master contract. Current typed
settings accept `auto_advance`; defaults remain `{}`. Unknown settings are rejected so secrets cannot
be smuggled into frontend-visible project JSON. Language identifiers preserve complete codes and
regional forms; this foundation validates shape without claiming a provider supports that language.

Both collection endpoints, `GET /api/projects` and `GET /api/projects/{id}/assets`, accept
`limit` (default 50, minimum 1, maximum 200) and `offset` (default 0, minimum 0). Their `{items,total}`
envelope keeps `total` equal to the entire owned, active filtered collection, independent of the
requested page. Items use stable `created_at DESC, id ASC` ordering. Invalid bounds return 422;
foreign or deleted project asset collections remain 404.

Upload one multipart `file` to `POST /api/projects/{id}/source`; the response is `{project, asset}`.
Allowed extension/MIME pairs are MP4/M4V, MOV, WebM, MKV and AVI. Both declarations are checked;
media decoding and analysis belong to the next worker increment. Upload sets status `uploaded`,
stores SHA-256 and byte size, and increments the project revision. The default limit is 512 MiB,
configurable via `VT_UPLOAD_MAX_BYTES`. Multipart body spooling is bounded before parsing with a
64 KiB header allowance, then exact file size/hash are read in chunks. Files, private object keys,
metadata and revisions are cleaned up/rolled back on handled failures; existing sources survive
failed replacements. A process crash between object storage and database commit still needs future
orphan reconciliation, and a failed remote delete must be repaired operationally.

`GET /api/projects/{id}/assets` returns `{items,total}`. `GET /api/assets/{id}/content` authenticates
every request, serves safe attachment headers, and supports one byte range, including suffix/open
ranges (206). Invalid or multiple ranges return 416. Unknown/foreign IDs and assets belonging to
soft-deleted projects return 404. Original cookies are never forwarded to source URLs; the API accepts
uploaded files, not remote URL fetches.

Errors use `{error:{code,message,retryable,details}}`; validation details contain field locations and
codes only, never submitted values. Responses are private/non-cacheable; unexpected exceptions are
contained before ASGI server traceback logging. Public responses omit passwords, hashes, session
tokens, storage paths/keys and credentials.

## Verify

```sh
uv run pytest -q
uv run python -m compileall -q src
uv run ruff check src tests alembic
uv run pip-audit --skip-editable --progress-spinner off
```

Tests use fresh real SQLite databases and real files. They cover identity/session/CSRF, persistent
login limits, workspace isolation, atomic revisions, real MP4 upload hash/bytes/ranges, failure cleanup,
production refusals, private S3 call parameters and a clean Alembic upgrade/downgrade/schema parity.
The production cookie/factory unit test injects SQLite/local storage only to inspect that factory's
behavior; it is not a live PostgreSQL or S3 test. Cloud deployment and real inference remain separate
acceptance stages. See [engineering sources](docs/engineering/sources.md) and
[verification evidence](docs/engineering/foundation-verification.md).
