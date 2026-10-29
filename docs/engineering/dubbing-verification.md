# Dubbing domain increment 4A verification

Scope: manual domain foundations only. This increment does not submit remote ASR,
separation, translation, reference, cloning, fitting, mixing or export jobs. No model
weights, torch, transformers, local AI runtime or paid inference was used. The real
CPU probe fixture is generated in each test's temporary directory. The user's
existing preview database, server key and five configured connections were not read
or modified.

## Interfaces and lineage

- `PUT /api/projects/{id}/source-selection` takes the current project `revision`,
  owned current `source_asset_id`, audio `audio_ordinal`, `start_ms` and optional
  `end_ms`. Missing end resolves to actual successful fresh probe duration. The
  result includes selection `id/revision/start_ms/end_ms/source_asset_id/stale` and
  actual `track` facts, including both ordinal and absolute stream index and probe
  run ID. A real change creates immutable selection history and clears the active
  transcript pointer; old batches remain available in history. Legacy source
  uploads/track patches invalidate the selection facet and old transcript, including
  a track-away/track-back sequence. A full-file probe depends only on the source
  video and remains reusable across window/track selection.
- Source editing and translation/import mutations take `selection_revision` and
  `transcript_revision`. The latter is the immutable active batch ID, not a counter
  changed by each cell edit. Initial manual creation passes explicit null. Each
  existing segment/translation/track/speaker additionally has a row `revision`.
  Translation creation expects revision 0. Project revision records lineage and
  is not used to reject unrelated cell edits.
- `POST /segments` returns `{segment, transcript_revision, selection_revision}`.
  Segment PATCH returns the corrected segment. Split returns `{segments}` and
  merge returns `{segment}`. Split parts and merge require explicit `speaker_id`
  (null means unassigned), text and relative timing. Replaced stable IDs are
  archived; `parent_segment_ids` and immutable revisions retain lineage. Relative
  and absolute source timings are both returned.
- Language track creation/configuration is manual and supports catalog tags and
  variants with Fast/Cinematic/Autofit settings. These are configuration labels;
  no translation, context generation or duration estimate is fabricated. Supplied
  summary/glossary snapshots are immutable. Declared project targets without a
  stored track are marked `materialized:false` on read. Existing project target
  PATCHes coherently archive/restore materialized tracks and retain their config.
- Translation PATCH returns current revision, text, lock/stale/review/approval and
  context/source-fingerprint lineage. Source meaning changes stale even locked
  wording. Explicit approval appends a revision against the actual current source
  fingerprint; timing-only edits and speaker renames preserve translated meaning.
  Context/mode changes invalidate suggestion inputs without replacing committed
  approved wording. Archived target configuration requires explicit restoration.
- Timeline GET defaults to 100 source rows, maximum 200, stable display order,
  explicit total/offset and only the selected target's corresponding translations.
  Cast and track summaries are capped at 200 with totals; paged GET `/speakers`
  and `/language-tracks` allow the remaining stored summaries to be inspected.
  References are explicitly unavailable in 4A. All reads leave DB state unchanged.
- Bounded history GETs: `/source-selections`, `/transcripts`,
  `/transcripts/{id}/segments`, `/segments/{id}/revisions`,
  `/speakers/{id}/revisions`, `/language-tracks/{tag}/contexts`, and
  `/language-tracks/{tag}/segments/{id}/revisions`.

## Caption previews and limits

Source/target `/import/preview` accepts guarded format/content and is read-only.
It returns deterministic ordered cue IDs, timing errors, candidate matches,
ambiguity/lock/mapping conflicts and a canonical digest. Apply resubmits the same
content, source guards, digest and an explicit mapping covering exactly the cue
IDs. Source imports create a new immutable batch (`new_transcript` or
`replace_current`); they never zip onto existing source IDs. Target mappings name
stable segment IDs and expected translation row revisions; SRT/VTT timing or
numbered indices are suggestions, never an implicit mapping. The digest covers
current source revisions, target states/locks and track/context lineage, so source
or target edits after preview cause conflict. Locked target replacement requires
`force_locked:true` and an audited forced import event. Failed applications roll
back history, pointers, facets, cast creation and events together.

Caption text is bounded to 256 KiB UTF-8 overall, 1,000 cues, 10,000 characters per
cue and 200,000 text characters total. This is a deliberate manual-review batch
limit; larger transcripts must be imported in a later supported batching workflow,
not silently truncated. The outer JSON envelope is streamed with a 4 MiB bound
before JSON decoding, allowing explicit mappings/JSON escaping. Context summary is
20,000 characters; glossary is at most 200 entries and 20,000 characters total;
all edit text is at most 10,000 characters. Invalid Unicode/control input and
non-integer/negative/reversed/out-of-window timing are rejected with safe errors.

SRT/VTT preserves CJK, RTL, combining marks and meaningful newlines/`<br>`. Styling,
script/style/media markup and external resources are ignored as data. Plain
captions do not prove speaker detection. A single VTT voice label can be explicitly
mapped to a work label; multiple labels in a cue produce an ambiguity warning and
remain unassigned unless the user explicitly maps a role. Numbered text is target
only and has no invented times.

## Red/green evidence

Initial command before implementation:

```sh
PYTHONPATH=src uv run --frozen --extra dev pytest -q tests/test_dubbing_domain.py tests/test_dubbing_edits.py tests/test_dubbing_imports.py
```

Observed 18 failures for absent source-selection/edit/import routes and parser.
Initial implementation brought those 18 tests green (11.29s). Additional tests
then demonstrated and corrected these regressions before the final check:

- source meaning did not initially invalidate direct descendants of committed
  manual translation inputs;
- legacy track-away/track-back could incorrectly reactivate old selection;
- fresh selection initially retained a blocking old active transcript pointer;
- segment archival did not initially stale manual target descendants;
- legacy project target PATCH did not initially synchronize track archive state;
- mixed VTT labels initially took the first label;
- summary collections were initially unbounded;
- audit events initially omitted the edited stable cell ID;
- split initially allowed omitted role distribution;
- archived target configuration initially allowed edits without restoration;
- oversized JSON and NUL work labels were initially accepted.

An intermediate full run had 278 passing tests and one old hardcoded migration
table-list expectation, updated for the thirteen additive domain tables. Another
full run (283 passing) caught an extra positional argument accidentally introduced
in context-history routing; this was corrected before final verification.

## Isolated migration checks

`0004_dubbing_domain.py` is a frozen self-contained schema migration. It does not
import current ORM models into historical migration code. It adds the narrow
`assets(id,project_id,workspace_id)` unique index needed for composite references,
all domain ownership/pointer/parent constraints, and explicit circular pointer
constraints. SQLite and PostgreSQL metadata comparisons are empty after upgrade
and after downgrade/upgrade. PostgreSQL additionally exercises downgrade with
populated history and pointer cycles.

The opt-in live PostgreSQL test creates a unique `dubbing_4a_*` database owned by the
local test role, runs upgrade/metadata parity, real CPU probe, ownership denial and
actual simultaneous row CAS, then populated downgrade to 0003, upgrade and parity.
It drops only its own temporary database and leaves the test server running.

```sh
VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres PYTHONPATH=src uv run --frozen --extra dev pytest -q tests/test_dubbing_domain.py::test_postgres_dubbing_roundtrip_ownership_and_simultaneous_cas
```

Observed: 1 passed, including independent row results `[200,200]` and same-row
results `[200,409]`, upgrade/down/up parity and composite ownership denial.

An isolated simulation also creates a pre-Alembic development baseline-3 DB with a
fake opaque credential. It verifies that its schema matches the frozen baseline,
stamps 0003, upgrades to head, checks unchanged fake ciphertext and confirms the
new asset ownership index exists. Observed: 1 passed. `create_all()` alone does
not add the new index to an existing assets table. An unversioned development DB
must be backed up and its baseline verified before stamping; do not blindly stamp
or rerun the initial migrations. This test is evidence for the controller's later
protected upgrade, not a claim that the real preview was upgraded here.

## Final checks

Fresh verification on 2026-10-30:

```sh
VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres PYTHONPATH=src uv run --frozen --extra dev pytest -q
# 287 passed in 62.09s; PostgreSQL opt-in test ran, no skips.
PYTHONPATH=src uv run --frozen --extra dev ruff check src tests alembic
# All checks passed.
PYTHONPATH=src uv run --frozen --extra dev ruff format --check src tests alembic
# 75 files already formatted.
PYTHONPATH=src uv run --frozen --extra dev python -m compileall -q src tests alembic
# exit 0.
uv lock --check
# Resolved 75 packages; exit 0.
git diff --check
# exit 0.
```

Independent SPEC then QUALITY review is performed by the controller after this
implementer handoff. Frontend files were unchanged in 4A; this API/domain
increment does not claim browser product acceptance. Full English-to-Chinese/
Japanese inference and product acceptance remain future work in 4B/4C; this
domain increment is not the completed SaaS.

## Independent SPEC fixes after 8b623b5

The reviewer reproduced three gaps. Each was first added as a failing regression:

1. A work label from an earlier source window could be bound to a new window.
   `Speaker.selection_id` is now required and has a composite owned-selection FK
   in the unreleased 0004 migration. It is immutable through the API. Work labels
   may be created after a valid source selection and before the first manual
   transcript. Creation, binding, patching, merging, timeline cast summaries and
   normal role listing use only the live current source selection. Source asset,
   audio track or window changes cannot reactivate old cast implicitly. New
   selections require explicit creation of fresh work labels. Historical IDs and
   label revision history stay readable; `/speakers?include_historical=true`
   explicitly lists earlier selections' labels, and `include_archived=true` is a
   separate choice. Historical role binding and editing return 404. Both manual
   segment creation and caption import mapping are covered by the same check.
2. JSON-escaped lone surrogate characters in glossary keys/values could be saved,
   then break a context-history response. The inherited string validator now
   validates nested dictionary keys/values and list/tuple members using an
   iterative stack. It rejects invalid Unicode/control characters with a safe 422,
   with depth 20, 20,000 visited-node and 2,000-item container bounds. It does not
   recurse on attacker-supplied nesting. Valid CJK, RTL, combining marks and emoji
   round-trip unchanged.
3. A malformed glossary value could place its private dictionary term in Pydantic's
   error location. A field-level pre-type check now rejects non-text glossary
   keys/values before dictionary-entry parsing. The public location is the static
   `body.glossary`; submitted terms never appear in that error response and no
   context/track history is written.

RED evidence: six initial role/Unicode regression cases failed (old role binding
and import returned 201; invalid nested strings were accepted). After correction,
those six passed in 5.00s. The separate private-term error regression then failed
because `PRIVATE_DIALOGUE_SENTINEL` appeared in the response; after pre-type
validation, the focused Unicode/privacy/bounds group passed all six in 5.17s.

The PostgreSQL migration/CAS test now also persists both historical and current
selection-scoped work labels and their revisions, rejects a Speaker referencing a
selection from another project at the DB layer, then downgrades the populated
domain, upgrades and compares metadata. The real preview has not been upgraded;
0004 remains unreleased and was updated in place for this review correction.

Fresh post-review verification on 2026-10-30:

```sh
VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres PYTHONPATH=src uv run --frozen --extra dev pytest -q
# 295 passed in 62.56s, including the populated PostgreSQL speaker-selection FK roundtrip.
PYTHONPATH=src uv run --frozen --extra dev ruff check src tests alembic
# All checks passed.
PYTHONPATH=src uv run --frozen --extra dev ruff format --check src tests alembic
# 75 files already formatted.
PYTHONPATH=src uv run --frozen --extra dev python -m compileall -q src tests alembic
# exit 0.
uv lock --check
# exit 0.
git diff --check
# exit 0.
```
