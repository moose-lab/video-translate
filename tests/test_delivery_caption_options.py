"""Optional caption choices preserve old command capture and reject executable inputs."""

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
