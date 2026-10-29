# Foundation sources and dependency lock

The exact resolved versions and hashes live in `uv.lock`, generated with uv and Python 3.12.
No inference framework or model weights are dependencies. Version selection follows maintained
releases, with compatible major bounds in `pyproject.toml`; update the lock and run the behavior
suite when changing dependencies.

Official documentation pointers used for the foundation:

| Component | Official documentation | Application |
| --- | --- | --- |
| uv | https://docs.astral.sh/uv/concepts/projects/sync/ | Python 3.12 environment, lock, dev extra |
| FastAPI | https://fastapi.tiangolo.com/tutorial/sql-databases/ | Dependency-scoped database sessions and app API |
| FastAPI uploads | https://fastapi.tiangolo.com/tutorial/request-files/ | Multipart UploadFile/spooled file behavior |
| Starlette | https://starlette.dev/requests/ | Request streaming, form limits and lifecycle |
| Pydantic 2 | https://docs.pydantic.dev/latest/concepts/validators/ | Typed boundary validation |
| Pydantic Settings | https://docs.pydantic.dev/latest/concepts/pydantic_settings/ | Environment configuration and secrets |
| SQLAlchemy 2 | https://docs.sqlalchemy.org/en/20/orm/session_basics.html | Explicit transactions and session ownership |
| SQLAlchemy versioning | https://docs.sqlalchemy.org/en/20/orm/versioning.html | Optimistic concurrency rationale; API uses explicit CAS |
| Alembic | https://alembic.sqlalchemy.org/en/latest/tutorial.html | Explicit upgrade/downgrade migration |
| Psycopg 3 | https://www.psycopg.org/psycopg3/docs/basic/install.html | PostgreSQL production driver |
| argon2-cffi | https://argon2-cffi.readthedocs.io/en/stable/howto.html | Password hashing and verification |
| cryptography | https://cryptography.io/en/latest/fernet/ | Reserved for the upcoming credential-vault increment |
| boto3 S3 put | https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/put_object.html | Private uploads without public ACLs |
| boto3 S3 get | https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/get_object.html | Server-side Range retrieval |
| HTTPX | https://www.python-httpx.org/ | Runtime remote-provider HTTP client |
| pytest | https://docs.pytest.org/en/stable/how-to/fixtures.html | Isolated database/filesystem behavior fixtures |

The installed Starlette source is also inspected for multipart parser failure cleanup: current
`MultiPartParser.parse` closes its tracked spool files on parsing/stream exceptions. Do not silently
relax that cleanup guarantee when upgrading. Its current TestClient recommends HTTPX2; dev-only
transport ownership/source verification is recorded in the verification evidence. Runtime adapters
continue to depend on HTTPX 0.28 rather than changing provider client APIs.

HTTPX2 transport verification (2026-10-29):

- Current official [Starlette TestClient source](https://github.com/Kludex/starlette/blob/main/starlette/testclient.py)
  imports HTTPX2 and explicitly recommends it over the deprecated HTTPX1 test transport.
- Official [Starlette project metadata](https://github.com/Kludex/starlette/blob/main/pyproject.toml)
  includes `httpx2>=2.0.0` and points to `starlette.dev` as its documentation site.
- [PyPI project metadata](https://pypi.org/pypi/httpx2/json) lists Tom Christie as author,
  Pydantic Services Inc. as maintainer and `pydantic/httpx2` as source. The GitHub API confirmed
  the [repository](https://github.com/pydantic/httpx2) is owned by `pydantic` and is not archived.
- `httpx2==2.16.0` is dev-only. `httpx==0.28.1` remains the runtime provider client.
