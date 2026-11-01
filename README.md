# Video Translate

SaaS video dubbing workbench with separate Web, API and media Worker processes.
It includes authenticated private media, durable source analysis and full-pipeline coordination,
editable transcripts/roles/references/translation, per-line remote voices and independent QC,
shared timing maps, background mixing, captions and private multi-track exports. Hugging Face
is the primary remote ecosystem. There are no local AI models, model weights, torch,
transformers, ASR or TTS runtimes in this package.

The requested SIZsFGvtClM English→Chinese preview is an actual registered cloud-inference
result:59.51s of source becomes76.810s with natural voice speed preserved. The original and
Chinese playback files, verified exports and receipts are in the adjacent
`VideoTranslate-SIZsFGvtClM-EN-ZH` output folder. Human voice/listening acceptance is separate;
Japanese testing is deferred by the user. See [current delivery boundary](docs/engineering/remaining-product-obligations.md)
and [source-linked implementation flows](docs/engineering/voice-dubbing-source-flows.md).

## Run locally

Python 3.12 and [uv](https://docs.astral.sh/uv/) are required. The CPU media Worker requires FFmpeg/FFprobe, Rubber Band4/R3, Fontconfig and usable
outline fonts; YouTube extraction also requires the pinned Deno runtime in the container build.
Tests require FFmpeg on PATH;
the test fixture generates an actual tiny MP4 rather than labelling invented bytes as decoded media.

```sh
uv sync --python 3.12 --extra dev
cp .env.example .env
mkdir -p var
PYTHONPATH=src uv run --frozen uvicorn videotranslate.app:create_app --factory --host 127.0.0.1 --port 8000
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
a standalone API keeps this strict peer behavior. The packaged Web/API topology includes an
explicit trusted edge and one trusted Web proxy address so different clients retain distinct login
buckets. Follow [the deployment proxy contract](deploy/README.md); do not enable arbitrary proxy header trust. Avoid request body/header or exception
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
regional forms using the646-language catalog. Catalog membership does not prove a particular provider
supports or has tested that language.

Both collection endpoints, `GET /api/projects` and `GET /api/projects/{id}/assets`, accept
`limit` (default 50, minimum 1, maximum 200) and `offset` (default 0, minimum 0). Their `{items,total}`
envelope keeps `total` equal to the entire owned, active filtered collection, independent of the
requested page. Items use stable `created_at DESC, id ASC` ordering. Invalid bounds return 422;
foreign or deleted project asset collections remain 404.

Upload one multipart `file` to `POST /api/projects/{id}/source`; the response is `{project, asset}`.
Allowed extension/MIME pairs are MP4/M4V, MOV, WebM, MKV and AVI. Both declarations are checked;
media decoding and analysis run in the independent worker after upload. Upload sets status `uploaded`,
stores SHA-256 and byte size, and increments the project revision. The default limit is 512 MiB,
configurable via `VT_UPLOAD_MAX_BYTES`. Multipart body spooling is bounded before parsing with a
64 KiB header allowance, then exact file size/hash are read in chunks. Files, private object keys,
metadata and revisions are cleaned up/rolled back on handled failures; existing sources survive
failed replacements. A process crash between object storage and database commit still needs future
orphan reconciliation, and a failed remote delete must be repaired operationally.

`GET /api/projects/{id}/assets` returns `{items,total}`. `GET /api/assets/{id}/content` authenticates
every request. Binary media uses safe attachment headers and supports one byte range, including
suffix/open ranges (206); waveform JSON is validated and returned as the exact complete stored object. Invalid or multiple ranges return 416. Unknown/foreign IDs and assets belonging to
soft-deleted projects return 404. Original cookies are never forwarded to source URLs. Public HTTPS/YouTube import uses the
separate guarded `/api/projects/{id}/source-imports` command; unsupported or unavailable
upstream links provide an upload fallback. Direct adaptive YouTube video/audio pairs are downloaded
through the same boundary and muxed locally; no browser credentials or remote manifests are used.

Errors use `{error:{code,message,retryable,details}}`; validation details contain field locations and
codes only, never submitted values. Responses are private/non-cacheable; unexpected exceptions are
contained before ASGI server traceback logging. Public responses omit passwords, hashes, session
tokens, storage paths/keys and credentials.

## Verify

```sh
PYTHONPATH=src uv run --frozen --extra dev pytest -q
PYTHONPATH=src uv run --frozen --extra dev python -m compileall -q src
uv run --frozen --extra dev ruff check src tests alembic
uv run --frozen --extra dev ruff format --check src tests alembic
uv lock --check
```

Tests use fresh real SQLite databases and real files. They cover identity/session/CSRF, persistent
login limits, workspace isolation, atomic revisions, real MP4 upload hash/bytes/ranges, failure cleanup,
production refusals, private S3 call parameters and a clean Alembic upgrade/downgrade/schema parity.
The production cookie/factory unit test injects SQLite/local storage only to inspect that factory's
behavior; it is not a live PostgreSQL or S3 test. Cloud deployment and real inference remain separate
acceptance stages. See [engineering sources](docs/engineering/sources.md) and
[verification evidence](docs/engineering/foundation-verification.md).

## Durable media and cloud worker

Run the API and worker as separate processes against the same database and private storage. Apply
Alembic migrations before starting production processes. The PostgreSQL database is the production
queue; SQLite and local storage are for development and tests. Install FFmpeg/FFprobe on the worker.

```sh
PYTHONPATH=src uv run --frozen python -m videotranslate.execution.worker
PYTHONPATH=src uv run --frozen python -m videotranslate.execution.worker --once
```

The one-shot command prints `{"claimed": true}` or `{"claimed": false}`. Configure
`VT_WORKER_LEASE_SECONDS`, `VT_WORKER_HEARTBEAT_SECONDS` and `VT_WORKER_POLL_SECONDS`; heartbeat
must be shorter than the lease. Probe limits are set with `VT_PROBE_MAX_BYTES`,
`VT_PROBE_MAX_DURATION_SECONDS`, `VT_PROBE_MAX_PIXELS` and `VT_PROBE_TIMEOUT_SECONDS`.

Create a probe with `POST /api/projects/{id}/runs` and `{"stage":"probe"}`; mutations need CSRF.
Run lists, individual run/attempt details, retries, cancellation and project events are private to
the workspace. `GET /api/projects/{id}/events/stream` supports `after`, `Last-Event-ID`, and
`follow=false`. Probe reports zero-based audio ordinals separately from FFmpeg stream indices; a
video without audio can be probed but cannot produce source speech. Real registered stages include
`source_import`, `extract`, `separate`, `transcribe`, `reference`, target-specific translation phases,
per-line `synthesize` and `voice_qc`, `waveform_envelope`, `plan_fit`, `deliver` and `workflow_continue`. Guarded workflow/reference/translation/synthesis routes capture the necessary editor proofs; generic run creation
cannot bypass those command boundaries. Unimplemented stages return `STAGE_UNAVAILABLE`.

Handlers implement `StageDefinition` with option validation, exact input resolution, and `handle`;
an optional short database-only `publish` callback runs after lease and freshness verification.
Remote adapters must use `RunContext` submission checkpoints and resume a saved remote ID. An
uncertain named inference submission requires explicit acknowledgment before retry. Upload preparation
is separate from that boundary. Object storage and database commits are not atomic: the existing
prepared-object reservations, settlement and cleanup must remain enabled for derived assets; broader
deployment storage reconciliation still requires operational verification.

## Source, cast, references and translation API

After a fresh source upload, enqueue `probe` and wait for its successful current result. Then use
`PUT /api/projects/{id}/source-selection` with the **current project revision**, owned source asset,
audio ordinal and explicit millisecond window. Read `GET /api/projects/{id}/timeline` for current
selection/transcript identity, source rows, cast, references and target summaries.

`POST /api/projects/{id}/workflow` accepts `action: "analyse"` or `"prepare_media"`, the current
timeline `expected_editor_fingerprint` and `auto_advance`. It creates real extraction/separation/ASR
jobs and defaults to source/cast review. Poll its returned workflow ID. A provider that supplies no
speaker labels leaves rows unassigned for manual review. Work labels are not real-person identity.
`auto_advance` never supplies missing roles or references.

Source rows support guarded edits, split/merge and SRT/VTT import preview/apply. Speakers support
versioned edits and merge. Source and target originals/history remain available through bounded
revision endpoints. Mutations carry the active selection/transcript plus relevant row revisions;
reload after409 instead of overwriting newer work. Times in the current timeline are relative to
the selected window; original absolute bounds are retained separately.

`POST /references/extract` below a project extracts the complete current source segment from source
audio or separated vocals; split the segment explicitly first when a narrower reference is needed.
`POST /references/upload` accepts private audio with reference wording/language and validates it in
the worker. Reference wording corrections create immutable versions. Bind a speaker default with
`PUT /speakers/{speaker_id}/reference` or an explicit line override with
`PUT /segments/{segment_id}/reference`. Both are project-scoped. Measured warnings and staleness are
visible; extracted audio is not silently trimmed while retaining its old transcript.

Create/materialize target tracks through `POST /language-tracks`, with an explicit catalog tag,
`Fast`, `Cinematic` or `Autofit` mode, supplied context and glossary. A declared project target alone
is not an initialized target record. For a chosen target, fetch the timeline with
`?target_language=zh` (or another exact tag). `POST /language-tracks/{tag}/translate` accepts active
selection/transcript identity, track revision and explicit source rows, each with ID, current target
revision (0 if absent), current source-text fingerprint, lock and approval state.

Fast performs direct batches. Cinematic separately checkpoints whole-source context, draft,
critique and rewrite. Autofit adds labelled heuristic estimates and an independently recoverable
shortening suggestion where supported; it does not measure audio or automatically change wording.
Inspect `GET /language-tracks/{tag}/translate/{command_id}` and retry only the failed phase using its
run ID. Locked/approved rows are preserved by default; forced replacement is explicit and audited.
Shorter wording requires guarded `POST /language-tracks/{tag}/translate/{command_id}/apply-suggestion`.
Manual changes and approval use the current row/source proof. No cloud phase auto-approves a target.

All abbreviated routes in this section are prefixed by `/api/projects/{id}`. OpenAPI contains the
exact finite request contracts. Configure providers through the protected setup page before invoking
cloud work. Named jobs retain their actual host/API/ID and terminal files; prepared synchronous
results survive publication conflicts without silently paying for inference again. An interrupted
named submission is visibly uncertain; repeated commands do not override that state. Chinese and
Japanese operations and row histories remain independent.

Tests use explicit recording providers, real CPU media and optional isolated actual PostgreSQL.
Set `VT_TEST_POSTGRES_ADMIN_URL` only to an administrator URL for a disposable test server; fixtures
create/drop uniquely named test databases. See `docs/verification/task4b-analysis.md`,
`task4c-translation.md` and `upload-preparation.md` for their actual evidence/gates. Recording-provider tests are separate from real inference and final listening acceptance.
The actual requested English→Chinese integration and its output boundaries are recorded in
[the current delivery record](docs/engineering/remaining-product-obligations.md); Japanese is deferred.

## Natural per-line voice synthesis

Under `/api/projects/{id}/language-tracks/{tag}`, `POST /synthesize` captures explicit current
source rows, target revisions, effective references/controls and audio-selection revisions. Read
`GET /synthesis`, `GET /synthesis/{command_id}` and each segment's `/audio-history` for actual line
runs, measured natural audio and immutable selection history. Track and per-line `/voice-settings`
are versioned; a null line override restores the track defaults. Use the guarded segment
`/audio-selection` endpoint to choose an owned validated historical output.

Default synthesis preserves chosen audio; explicit replacement or regeneration is recorded.
Unapproved wording and reference warnings require their exact current review proofs. A model result
is not listening approval: outputs report `acceptance: not_assessed` until the later QC/review stage
exists. Duration planning uses decoded audio measurements; fitting and final mix/export are separate.

Natural cache identity includes exact wording, model language, reference audio/transcript/binding,
connection revision and effective controls. Slot/display changes do not automatically regenerate it.
Durable operations retain real remote receipts and original measured provenance; interrupted local
reuse resumes without another model POST. Invalid proof is visible and cannot be manually selected
as verified audio. Current editor guards still prevent an old completion from replacing a newer
choice. See `docs/verification/task5-synthesis-qc.md` for the backend gates. The requested sample now has
eight real clones, eight independent QC results and a verified Chinese video preview; human
listening acceptance and the deferred Japanese integration are separate states.

### Provider credential storage

Provider credentials are encrypted using a workspace- and purpose-derived Fernet key based on `VT_SERVER_SECRET`; the API returns only whether a credential is configured and its revision. Preserve the server secret securely across restarts. To rotate it, deploy a controlled maintenance operation that reads and decrypts every credential using the old secret, encrypts each with the new secret, verifies the results, and updates them transactionally before switching all application instances. No automatic rotation utility is implemented yet; changing the secret alone makes existing credentials unreadable.

Provider connection settings are revisioned separately from credentials. The language catalogue records synthesis model metadata, not verified end-to-end language support.

### Setup interface

The development interface runs on loopback at `http://127.0.0.1:5173` and proxies `/api` to the local API at `127.0.0.1:8000`. Start the API using the documented environment, then run `pnpm install --frozen-lockfile` and `pnpm dev` in `web/`. Use Node 22, 24 or 26 as specified by `web/package.json`; the bundled Node 24 runtime was used for verification. `pnpm test`, `pnpm typecheck` and `pnpm build` run the frontend checks.

For the same-origin production gateway, use [deploy/compose.yaml](deploy/compose.yaml) and
[deploy/nginx.conf](deploy/nginx.conf) with the exact trusted-edge/private-proxy contract in
[deploy/README.md](deploy/README.md). It serves the built Web assets, keeps API private, preserves
separate client login throttles and disables buffering for event streams. The520MiB gateway body
limit accommodates the default512MiB upload plus multipart overhead; adjust both together.
Docker/Nginx are unavailable here, so image/Compose startup and HTTPS ingress are unverified.

Provider network access is direct by default and ignores ambient proxy variables. An administrator can set `VT_PROVIDER_PROXY_URL` and `VT_PROVIDER_DNS_OVER_HTTPS=true` when the deployment requires a trusted proxy and DNS over HTTPS. Proxy credentials belong in the server environment, never the browser or the provider settings API. HTTP proxies are restricted to loopback; HTTPS proxies must have a valid certificate. The DNS resolver uses a fixed public Cloudflare endpoint, validates every returned address as public, and tunnels to a validated address while retaining the original provider hostname for TLS verification. Provider authorization headers travel only inside the provider TLS tunnel. The runtime integration relies on HTTPX/httpcore's pinned backend interface and must be reverified when changing those dependencies. The real public checks so far cover the local loopback HTTP proxy; remote HTTPS-proxy operation has not been independently verified.

## Container runtime

See [SaaS runtime packaging](deploy/README.md) for separate API/Worker/Web images,
explicit migrations and production PostgreSQL/private-S3 configuration. Image
build and actual cloud deployment are separate verification steps.
