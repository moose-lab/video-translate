# Durable execution verification

The implementation adds a real CPU FFprobe stage and an independent queue worker. No cloud model
or translation inference is implemented or claimed. SQLite/local files are development and test
adapters; production requires PostgreSQL and private S3-compatible storage.

Independent specification and quality gates passed at `652c0ce`. Final full-suite evidence is
**153 passed**. Review fixed two accepted-handle reconciliation gaps after input edits, an async
SSE SQL blocking issue, and successful-cache matching after retry. The original delayed-query
reproduction improved maximum event-loop heartbeat gap from525ms to12ms. Cache reproduction now
retains one successful run and preserves the original creation key's409 conflict. No review findings
remain within this increment; cloud inference and full SaaS acceptance remain separate.

The inherited worker/probe tests initially produced 6 failures and 7 passes because the worker and
probe modules did not exist. After implementation the same tests passed. Additional regression tests
cover a provider model identifier containing a colon, SSE cursor resumption and session expiry,
real worker SIGTERM and independent restart, stale and cancelled remote-job recovery, expired lease retirement
after project deletion, and FFprobe timeout cleanup. Recording handlers are test doubles, not inference.

A dedicated throwaway PostgreSQL 14.18 `execution_test` database was migrated independently. Real
API registration, project/source upload, two concurrent claimers, wrong-token finish rejection, and
project event sequencing passed. This is not a cloud deployment or a real S3 test. Database and
object storage do not share an atomic commit; orphan reconciliation requires supported object listing
and must only remove definitely owned aged orphans.

Follow-up verification should include production-scale load, live object storage behavior, and
provider-specific cancellation and long-running poll recovery. Full translation and model acceptance,
including English to Chinese/Japanese, remain future work.

Recorded local commands for this increment:

- `uv run pytest -q`:153 passed at final review (earlier pre-review implementation139).
- `uv run ruff check src tests alembic`, `uv run ruff format --check src tests alembic`,
  `uv run python -m compileall -q src`, and `git diff --check`: passed.
- PostgreSQL `alembic downgrade base`, `upgrade head`, and `alembic check`: passed in the isolated
  test database. Two simultaneous event writers confirmed that the second waits for the first commit
  and receives the next sequence.
- The supplied 700.407-second MP4 was uploaded and probed through the product queue locally: AV1,
  1280×720, AAC stereo audio ordinal 0 / stream 1, language `eng`. This is media inspection only.
- PostgreSQL composite foreign keys rejected both a mismatched workspace/project input state and an
  event referencing a run from a different project in the same workspace.
