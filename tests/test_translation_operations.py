"""Durable target translation using recorded providers only."""

import json

import pytest
from dubbing_helpers import create_line, guard, make_track, selected
from sqlalchemy import select

from videotranslate.execution.worker import Worker
from videotranslate.models.analysis import PrivateOperation
from videotranslate.models.execution import StageRun


@pytest.fixture
def translation_project(dubbing_project):
    c, h, p = dubbing_project
    s = selected(dubbing_project)
    line = create_line(dubbing_project, s, "IBM makes computers", end_ms=400)["segment"]
    base = f"/api/projects/{p['id']}"
    track = make_track(c, h, base, "zh-Hant", summary="Supplied summary", glossary={"IBM": "IBM"})
    result = c.put(
        "/api/providers/translation",
        headers=h,
        json={
            "revision": 0,
            "adapter": "openai_compatible",
            "endpoint": "https://translator.example/v1",
            "model": "test-model",
            "credential_ref": None,
        },
    )
    # The custom host is an administrator runtime setting.
    if result.status_code != 200:
        c.app.state.settings = c.app.state.settings.model_copy(
            update={"provider_allowed_hosts": "translator.example"}
        )
        result = c.put(
            "/api/providers/translation",
            headers=h,
            json={
                "revision": 0,
                "adapter": "openai_compatible",
                "endpoint": "https://translator.example/v1",
                "model": "test-model",
                "credential_ref": None,
            },
        )
    assert result.status_code == 200, result.text
    return c, h, p, s, line, track


def request_body(s, line, track, **kw):
    return (
        guard(s, line["transcript_revision"])
        | {
            "track_revision": track["revision"],
            "segments": [
                {
                    "id": line["id"],
                    "revision": 0,
                    "expected_source_text_fingerprint": line["source_text_fingerprint"],
                    "locked": False,
                    "approved": False,
                }
            ],
        }
        | kw
    )


class RecordingChat:
    allowed_hosts = {"translator.example"}

    def __init__(self):
        self.calls = []
        self.hook = None
        self.fail = None
        self.closed = 0

    def close(self):
        self.closed += 1

    def post_json(self, url, body, **kwargs):
        phase = body["messages"][0]["content"].split("Phase: ")[1].split(".")[0]
        data = json.loads(body["messages"][1]["content"])
        quoted = data["quoted_data"]
        self.calls.append((phase, data))
        if self.hook:
            self.hook(phase)
        if phase == self.fail:
            raise TimeoutError("lost response")
        if phase == "context":
            output = {
                "target_language": data["target_language"],
                "source_ids": [r["id"] for r in quoted["segments"]],
                "summary": "Generated summary",
                "glossary": {"IBM": "wrong", "computer": "電腦"},
            }
        else:
            text = {
                "draft": "IBM 製造電腦產品。",
                "critique": "Use natural speech.",
                "rewrite": "IBM 製造電腦。",
                "shorten": "IBM 造電腦。",
            }[phase]
            output = {
                "target_language": data["target_language"],
                "segments": [{"id": r["id"], "text": text} for r in quoted["segments"]],
            }
        return json.dumps(
            {
                "id": "actual-response-" + str(len(self.calls)),
                "usage": {"total_tokens": 9},
                "choices": [{"message": {"content": json.dumps(output)}}],
            }
        )


def install_chat(monkeypatch):
    chat = RecordingChat()
    monkeypatch.setattr("videotranslate.dubbing.remote_translation.make_http", lambda _: chat)
    return chat


def drain(c, limit=20):
    worker = Worker(c.app.state.settings)
    for _ in range(limit):
        if not worker.run_once():
            break


def view(c, p, line, tag="zh-Hant"):
    rows = c.get(f"/api/projects/{p['id']}/timeline", params={"target_language": tag}).json()[
        "segments"
    ]
    return next(row for row in rows if row["id"] == line["id"])["translation"]


def test_fast_command_is_guarded_and_reuses_paid_success_after_own_publication(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    body = request_body(s, line, track)
    response = c.post(path, headers=h, json=body)
    assert response.status_code == 202, response.text
    command = response.json()
    drain(c)
    result = c.get(path + "/" + command["id"]).json()
    assert result["status"] == "review" and result["next_action"] == "translation_review"
    assert [phase for phase, _ in chat.calls] == ["draft"]
    cell = view(c, p, line)
    assert cell["text"] == "IBM 製造電腦產品。" and not cell["approved"]
    body["segments"][0]["revision"] = cell["revision"]
    repeated = c.post(path, headers=h, json=body)
    assert repeated.status_code == 202 and repeated.json()["id"] == command["id"]
    drain(c)
    assert len(chat.calls) == 1
    generic = c.post(
        f"/api/projects/{p['id']}/runs",
        headers=h,
        json={"stage": "translation_draft", "target_language": "zh-Hant", "options": {}},
    )
    assert generic.status_code == 422


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("Cinematic", ["context", "draft", "critique", "rewrite"]),
        ("Autofit", ["context", "draft", "critique", "rewrite", "shorten"]),
    ],
)
def test_refinements_have_separate_recoverable_operations_and_manual_terms_win(
    translation_project, monkeypatch, mode, expected
):
    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    base = f"/api/projects/{p['id']}"
    track = c.patch(
        base + "/language-tracks/zh-Hant",
        headers=h,
        json={"revision": track["revision"], "mode": mode},
    ).json()
    path = base + "/language-tracks/zh-Hant/translate"
    queued = c.post(path, headers=h, json=request_body(s, line, track))
    assert queued.status_code == 202, queued.text
    drain(c)
    result = c.get(path + "/" + queued.json()["id"]).json()
    assert result["status"] == "review", result
    assert [phase for phase, _ in chat.calls] == expected
    with c.app.state.session_factory() as db:
        ops = db.scalars(
            select(PrivateOperation).join(StageRun).where(StageRun.stage.like("translation_%"))
        ).all()
        assert len(ops) == len(expected) and all(op.phase == "prepared" for op in ops)
        assert len({op.run_id for op in ops}) == len(expected)
    draft_data = chat.calls[1][1]["quoted_data"]
    assert draft_data["glossary"]["IBM"] == "IBM"
    assert draft_data["context"]["supplied_summary"] == "Supplied summary"
    assert draft_data["context"]["generated_summary"] == "Generated summary"
    assert view(c, p, line)["text"] == "IBM 製造電腦。"
    if mode == "Autofit":
        assert result["suggestions"][0]["estimated"] is True
        assert result["suggestions"][0]["text"] == "IBM 造電腦。"
        assert result["suggestions"][0]["applied"] is False


def target_edit(
    c, h, p, s, line, *, revision, text="Human translation", locked=False, approved=False
):
    return c.patch(
        f"/api/projects/{p['id']}/language-tracks/zh-Hant/segments/{line['id']}",
        headers=h,
        json=guard(s, line["transcript_revision"])
        | {
            "revision": revision,
            "expected_source_text_fingerprint": line["source_text_fingerprint"],
            "text": text,
            "locked": locked,
            "approved": approved,
        },
    )


def set_mode(c, h, p, track, mode):
    response = c.patch(
        f"/api/projects/{p['id']}/language-tracks/zh-Hant",
        headers=h,
        json={"revision": track["revision"], "mode": mode},
    )
    assert response.status_code == 200
    return response.json()


def test_manual_lock_during_inference_preserved_and_repeated_default_does_not_pay(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    body = request_body(s, line, track)
    queued = c.post(path, headers=h, json=body).json()

    def edit(phase):
        assert target_edit(c, h, p, s, line, revision=0, locked=True).status_code == 200

    chat.hook = edit
    drain(c)
    assert view(c, p, line)["text"] == "Human translation"
    state = c.get(path + "/" + queued["id"]).json()
    assert state["status"] == "incomplete"
    body["segments"][0].update(revision=1, locked=True)
    repeated = c.post(path, headers=h, json=body)
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["id"] == queued["id"]
    drain(c)
    assert len(chat.calls) == 1


def test_critique_lost_response_retry_requires_ack_reuses_prior_phases(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    track = set_mode(c, h, p, track, "Cinematic")
    chat = install_chat(monkeypatch)
    chat.fail = "critique"
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    queued = c.post(path, headers=h, json=request_body(s, line, track)).json()
    drain(c)
    state = c.get(path + "/" + queued["id"]).json()
    assert state["status"] == "incomplete" and view(c, p, line)["text"] == "IBM 製造電腦產品。"
    assert state["next_action"] == "acknowledge_uncertain_submission"
    run_id = state["phases"][-1]["run_id"]
    assert c.post(f"/api/runs/{run_id}/retry", headers=h, json={}).status_code == 409
    chat.fail = None
    assert (
        c.post(
            f"/api/runs/{run_id}/retry", headers=h, json={"acknowledge_uncertain_submission": True}
        ).status_code
        == 200
    )
    drain(c)
    assert [phase for phase, _ in chat.calls] == [
        "context",
        "draft",
        "critique",
        "critique",
        "rewrite",
    ]
    assert c.get(path + "/" + queued["id"]).json()["status"] == "review"


def test_suggestion_apply_is_explicit_and_slot_edit_only_stales_suggestion(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    track = set_mode(c, h, p, track, "Autofit")
    install_chat(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    queued = c.post(path, headers=h, json=request_body(s, line, track)).json()
    drain(c)
    state = c.get(path + "/" + queued["id"]).json()
    suggestion = state["suggestions"][0]
    current = view(c, p, line)
    body = guard(s, line["transcript_revision"]) | {
        "phase_id": suggestion["phase_id"],
        "segments": [
            {
                "id": line["id"],
                "revision": current["revision"],
                "expected_source_text_fingerprint": line["source_text_fingerprint"],
                "locked": False,
                "approved": False,
            }
        ],
    }
    result = c.post(path + "/" + queued["id"] + "/apply-suggestion", headers=h, json=body)
    assert result.status_code == 200, result.text
    assert view(c, p, line)["text"] == suggestion["text"]
    assert (
        c.post(path + "/" + queued["id"] + "/apply-suggestion", headers=h, json=body).status_code
        == 409
    )


def test_unknown_rate_remains_unknown():
    from videotranslate.dubbing.remote_translation import estimate_ms

    assert estimate_ms("hello", "ldb") is None
    assert estimate_ms("مرحبا", "ar") is None
    assert estimate_ms("你好", "zh-Hant") > 0


def test_default_preserves_approved_and_force_is_audited(translation_project, monkeypatch):
    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    assert target_edit(c, h, p, s, line, revision=0, approved=True).status_code == 200
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    body = request_body(s, line, track)
    body["segments"][0].update(revision=1, approved=True)
    assert c.post(path, headers=h, json=body).status_code == 409
    assert not chat.calls
    body["force_replace"] = True
    response = c.post(path, headers=h, json=body)
    assert response.status_code == 202
    drain(c)
    cell = view(c, p, line)
    assert cell["text"] == "IBM 製造電腦產品。" and not cell["approved"]
    events = c.get(f"/api/projects/{p['id']}/events").json()
    assert "force_replace" in str(events)


@pytest.mark.parametrize("stop_phase", ["context", "draft", "critique", "rewrite", "shorten"])
def test_restart_after_private_phase_success_reuses_same_generation(
    translation_project, monkeypatch, stop_phase
):
    from datetime import timedelta

    from videotranslate.dubbing.remote_translation import handler
    from videotranslate.execution.context import RunContext
    from videotranslate.execution.service import claim_run
    from videotranslate.models.core import utcnow

    c, h, p, s, line, track = translation_project
    track = set_mode(c, h, p, track, "Autofit")
    chat = install_chat(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    queued = c.post(path, headers=h, json=request_body(s, line, track)).json()
    worker = Worker(c.app.state.settings)
    while True:
        state = c.get(path + "/" + queued["id"]).json()
        pending = next(row for row in state["phases"] if row["status"] == "queued")
        if pending["phase"] == stop_phase:
            break
        assert worker.run_once()
    sf = c.app.state.session_factory
    with sf.begin() as db:
        run = claim_run(db, "before-crash")
    context = RunContext(sf, c.app.state.storage, c.app.state.settings, run.id, run.lease_token)
    result = handler(context)  # Durable private checkpoint, crash before finish_run.
    with sf.begin() as db:
        op = db.get(PrivateOperation, result.prepared_id)
        generation = op.generation
        db.get(StageRun, run.id).lease_expires_at = utcnow() - timedelta(seconds=1)
    before = len(chat.calls)
    assert Worker(c.app.state.settings).run_once()
    assert len(chat.calls) == before
    with sf() as db:
        assert db.get(StageRun, run.id).request_key == generation
        assert db.get(StageRun, run.id).status == "succeeded"
    drain(c)
    assert [phase for phase, _ in chat.calls] == [
        "context",
        "draft",
        "critique",
        "rewrite",
        "shorten",
    ]


def test_slot_change_stales_suggestion_without_staling_meaning_and_estimates_visible(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    track = set_mode(c, h, p, track, "Autofit")
    install_chat(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    queued = c.post(path, headers=h, json=request_body(s, line, track)).json()
    drain(c)
    before = view(c, p, line)
    edited = c.patch(
        f"/api/projects/{p['id']}/segments/{line['id']}",
        headers=h,
        json=guard(s, line["transcript_revision"]) | {"revision": line["revision"], "end_ms": 1800},
    )
    assert edited.status_code == 200
    state = c.get(path + "/" + queued["id"]).json()
    assert state["suggestions"][0]["stale"]
    assert view(c, p, line)["text"] == before["text"] and not view(c, p, line)["stale"]
    assert state["estimates"][0]["provenance"] == "estimated_language_rate_v1"
    assert state["estimates"][0]["fit_guaranteed"] is False


def test_successful_cache_after_rejected_publication_can_be_explicitly_forced_without_post(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    body = request_body(s, line, track)
    c.post(path, headers=h, json=body)
    chat.hook = lambda phase: target_edit(c, h, p, s, line, revision=0)
    drain(c)
    assert len(chat.calls) == 1 and view(c, p, line)["text"] == "Human translation"
    body["segments"][0]["revision"] = 1
    body["force_replace"] = True
    chat.hook = None
    force = c.post(path, headers=h, json=body)
    assert force.status_code == 202
    drain(c)
    assert len(chat.calls) == 1
    assert view(c, p, line)["text"] == "IBM 製造電腦產品。"


def test_changed_source_uses_new_operation_and_old_wording_stays_stale(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    c.post(path, headers=h, json=request_body(s, line, track))
    drain(c)
    cell = view(c, p, line)
    edited = c.patch(
        f"/api/projects/{p['id']}/segments/{line['id']}",
        headers=h,
        json=guard(s, line["transcript_revision"]) | {"revision": 1, "text": "New source"},
    ).json()
    assert view(c, p, line)["text"] == cell["text"] and view(c, p, line)["stale"]
    body = request_body(s, edited, track)
    body["segments"][0]["revision"] = cell["revision"] + 1
    assert c.post(path, headers=h, json=body).status_code == 202
    drain(c)
    assert len(chat.calls) == 2


def test_same_wording_lock_unlock_during_refinement_still_suppresses_replacement(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    track = set_mode(c, h, p, track, "Cinematic")
    chat = install_chat(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    queued = c.post(path, headers=h, json=request_body(s, line, track)).json()

    def edit(phase):
        if phase == "rewrite":
            assert (
                target_edit(
                    c, h, p, s, line, revision=1, text="IBM 製造電腦產品。", locked=True
                ).status_code
                == 200
            )
            assert (
                target_edit(
                    c, h, p, s, line, revision=2, text="IBM 製造電腦產品。", locked=False
                ).status_code
                == 200
            )

    chat.hook = edit
    drain(c)
    assert view(c, p, line)["text"] == "IBM 製造電腦產品。"
    assert c.get(path + "/" + queued["id"]).json()["status"] == "incomplete"


def test_unrelated_row_change_does_not_block_fast_selected_batch(translation_project, monkeypatch):
    c, h, p, s, line, track = translation_project
    other = create_line(
        (c, h, p),
        s,
        "Other source",
        transcript=line["transcript_revision"],
        start_ms=500,
        end_ms=1000,
    )["segment"]
    chat = install_chat(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    queued = c.post(path, headers=h, json=request_body(s, line, track)).json()

    def edit(phase):
        result = c.patch(
            f"/api/projects/{p['id']}/segments/{other['id']}",
            headers=h,
            json=guard(s, line["transcript_revision"])
            | {"revision": 1, "text": "Unrelated correction"},
        )
        assert result.status_code == 200

    chat.hook = edit
    drain(c)
    assert c.get(path + "/" + queued["id"]).json()["status"] == "review"
    assert view(c, p, line) is not None and view(c, p, other) is None


def test_deterministic_selected_batches_partial_failure_retry_is_isolated(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    lines = [line]
    for index in range(21):
        lines.append(
            create_line(
                (c, h, p),
                s,
                f"Row {index}",
                transcript=line["transcript_revision"],
                start_ms=500,
                end_ms=1000,
            )["segment"]
        )
    chat = install_chat(monkeypatch)
    body = request_body(s, line, track)
    body["segments"] = [request_body(s, row, track)["segments"][0] for row in reversed(lines)]
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    queued = c.post(path, headers=h, json=body)
    assert queued.status_code == 202

    def fail_second(phase):
        if len(chat.calls) == 2:
            raise TimeoutError("lost batch response")

    chat.hook = fail_second
    drain(c)
    state = c.get(path + "/" + queued.json()["id"]).json()
    assert state["status"] == "incomplete" and len(state["phases"]) == 2
    assert len({row["run_id"] for row in state["phases"]}) == 2
    requested = {row["id"] for row in lines}
    returned_ids = [
        [row["id"] for row in data["quoted_data"]["segments"]] for _, data in chat.calls
    ]
    assert len(returned_ids[0]) == 20 and len(returned_ids[1]) == 2
    assert set(returned_ids[0] + returned_ids[1]) == requested
    with c.app.state.session_factory() as db:
        runs = db.scalars(select(StageRun).where(StageRun.stage == "translation_draft")).all()
        assert len({row.output_key for row in runs}) == 2
    failed = next(row for row in state["phases"] if row["status"] == "needs_review")
    chat.hook = None
    assert (
        c.post(
            f"/api/runs/{failed['run_id']}/retry",
            headers=h,
            json={"acknowledge_uncertain_submission": True},
        ).status_code
        == 200
    )
    drain(c)
    assert len(chat.calls) == 3
    assert c.get(path + "/" + queued.json()["id"]).json()["status"] == "review"


@pytest.mark.parametrize("tag", ["ja", "ar", "en-GB"])
def test_targets_are_independent_and_catalog_variants_explicit(
    translation_project, monkeypatch, tag
):
    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    base = f"/api/projects/{p['id']}"
    other = make_track(c, h, base, tag)
    zh = c.post(
        base + "/language-tracks/zh-Hant/translate", headers=h, json=request_body(s, line, track)
    ).json()
    second = c.post(
        base + f"/language-tracks/{tag}/translate", headers=h, json=request_body(s, line, other)
    ).json()
    drain(c)
    assert view(c, p, line, tag) is not None and view(c, p, line) is not None
    assert {data["target_language"] for _, data in chat.calls} == {"zh-Hant", other["tag"]}
    assert c.get(base + f"/language-tracks/{tag}/translate/" + zh["id"]).status_code == 404
    assert c.get(base + "/language-tracks/zh-Hant/translate/" + second["id"]).status_code == 404


def test_new_human_context_during_extraction_is_preserved(translation_project, monkeypatch):
    from videotranslate.models.dubbing import ContextRevision, LanguageTrack

    c, h, p, s, line, track = translation_project
    track = set_mode(c, h, p, track, "Cinematic")
    chat = install_chat(monkeypatch)
    base = f"/api/projects/{p['id']}"
    path = base + "/language-tracks/zh-Hant/translate"
    queued = c.post(path, headers=h, json=request_body(s, line, track)).json()

    def change(phase):
        result = c.patch(
            base + "/language-tracks/zh-Hant",
            headers=h,
            json={"revision": track["revision"], "summary": "Newer human context"},
        )
        assert result.status_code == 200

    chat.hook = change
    drain(c)
    with c.app.state.session_factory() as db:
        current = db.get(LanguageTrack, track["id"])
        assert db.get(ContextRevision, current.context_revision_id).summary == "Newer human context"
        assert (
            len(
                db.scalars(
                    select(ContextRevision).where(ContextRevision.provenance == "generated")
                ).all()
            )
            == 0
        )
    assert c.get(path + "/" + queued["id"]).json()["status"] == "incomplete"
    assert len(chat.calls) == 1


def test_whole_context_records_all_rows_and_oversize_rejects_before_operation(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    track = set_mode(c, h, p, track, "Cinematic")
    chat = install_chat(monkeypatch)
    other = create_line(
        (c, h, p),
        s,
        "Other context row",
        transcript=line["transcript_revision"],
        start_ms=500,
        end_ms=1000,
    )["segment"]
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    c.post(path, headers=h, json=request_body(s, line, track))
    drain(c)
    assert [r["id"] for r in chat.calls[0][1]["quoted_data"]["segments"]] == [
        line["id"],
        other["id"],
    ]
    assert [r["id"] for r in chat.calls[1][1]["quoted_data"]["segments"]] == [line["id"]]
    for _index in range(25):
        create_line(
            (c, h, p),
            s,
            "x" * 10000,
            transcript=line["transcript_revision"],
            start_ms=1100,
            end_ms=1500,
        )
    body = request_body(s, line, track)
    body["segments"][0]["revision"] = view(c, p, line)["revision"]
    rejected = c.post(path, headers=h, json=body)
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "CONTEXT_LIMIT"
    assert len(chat.calls) == 4


def test_default_after_later_manual_edit_reports_current_review_state(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    body = request_body(s, line, track)
    queued = c.post(path, headers=h, json=body).json()
    drain(c)
    assert target_edit(c, h, p, s, line, revision=1).status_code == 200
    body["segments"][0]["revision"] = 2
    repeated = c.post(path, headers=h, json=body).json()
    assert repeated["id"] == queued["id"] and repeated["status"] == "incomplete"
    assert view(c, p, line)["text"] == "Human translation" and len(chat.calls) == 1


def test_large_fast_selection_uses_batches_instead_of_whole_context_rejection(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    lines = [line]
    for _ in range(25):
        lines.append(
            create_line(
                (c, h, p),
                s,
                "x" * 10000,
                transcript=line["transcript_revision"],
                start_ms=500,
                end_ms=1000,
            )["segment"]
        )
    body = request_body(s, line, track)
    body["segments"] = [request_body(s, row, track)["segments"][0] for row in lines]
    response = c.post(
        f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate", headers=h, json=body
    )
    assert response.status_code == 202, response.text
    drain(c)
    assert len(chat.calls) > 1
    assert sum(len(data["quoted_data"]["segments"]) for _, data in chat.calls) == len(lines)


@pytest.mark.parametrize("corruption", ["generation", "payload", "facts"])
def test_invalid_private_cache_is_not_reused_by_forced_review(
    translation_project, monkeypatch, corruption
):
    from videotranslate.execution.prepared import current_operation

    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    body = request_body(s, line, track)
    queued = c.post(path, headers=h, json=body).json()
    drain(c)
    run_id = c.get(path + "/" + queued["id"]).json()["phases"][0]["run_id"]
    with c.app.state.session_factory.begin() as db:
        run = db.get(StageRun, run_id)
        if corruption == "generation":
            run.request_key = "new-current-generation"
        elif corruption == "facts":
            current_operation(db, run).public_facts = {"dialogue": "private"}
        else:
            op = current_operation(db, run)
            op.prepared_payload = {
                "output": {"segments": {}, "metadata": {}},
                "input_fingerprint": op.prepared_payload["input_fingerprint"],
            }
    body["segments"][0]["revision"] = view(c, p, line)["revision"]
    body["force_replace"] = True
    assert c.post(path, headers=h, json=body).status_code == 202
    drain(c)
    assert len(chat.calls) == 2


def test_provider_configuration_rechecked_before_submission(translation_project, monkeypatch):
    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    assert c.post(path, headers=h, json=request_body(s, line, track)).status_code == 202
    # Administrator removes a host after command capture, before worker submission.
    c.app.state.settings = c.app.state.settings.model_copy(update={"provider_allowed_hosts": ""})
    chat.allowed_hosts = set()
    drain(c)
    assert not chat.calls
    with c.app.state.session_factory() as db:
        run = db.scalar(select(StageRun).where(StageRun.stage == "translation_draft"))
        assert run.safe_error["code"] == "CONFIGURATION" and run.remote_state == "not_submitted"


def test_known_unsupported_provider_keeps_manual_path_available(translation_project, monkeypatch):
    from videotranslate.models.providers import ProviderConnection

    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    with c.app.state.session_factory.begin() as db:
        config = db.scalar(
            select(ProviderConnection).where(ProviderConnection.slot == "translation")
        )
        config.check_state = {
            "capabilities": {"language_support": "unsupported", "supported_languages": ["en"]}
        }
    response = c.post(
        f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate",
        headers=h,
        json=request_body(s, line, track),
    )
    assert (
        response.status_code == 422 and response.json()["error"]["code"] == "UNSUPPORTED_LANGUAGE"
    )
    assert target_edit(c, h, p, s, line, revision=0).status_code == 200
    assert not chat.calls


def test_immutable_connection_revision_change_suppresses_publication(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    queued = c.post(path, headers=h, json=request_body(s, line, track)).json()

    def rotate(phase):
        result = c.put(
            "/api/providers/translation",
            headers=h,
            json={
                "revision": 1,
                "adapter": "openai_compatible",
                "endpoint": "https://translator.example/v1",
                "model": "test-model",
                "credential_ref": None,
            },
        )
        assert result.status_code == 200

    chat.hook = rotate
    drain(c)
    assert view(c, p, line) is None
    assert c.get(path + "/" + queued["id"]).json()["status"] == "incomplete"


def test_autofit_forced_review_reuses_all_same_actual_phase_inputs(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    track = set_mode(c, h, p, track, "Autofit")
    chat = install_chat(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    body = request_body(s, line, track)
    queued = c.post(path, headers=h, json=body).json()
    drain(c)
    current = view(c, p, line)
    assert target_edit(c, h, p, s, line, revision=current["revision"]).status_code == 200
    body["segments"][0]["revision"] = current["revision"] + 1
    body["force_replace"] = True
    forced = c.post(path, headers=h, json=body)
    assert forced.status_code == 202, forced.text
    drain(c)
    assert len(chat.calls) == 5
    assert c.get(path + "/" + forced.json()["id"]).json()["status"] == "review"
    assert c.get(path + "/" + queued["id"]).json()["suggestions"][0]["stale"]


def test_credential_removed_after_command_does_not_cross_submission_boundary(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    assert (
        c.put(
            "/api/credentials/translation",
            headers=h,
            json={"revision": 0, "token": "ephemeral-test-token"},
        ).status_code
        == 200
    )
    assert (
        c.put(
            "/api/providers/translation",
            headers=h,
            json={
                "revision": 1,
                "adapter": "openai_compatible",
                "endpoint": "https://translator.example/v1",
                "model": "test-model",
                "credential_ref": "translation",
            },
        ).status_code
        == 200
    )
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    queued = c.post(path, headers=h, json=request_body(s, line, track)).json()
    assert (
        c.put(
            "/api/credentials/translation", headers=h, json={"revision": 1, "clear": True}
        ).status_code
        == 200
    )
    drain(c)
    with c.app.state.session_factory() as db:
        run = db.get(StageRun, queued["phases"][0]["run_id"])
        assert run.remote_state == "not_submitted"
        assert run.safe_error["code"] in {"CONFIGURATION", "AUTHENTICATION"}
    assert not chat.calls


def test_batch_run_scope_does_not_claim_a_phase_uuid_is_a_source_segment(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    install_chat(monkeypatch)
    response = c.post(
        f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate",
        headers=h,
        json=request_body(s, line, track),
    ).json()
    with c.app.state.session_factory() as db:
        run = db.get(StageRun, response["phases"][0]["run_id"])
        assert run.segment_id is None
        assert run.scope_key.endswith(response["phases"][0]["id"])


def test_foreign_command_phase_lineage_never_submits(translation_project, monkeypatch):
    from videotranslate.models.translation import TranslationPhase

    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    base = f"/api/projects/{p['id']}"
    first = c.post(
        base + "/language-tracks/zh-Hant/translate", headers=h, json=request_body(s, line, track)
    ).json()
    other = make_track(c, h, base, "ja")
    second = c.post(
        base + "/language-tracks/ja/translate", headers=h, json=request_body(s, line, other)
    ).json()
    with c.app.state.session_factory.begin() as db:
        db.get(TranslationPhase, first["phases"][0]["id"]).parent_phase_id = second["phases"][0][
            "id"
        ]
    drain(c)
    assert [data["target_language"] for _, data in chat.calls] == ["ja"]
    assert (
        c.get(base + "/language-tracks/zh-Hant/translate/" + first["id"]).json()["status"]
        == "incomplete"
    )


def test_equal_wording_rewrite_keeps_distinct_phase_revision_history(
    translation_project, monkeypatch
):
    from videotranslate.models.dubbing import TranslationRevision

    c, h, p, s, line, track = translation_project
    track = set_mode(c, h, p, track, "Cinematic")
    chat = install_chat(monkeypatch)
    original = chat.post_json

    def same_wording(url, body, **kwargs):
        response = json.loads(original(url, body, **kwargs))
        if chat.calls[-1][0] == "rewrite":
            output = json.loads(response["choices"][0]["message"]["content"])
            draft = chat.calls[-1][1]["quoted_data"]["draft"]
            output["segments"] = [{"id": key, "text": value} for key, value in draft.items()]
            response["choices"][0]["message"]["content"] = json.dumps(output)
        return json.dumps(response)

    chat.post_json = same_wording
    c.post(
        f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate",
        headers=h,
        json=request_body(s, line, track),
    )
    drain(c)
    with c.app.state.session_factory() as db:
        rows = db.scalars(
            select(TranslationRevision)
            .where(TranslationRevision.segment_id == line["id"])
            .order_by(TranslationRevision.created_at)
        ).all()
        assert [row.provenance for row in rows] == ["cloud_draft", "cloud_rewrite"]
        assert rows[1].parent_revision_id == rows[0].id and rows[1].text == rows[0].text


def test_manual_same_wording_save_during_rewrite_protects_human_revision(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    track = set_mode(c, h, p, track, "Cinematic")
    chat = install_chat(monkeypatch)
    saved = []

    def save(phase):
        if phase == "rewrite":
            result = target_edit(c, h, p, s, line, revision=1, text="IBM 製造電腦產品。")
            saved.append(result.json())

    chat.hook = save
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    queued = c.post(path, headers=h, json=request_body(s, line, track)).json()
    drain(c)
    assert saved and saved[0]["revision"] == 2
    assert view(c, p, line)["text"] == "IBM 製造電腦產品。"
    assert c.get(path + "/" + queued["id"]).json()["status"] == "incomplete"


@pytest.mark.parametrize("fail", [None, "draft"])
def test_translation_http_transport_is_closed_after_success_or_failure(
    translation_project, monkeypatch, fail
):
    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    chat.fail = fail
    c.post(
        f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate",
        headers=h,
        json=request_body(s, line, track),
    )
    drain(c)
    assert chat.closed == 1


def test_uncertain_fast_row_does_not_freeze_a_disjoint_fast_command(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    other = create_line(
        (c, h, p),
        s,
        "Independent row",
        transcript=line["transcript_revision"],
        start_ms=500,
        end_ms=1000,
    )["segment"]
    chat = install_chat(monkeypatch)
    chat.fail = "draft"
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    first = c.post(path, headers=h, json=request_body(s, line, track)).json()
    drain(c)
    assert c.get(path + "/" + first["id"]).json()["status"] == "incomplete"
    chat.fail = None
    second = c.post(path, headers=h, json=request_body(s, other, track))
    assert second.status_code == 202, second.text
    drain(c)
    assert view(c, p, other) is not None and view(c, p, line) is None
    assert len(chat.calls) == 2


def test_uncertain_overlap_requires_ack_but_other_target_can_proceed(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    chat.fail = "draft"
    base = f"/api/projects/{p['id']}"
    path = base + "/language-tracks/zh-Hant/translate"
    first = c.post(path, headers=h, json=request_body(s, line, track)).json()
    drain(c)
    repeated = c.post(path, headers=h, json=request_body(s, line, track)).json()
    assert repeated["id"] == first["id"]
    forced = c.post(path, headers=h, json=request_body(s, line, track, force_replace=True))
    assert forced.status_code == 409 and forced.json()["error"]["code"] == "SUBMISSION_UNCERTAIN"
    ja = make_track(c, h, base, "ja")
    chat.fail = None
    assert (
        c.post(
            base + "/language-tracks/ja/translate", headers=h, json=request_body(s, line, ja)
        ).status_code
        == 202
    )
    drain(c)
    assert view(c, p, line, "ja") is not None and len(chat.calls) == 2


def test_same_unresolved_shared_context_blocks_only_duplicate_context_work(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    other = create_line(
        (c, h, p),
        s,
        "Independent selected row",
        transcript=line["transcript_revision"],
        start_ms=500,
        end_ms=1000,
    )["segment"]
    track = set_mode(c, h, p, track, "Cinematic")
    chat = install_chat(monkeypatch)
    chat.fail = "context"
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    c.post(path, headers=h, json=request_body(s, line, track))
    drain(c)
    duplicate_context = c.post(path, headers=h, json=request_body(s, other, track))
    assert duplicate_context.status_code == 409
    assert duplicate_context.json()["error"]["code"] == "SUBMISSION_UNCERTAIN"
    assert len(chat.calls) == 1
    track = set_mode(c, h, p, track, "Fast")
    chat.fail = None
    independent_fast = c.post(path, headers=h, json=request_body(s, other, track))
    assert independent_fast.status_code == 202, independent_fast.text
    drain(c)
    assert view(c, p, other) is not None and view(c, p, line) is None
    assert [phase for phase, _ in chat.calls] == ["context", "draft"]


def test_queued_overlap_and_shared_context_are_reserved_without_freezing_independent_fast(
    translation_project, monkeypatch
):
    c, h, p, s, line, track = translation_project
    other = create_line(
        (c, h, p),
        s,
        "Independent queued row",
        transcript=line["transcript_revision"],
        start_ms=500,
        end_ms=1000,
    )["segment"]
    chat = install_chat(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    c.post(path, headers=h, json=request_body(s, line, track))
    overlap = c.post(path, headers=h, json=request_body(s, line, track, force_replace=True))
    assert overlap.status_code == 409 and overlap.json()["error"]["code"] == "RUN_ACTIVE"
    assert c.post(path, headers=h, json=request_body(s, other, track)).status_code == 202
    drain(c)
    assert len(chat.calls) == 2
    track = set_mode(c, h, p, track, "Cinematic")
    first_body, second_body = request_body(s, line, track), request_body(s, other, track)
    first_body["segments"][0]["revision"] = view(c, p, line)["revision"]
    second_body["segments"][0]["revision"] = view(c, p, other)["revision"]
    assert c.post(path, headers=h, json=first_body).status_code == 202
    shared = c.post(path, headers=h, json=second_body)
    assert shared.status_code == 409 and shared.json()["error"]["code"] == "RUN_ACTIVE"


def test_live_running_submission_conflict_is_active_not_uncertain(translation_project, monkeypatch):
    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    conflicts = []

    def overlap(phase):
        conflicts.append(
            c.post(path, headers=h, json=request_body(s, line, track, force_replace=True))
        )

    chat.hook = overlap
    first = c.post(path, headers=h, json=request_body(s, line, track)).json()
    drain(c)
    assert len(conflicts) == 1 and conflicts[0].status_code == 409
    assert conflicts[0].json()["error"]["code"] == "RUN_ACTIVE"
    assert c.get(path + "/" + first["id"]).json()["status"] == "review"


@pytest.mark.parametrize("changed_input", ["source", "context", "glossary"])
def test_obsolete_uncertain_phase_can_be_acknowledged_locally_before_fresh_guarded_command(
    translation_project, monkeypatch, changed_input
):
    from videotranslate.execution.prepared import current_operation

    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    chat.fail = "draft"
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    first = c.post(path, headers=h, json=request_body(s, line, track)).json()
    drain(c)
    run_id = first["phases"][0]["run_id"]
    if changed_input == "source":
        edited = c.patch(
            f"/api/projects/{p['id']}/segments/{line['id']}",
            headers=h,
            json=guard(s, line["transcript_revision"])
            | {"revision": line["revision"], "text": "Corrected current source"},
        )
        assert edited.status_code == 200
        new_body = request_body(s, edited.json(), track)
    else:
        edited = c.patch(
            f"/api/projects/{p['id']}/language-tracks/zh-Hant",
            headers=h,
            json={"revision": track["revision"]}
            | (
                {"summary": "New supplied context"}
                if changed_input == "context"
                else {"glossary": {"IBM": "International Business Machines"}}
            ),
        )
        assert edited.status_code == 200
        new_body = request_body(s, line, edited.json())
    assert c.post(path, headers=h, json=new_body).status_code == 409
    assert c.post(f"/api/runs/{run_id}/retry", headers=h, json={}).status_code == 409
    with c.app.state.session_factory() as db:
        old = current_operation(db, db.get(StageRun, run_id))
        old_id, generation = old.id, old.generation
    acknowledged = c.post(
        f"/api/runs/{run_id}/retry", headers=h, json={"acknowledge_uncertain_submission": True}
    )
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["status"] == "stale"
    assert c.get(path + "/" + first["id"]).json()["next_action"] == "review_translation_changes"
    assert len(chat.calls) == 1
    with c.app.state.session_factory() as db:
        old_run = db.get(StageRun, run_id)
        assert current_operation(db, old_run) is None
        from videotranslate.models.execution import ProjectEvent

        events = db.scalars(
            select(ProjectEvent).where(
                ProjectEvent.run_id == run_id, ProjectEvent.kind == "run.uncertainty_acknowledged"
            )
        ).all()
        assert len(events) == 1 and events[0].facts == {"recovery": "retire_obsolete_generation"}
        old = db.get(PrivateOperation, old_id)
        assert old.generation == generation and old.phase == "submitting"
        assert old.request_payload["segments"][0]["text"] == line["text"]
        assert old.request_payload["context"] == {"supplied_summary": "Supplied summary"}
        assert old.request_payload["glossary"] == {"IBM": "IBM"}
    chat.fail = None
    fresh = c.post(path, headers=h, json=new_body)
    assert fresh.status_code == 202, fresh.text
    assert fresh.json()["id"] != first["id"]
    drain(c)
    assert len(chat.calls) == 2
    assert c.get(path + "/" + fresh.json()["id"]).json()["status"] == "review"


def test_uncertain_manual_publication_change_keeps_normal_acknowledged_retry_semantics(
    translation_project, monkeypatch
):
    from videotranslate.models.execution import ProjectEvent

    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    chat.fail = "draft"
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    first = c.post(path, headers=h, json=request_body(s, line, track)).json()
    drain(c)
    run_id = first["phases"][0]["run_id"]
    assert target_edit(c, h, p, s, line, revision=0).status_code == 200
    assert c.post(f"/api/runs/{run_id}/retry", headers=h, json={}).status_code == 409
    acknowledged = c.post(
        f"/api/runs/{run_id}/retry", headers=h, json={"acknowledge_uncertain_submission": True}
    )
    assert acknowledged.status_code == 200 and acknowledged.json()["status"] == "queued"
    with c.app.state.session_factory() as db:
        assert not db.scalars(
            select(ProjectEvent).where(
                ProjectEvent.run_id == run_id, ProjectEvent.kind == "run.uncertainty_acknowledged"
            )
        ).all()
    chat.fail = None
    drain(c)
    assert len(chat.calls) == 1 and view(c, p, line)["text"] == "Human translation"


def test_translation_commands_are_isolated_by_workspace_and_project(
    translation_project, client_factory, register, monkeypatch
):
    c, h, p, s, line, track = translation_project
    chat = install_chat(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    body = request_body(s, line, track)
    first = c.post(path, headers=h, json=body).json()
    foreign = client_factory(database_url=c.app.state.settings.database_url.get_secret_value())
    auth = register(foreign, "translation-other@example.com")
    foreign_headers = {"X-CSRF-Token": auth["csrf_token"]}
    assert foreign.get(path + "/" + first["id"]).status_code == 404
    assert foreign.post(path, headers=foreign_headers, json=body).status_code == 404
    other_project = c.post("/api/projects", headers=h, json={"name": "Other owned project"}).json()
    other_base = f"/api/projects/{other_project['id']}"
    make_track(c, h, other_base, "zh-Hant")
    assert (
        c.get(other_base + "/language-tracks/zh-Hant/translate/" + first["id"]).status_code == 404
    )
    assert (
        c.post(other_base + "/language-tracks/zh-Hant/translate", headers=h, json=body).status_code
        == 409
    )
    assert not chat.calls
    drain(c)
    assert len(chat.calls) == 1
