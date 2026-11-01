# SaaS runtime packaging

This packages the existing service as separate API, Worker, migration and Web
containers. PostgreSQL, private S3 and the trusted HTTPS ingress are external
prerequisites. These files do not provision them or deploy to a cloud account.

The runtime installs the project from `uv.lock` as a non-editable wheel. Python
3.12, FFmpeg, H.264/AAC/MP3 codecs and Rubber Band 4.0.0/R3 are build checks. The
runtime also includes Fontconfig, Noto Core/CJK fonts and a libass subtitles-filter
build assertion for the forthcoming burn-in slice. This does not claim that
burn-in or per-script rendering has been implemented or accepted. The
native runner uses its installed absolute script path; no `PYTHONPATH=src` is
needed. The Web build uses its frozen pnpm lock and contains no server secrets.

## Configure

From the repository root:

```sh
cp deploy/production.env.example .env.production
chmod 600 .env.production
```

Fill every blank with values from your secret manager. Generate a random server
secret, keep it stable across API/Worker restarts, and back it up securely.
Changing it alone invalidates sessions and makes stored provider credentials
unreadable; the project does not yet include automatic credential-key rotation.

Use a PostgreSQL role that owns the application's schema and can run its Alembic
DDL, with no superuser, createdb or createrole privileges. URL-encode the password
in `VT_DATABASE_URL`. The example verifies the database certificate against the
image's system CA bundle; mount the provider's CA read-only and change
`sslrootcert` if that provider uses a private CA.

Use a dedicated private S3-compatible bucket, with anonymous/public access
blocked and credentials limited to the application's object operations. Set the
actual HTTPS endpoint and region (`auto` for R2 where required by the provider).
API and Worker must share the same database, bucket and server secret. Provider
credentials are added through the authenticated application after startup.
Never put provider or storage credentials in Web build variables.

The public origin must be the exact HTTPS origin of the Web app, with no path.
Your TLS ingress forwards it to `127.0.0.1:8080`. Direct HTTP on that local port is
only useful for preflight; production authentication uses secure cookies. The
API trusts rewritten proxy headers only from the fixed Web address on a
separate internal network. The standalone runtime image still trusts no proxy.

Set the required `VT_TRUSTED_EDGE_CIDR` to the actual TLS-edge socket peer seen by
Web **after Docker port forwarding**, not a claimed HTTP header. For a host TLS
proxy this may be the edge bridge gateway rather than `127.0.0.1`; verify it in
network inspection and the Web log's `edge_peer` field. Use an exact `/32` or
`/128` where possible. Never configure `0.0.0.0/0`, `::/0` or an untrusted LAN.
The three `VT_PROXY_*` values instead define the private Web→API network; they
must remain consistent and must not conflict with existing networks.

The TLS edge must **overwrite**, not append or preserve, inbound forwarded
identity. For an Internet-facing Nginx TLS edge the relevant forwarding is:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host video.example.com;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto https;
}
```

This assumes that edge's socket peer is the client. If another proxy precedes
it, first establish that edge's own validated real-client contract with only
that proxy's exact trusted peers. Do not pass an arbitrary browser-supplied
address. Web applies real-IP handling only to the configured edge peer and then
replaces X-Forwarded-For/X-Real-IP with its validated `$remote_addr`; untrusted
peers' spoofed headers are ignored. It forwards that one address to API over the
private network. Uvicorn trusts only Web's configured address, with no `*`
trust. This separation keeps the persistent per-client login throttle from
becoming one global proxy bucket or accepting a spoofed public identity.

## Build and start

Docker Engine and Compose v2 are required. Base tags are convenient build inputs;
record the built image digests and source revision before promotion.

```sh
docker compose --env-file .env.production -f deploy/compose.yaml config --quiet
docker compose --env-file .env.production -f deploy/compose.yaml build --pull
docker compose --env-file .env.production -f deploy/compose.yaml run --rm migrate
docker compose --env-file .env.production -f deploy/compose.yaml up -d api worker web
```

`config --quiet` validates without printing the rendered secrets. Migration is
explicit and must succeed before API/Worker start. Production does not call
`create_all` or migrate when importing the app. A failed migration must be
resolved before starting application services.

Only Web's loopback port is published. API and Worker run as UID 10001 with a
read-only root filesystem and writable, bounded `/tmp`. Worker CPU/media limits
still apply; the example adds a 4 GiB memory limit and two-CPU quota. Choose
capacity and concurrency from measured media load rather than assuming these
example limits are sufficient for every upload.

## Verify the actual environment

```sh
docker compose --env-file .env.production -f deploy/compose.yaml ps
docker compose --env-file .env.production -f deploy/compose.yaml run --rm migrate alembic current
curl --fail --silent --show-error 'https://video.example.com/api/languages?limit=1'
```

Check API readiness (database `SELECT 1` plus the local metadata endpoint), Worker
process state, the expected Alembic head and HTTPS secure-cookie login. S3 policy
and actual write/read/range/delete behavior must be verified against the chosen
bucket. Then upload a small owned video and verify the real queued Worker result,
private download SHA/size and full decode. Remote inference can incur provider
charges: do the connectivity/metadata checks first, then authorize the specific
provider smoke run. Catalog language metadata is not end-to-end acceptance.

Keep old immutable image digests and tested database/bucket backups for rollback.
Do not run an automatic schema downgrade: if an older image is incompatible with
the upgraded schema, restore a tested backup under maintenance. This packaging
neither performs backups nor claims that rollback has been exercised.

## Verification on this machine

- Docker and Podman executables are unavailable, so no image build, Compose
  startup, Linux DSP execution or public deployment is claimed.
- `uv build` produced the sdist and wheel. The wheel was installed in a fresh
  temporary virtualenv; from `/tmp`, the installed runner loaded the actual R3
  engine and all 647 catalog records without a project `PYTHONPATH`.
- Ruby/Psych parsed Compose and checked four separate services, read-only roots,
  only non-secret edge configuration on Web and no directly published API port. The example was
  accepted by the current production `Settings` using disposable fixture secret
  values; this made no database, S3 or provider calls.
- `docker compose config`, Dockerfile image builds, Nginx/Linux codec checks,
  actual PG/S3 connectivity and HTTPS ingress remain unverified on this machine.
  The image's codec/R3 and Nginx real-IP/envsubst assertions run at build time
  when Docker is available.
- The proxy-trust fix was checked with the actual Uvicorn proxy middleware and
  persistent login reservation in an isolated database: distinct clients from
  the configured proxy stayed separate; a sixth attempt from one client was
  limited; changing spoofed headers from an untrusted peer did not change its
  identity or bypass the limiter. This is not a live Nginx/TLS test.
