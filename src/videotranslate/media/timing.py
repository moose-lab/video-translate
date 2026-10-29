"""Common demuxer origin and logical duration for the supported media containers."""

import math


def _clock(value):
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def timeline_bounds(data):
    """Mirror FFmpeg -copyts -start_at_zero, without subtracting MP4 duration twice.

    Matroska/WebM DURATION tags and format duration report the timeline end for
    offset files; MOV/MP4, AVI and audio demuxers report elapsed duration. Stream
    end tags disambiguate nonzero Matroska rather than guessing from magnitude.
    """
    info = data["format"]
    origin, duration = float(info.get("start_time", 0)), float(info["duration"])
    if not math.isfinite(origin) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid common timeline")
    formats = set(info.get("format_name", "").split(","))
    if formats.intersection({"matroska", "webm"}) and origin != 0:
        ends = []
        for stream in data["streams"]:
            tag = stream.get("tags", {}).get("DURATION")
            if tag:
                ends.append(_clock(tag))
            elif stream.get("duration") is not None:
                ends.append(float(stream.get("start_time", origin)) + float(stream["duration"]))
        if (
            not ends
            or any(not math.isfinite(end) for end in ends)
            or abs(max(ends) - duration) > 0.1
        ):
            raise ValueError("Ambiguous container timeline")
        duration -= origin
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid logical duration")
    return origin, duration
