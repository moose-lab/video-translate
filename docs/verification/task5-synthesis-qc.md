# Task 5A natural synthesis verification

Implementation verification only. Independent SPEC and QUALITY reviews and the controller's actual hosted-product acceptance remain separate. Task 5B listening/QC, media finishing and UI are outside this change.

## Late actual submission receipts

The previous strict lease path lost an actual returned event ID when the worker lease expired during the named POST. RED: `test_actual_handle_returned_after_lease_expiry_is_fenced_and_saved` observed `remote_id=None` after the recording provider returned its real fixture event ID. The optional `SubmissionBinding` now captures owned operation/run/project/workspace identity, generation, input fingerprint and provider/model from the persisted operation before POST. Receipt recording retains the original operation's ID after expiry or acknowledgement of a newer generation; only the exact still-current compatible generation may receive a current run handle. It does not transfer a lease or publish a result. Repeated same-ID receipts are idempotent; conflicting IDs and forged bindings are rejected. Existing callers retain strict lease acceptance.

GREEN: self-cleaned temporary-directory run with `PATH=/opt/homebrew/bin:$PATH PYTHONPATH=src:tests .venv/bin/python3.12 -m pytest tests/test_submission_receipts.py tests/test_execution.py tests/test_analysis_execution.py -q --basetemp <owned-temporary-directory>`: **32 passed**. This covers all binding fields, newer lease ownership, idempotence/conflicts, cancellation/deletion/staleness and the unchanged strict default. Product synthesis additionally tests expiry→late handle→poll without another POST and an acknowledged newer generation retaining the old receipt only historically.
