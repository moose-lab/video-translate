"""Optional caption choices preserve old command capture and reject executable inputs."""
# ruff: noqa: F811

import pytest
from pydantic import ValidationError

from videotranslate.dubbing.delivery_contracts import DeliveryCreate
from videotranslate.dubbing.pipeline_contracts import DeliveryOptions


def request(**extra):
    return dict(
        fit_plan_id="a",
        expected_fit_run_id="b",
        purpose="original_only",
        frame_rate=dict(numerator=25, denominator=1),
        background_gain=1.0,
        voice_gain=1.0,
        include_original_comparison=True,
        default_audio_track="original",
        captions="sidecar",
        **extra,
    )


def test_optional_caption_options_and_old_choices():
    old = request()
    assert DeliveryCreate.model_validate(old).model_dump(exclude_none=True) == old
    values = dict(
        formats=["ass"],
        burn_in=True,
        track="bilingual",
        target_track="zh-Hant",
        font_profile="auto",
        font_size=42,
        style="outlined",
        layout_policy="unicode_wrap_v2",
    )
    body = DeliveryCreate.model_validate(request(caption_options=values))
    assert body.caption_options.model_dump() == values
    assert (
        DeliveryOptions.model_validate(dict(caption_options=values)).caption_options
        == body.caption_options
    )


@pytest.mark.parametrize(
    "options",
    [
        dict(formats=["ass", "ass"]),
        dict(formats=["exe"]),
        dict(font_profile="/tmp/font.ttf"),
        dict(font_size=97),
        dict(style="{\\pos(0,0)}"),
        dict(track="target"),
        dict(track="source", target_track="zh"),
        dict(formats=[], burn_in=False),
        dict(font_path="/tmp/font"),
    ],
)
def test_caption_options_are_bounded_and_server_authored(options):
    with pytest.raises(ValidationError):
        DeliveryCreate.model_validate(request(caption_options=options))


from test_translation_operations import translation_project  # noqa: E402,F401


def test_pipeline_without_caption_options_keeps_legacy_signature(translation_project):
    from sqlalchemy import select

    from videotranslate.dubbing.pipeline_contracts import PipelineStart
    from videotranslate.execution.inputs import fingerprint
    from videotranslate.models.pipeline import PipelineWorkflow

    fixture = translation_project
    c, h, project, selection, _, track = fixture
    prefix = f"/api/projects/{project['id']}"
    timeline = c.get(prefix + "/timeline").json()
    payload = dict(
        expected_editor_fingerprint=timeline["editor_fingerprint"],
        target_track_ids=[track["id"]],
        delivery_track_ids=[track["id"]],
    )
    response = c.post(prefix + "/pipeline", headers=h, json=payload)
    assert response.status_code == 202, response.text
    legacy = PipelineStart.model_validate(payload).model_dump()
    del legacy["delivery_options"]["caption_options"]
    with c.app.state.session_factory() as db:
        workflow = db.scalar(select(PipelineWorkflow))
        assert workflow.signature == fingerprint(legacy | dict(selection_id=workflow.selection_id))
        assert "caption_options" not in workflow.delivery_options
        assert workflow.delivery_options["default_audio_track"] is None
    assert (
        c.post(prefix + "/pipeline", headers=h, json=payload).json()["id"] == response.json()["id"]
    )


def test_new_caption_requests_capture_unicode_layout_version_without_changing_legacy_absence():
    assert "caption_options" not in DeliveryCreate.model_validate(request()).model_dump(
        exclude_none=True
    )
    value = DeliveryCreate.model_validate(request(caption_options=dict(formats=["ass"])))
    assert (
        value.model_dump(exclude_none=True)["caption_options"]["layout_policy"] == "unicode_wrap_v2"
    )
    with pytest.raises(ValidationError):
        DeliveryCreate.model_validate(request(caption_options=dict(layout_policy="legacy_clipped")))
