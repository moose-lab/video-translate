# SaaS Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Follow test-driven development and report RED/GREEN command evidence.

**Goal:** Deliver a running SaaS API with protected account sessions, workspace-owned projects and private original-video upload/download, ready for durable cloud processing.

**Architecture:** FastAPI app factory and request-scoped SQLAlchemy sessions; Argon2 password hashes and random opaque session tokens; workspace ownership enforced in queries; storage interface with filesystem development and private S3 production implementations. The worker and later pipeline modules extend these foundations without introducing local models.

**Tech Stack:** Python 3.12, FastAPI/Pydantic 2, SQLAlchemy 2, Alembic, psycopg[binary], argon2-cffi, boto3, cryptography, python-multipart, HTTPX, pytest. Resolve maintained versions from package metadata, lock them and cite official APIs in docs/engineering/sources.md.

## File map

- `pyproject.toml`, `uv.lock`: server package, test dependencies, commands.
- `src/videotranslate/__init__.py`: package.
- `src/videotranslate/config.py`: typed settings, production validation and resource limits.
- `src/videotranslate/db.py`: engine, Base, session factory and request dependency.
- `src/videotranslate/models/core.py`: User, Workspace, Membership, AuthSession, LoginAttempt, Project and Asset.
- `src/videotranslate/security.py`: password hashing, token hashing, CSRF and session resolution.
- `src/videotranslate/errors.py`: structured safe errors.
- `src/videotranslate/storage.py`: private storage contract and filesystem/S3 implementations.
- `src/videotranslate/routes/auth.py`: register/login/me/logout.
- `src/videotranslate/routes/projects.py`: project CRUD and soft deletion.
- `src/videotranslate/routes/assets.py`: streaming multipart source upload and authorized download.
- `src/videotranslate/app.py`: app factory, middleware, dependencies and routers.
- `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_saas_core.py`: production migration.
- `tests/conftest.py`, `tests/test_auth.py`, `tests/test_projects.py`, `tests/test_storage.py`, `tests/test_upload.py`, `tests/test_config.py`: behavioral coverage.

## Task 1: Bootstrap and failing auth behavior

- [x] Create dependency/configuration files, source/test package directories and lock dependencies with `uv sync --extra dev`. No AI inference packages or weights.
- [x] Write a minimal test client fixture using a temporary SQLite database, temporary asset directory and `create_app(settings)` as the public factory. Startup creates development/test tables; production uses Alembic.
- [x] Add registration behavior test first:

```python
def test_register_creates_private_workspace_and_http_only_session(client):
    response = client.post('/api/auth/register', json={
        'email': 'creator@example.test', 'name': 'Creator',
        'password': 'correct-horse-123',
    })
    assert response.status_code == 201
    assert response.json()['workspace']['role'] == 'owner'
    assert response.json()['csrf_token']
    assert 'httponly' in response.headers['set-cookie'].lower()
    assert client.get('/api/auth/me').json()['user']['email'] == 'creator@example.test'
```

- [x] Run `uv run pytest tests/test_auth.py -q` and verify the missing registration behavior fails before implementing it.
- [x] Implement config, database models, structured errors, app factory and registration. Use `PasswordHasher().hash(password)` and `secrets.token_urlsafe(32)`; persist only SHA-256 hashes of session and CSRF values. Session expiry is an explicit UTC timestamp. Create the user, workspace and owner membership atomically.
- [x] Re-run the test, then commit the verified increment.

## Task 2: Login, CSRF, logout and credential safety

- [x] Add failing tests for: case-normalized duplicate email; wrong password returning generic 401; password minimum/maximum; name/email validation; expired/revoked session; missing/mismatched CSRF on mutations; successful login after logout; different sessions having different opaque tokens; bounded failed login attempts returning 429.

```python
def test_mutations_require_csrf(authenticated_client):
    client, auth = authenticated_client
    denied = client.post('/api/projects', json={'name': 'Film'})
    assert denied.status_code == 403
    allowed = client.post('/api/projects', json={'name': 'Film'},
                          headers={'X-CSRF-Token': auth['csrf_token']})
    assert allowed.status_code == 201
```

- [x] Run targeted tests and observe failures for the missing protections.
- [x] Implement login/logout/me, constant-time CSRF/hash comparisons and bounded persistent login throttling. Cookies use HttpOnly for session, SameSite=Lax, Secure in production and explicit expiry. Auth responses contain user/workspace/CSRF only, never password hash or session token in JSON. `/me` recovers the CSRF token from its matching CSRF cookie without returning the stored hash. Do not trust arbitrary forwarded IP headers.
- [x] Normalize Pydantic failures and database conflicts into safe error envelopes without echoing submitted passwords.
- [x] Verify `uv run pytest tests/test_auth.py -q`; commit.

## Task 3: Workspace-isolated project lifecycle

- [x] Add failing tests for project create/list/detail/rename/soft delete and cross-account list/detail/patch/delete access. Unknown or foreign IDs return 404 without confirming ownership. Project deletion hides associated asset access.

```python
def test_other_workspace_cannot_read_project(two_accounts):
    owner, visitor = two_accounts
    project = owner.create_project('Private video')
    assert visitor.client.get(f"/api/projects/{project['id']}").status_code == 404
    assert visitor.client.get('/api/projects').json()['items'] == []
```

- [x] Run tests to verify the missing behavior, then implement project routes using the authenticated workspace predicate on every query.
- [x] Create fields exactly as the master plan contract. `revision` begins at 1; accepted project changes increment it atomically. `status='draft'` until a source upload. Validate target languages as nonempty strings for now; the language increment adds the canonical catalog without changing stored shape.
- [x] Return bounded collection envelopes, user-safe timestamps and opaque IDs. No filesystem paths or credentials.
- [x] Verify all auth/project tests; commit.

## Task 4: Private media storage and upload

- [x] Write filesystem storage tests rejecting absolute keys, `..`, separators used to traverse and paths resolving outside the root. Write S3 contract tests against an injected in-process fake client; they test parameter construction and private object behavior, not a claimed live S3 deployment.
- [x] Write API tests for real tiny FFmpeg-generated video uploads, expected SHA-256 and byte size, source assignment/revision increment, authenticated content/range access, cross-workspace denial, oversized upload rejection, invalid extension rejection and database/storage cleanup on interrupted upload.

```python
def test_uploaded_source_is_private_and_downloadable(owner, visitor, tiny_mp4):
    project = owner.create_project('Upload')
    response = owner.client.post(
        f"/api/projects/{project['id']}/source",
        headers=owner.csrf_headers,
        files={'file': ('source.mp4', tiny_mp4, 'video/mp4')},
    )
    assert response.status_code == 201
    asset = response.json()['asset']
    assert owner.client.get(f"/api/assets/{asset['id']}/content").content == tiny_mp4
    assert visitor.client.get(f"/api/assets/{asset['id']}/content").status_code == 404
    assert 'storage_key' not in asset and 'path' not in asset
```

- [x] Run storage/upload tests before implementation.
- [x] Implement bounded chunked upload using a spool file, opaque workspace/project/asset storage keys and SHA-256. The original filename is display metadata only. Store asset metadata transactionally and remove newly written objects if persistence fails. Verify extension and declared media type without pretending that this replaces the later media-probe stage.
- [x] Implement content responses with authorized byte ranges, correct content type and safe Content-Disposition. Original uploads are private by default; do not set S3 public ACLs.
- [x] Implement `LocalStorage` only for development/tests and S3 storage for production. S3 operations accept an injected client for tests. Any presigned read URL has an explicit short expiry and is issued only after workspace authorization.
- [x] Verify all server tests; commit.

## Task 5: Production settings, migration and documentation

- [x] Add failing config tests: production refuses SQLite, local filesystem storage, missing secret key, missing public origin and incomplete S3 credentials; development may use explicit local settings. Ensure debug errors are disabled in production.
- [x] Add a migration test upgrading an empty database and inspecting the expected tables and uniqueness indexes.
- [x] Implement production validation and initial Alembic migration. Provide `.env.example` with variable names and non-secret development defaults only.
- [x] Write `README.md` startup/test commands and docs/engineering/sources.md with official FastAPI, SQLAlchemy, Argon2 and upload documentation used. State precisely which foundation behaviors are implemented and that model processing is the next increment.
- [x] Run `uv run pytest -q` and `uv run python -m compileall -q src`; inspect git diff and secret exposure. Commit, report changes, tests, RED/GREEN evidence and remaining integration dependencies.

## Review gates

1. Controller verifies the actual implementation against all requirements above and dispatches an independent spec reviewer.
2. Resolve spec gaps before dispatching a separate code-quality reviewer.
3. Continue to durable execution only after both reviews pass. Passing this increment does not complete the overall SaaS objective.
