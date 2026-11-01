"""Literal ASS sidecars and measured libass burn-in; no inference or shell text."""

import hashlib
import json
import shutil
import tempfile
import unicodedata
from pathlib import Path

from .delivery_export import ExportedFile
from .float_audio import digest, invalid
from .subtitle_fonts import FAMILIES, FontCoverageError


def ass_time(ms, *, end=False):
    if type(ms) is not int or ms < 0:
        raise invalid()
    ticks = (ms + 9 if end else ms) // 10
    hours, ticks = divmod(ticks, 360000)
    minutes, ticks = divmod(ticks, 6000)
    seconds, ticks = divmod(ticks, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{ticks:02}"


def literal(text):
    # libass 0.17.3 ass_get_next_char handles escaped braces, but has no literal
    # backslash escape. WORD JOINER stops an input '\\N' becoming a line break
    # while remaining invisible; inserted ASS line breaks are added afterwards.
    return (
        text.replace("\\", "\\\u2060")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\t", " ")
        .replace("\n", r"\N")
    )


def literal_font_runs(text, fonts):
    """Do not rely on libass choosing a working fallback from fontsdir.

    Font providers can choose a missing-glyph box even when a loaded secondary
    font has the character. Server-authored, fixed-family runs choose the exact
    family whose measured charset contains each visible character.
    """
    result, active = [], None
    allowed = {value for names in FAMILIES.values() for value in names}
    for char in text.replace("\r\n", "\n").replace("\r", "\n"):
        point = ord(char)
        invisible = (
            char.isspace()
            or unicodedata.category(char) in {"Cf", "Cc"}
            or 0xFE00 <= point <= 0xFE0F
            or 0xE0100 <= point <= 0xE01EF
        )
        font = (
            (active or fonts[0])
            if invisible
            else next((font for font in fonts if point in font.covered), None)
        )
        if font is None or font.family not in allowed:
            raise FontCoverageError("FONT_GLYPHS_MISSING", [f"U+{point:04X}"])
        if font != active:
            result.append("{\\fn" + font.family + "}")
            active = font
        result.append(literal(char))
    return "".join(result)


def ass_file(cues, destination, *, width, height, family, font_size=42, fonts=None):
    destination = Path(destination)
    if (
        destination.exists()
        or type(width) is not int
        or type(height) is not int
        or not 16 <= width <= 16384
        or not 16 <= height <= 16384
    ):
        raise invalid()
    if family not in {value for names in FAMILIES.values() for value in names}:
        raise invalid()
    if type(font_size) is not int or not 12 <= font_size <= 96 or not 0 < len(cues) <= 1000:
        raise invalid()
    size, margin = max(12, round(font_size * height / 720)), max(8, round(height * 0.04))
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{family},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,1.5,0,2,{margin},{margin},{margin},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines, seen = [], set()
    for cue in cues:
        if (
            set(cue) != {"id", "start_ms", "end_ms", "text"}
            or cue["id"] in seen
            or type(cue["start_ms"]) is not int
            or type(cue["end_ms"]) is not int
            or not 0 <= cue["start_ms"] < cue["end_ms"] <= 57600000
            or not isinstance(cue["text"], str)
            or not cue["text"].strip()
            or any(ord(c) < 32 and c not in "\r\n\t" for c in cue["text"])
        ):
            raise invalid()
        seen.add(cue["id"])
        text = literal_font_runs(cue["text"], fonts) if fonts else literal(cue["text"])
        lines.append(
            f"Dialogue: 0,{ass_time(cue['start_ms'])},{ass_time(cue['end_ms'], end=True)},Default,,0,0,0,,{text}\n"
        )
    data = (header + "".join(lines)).encode("utf-8")
    if len(data) > 2 * 1024 * 1024:
        raise invalid()
    destination.write_bytes(data)
    return ExportedFile(
        destination,
        dict(
            sha256=hashlib.sha256(data).hexdigest(),
            byte_size=len(data),
            cue_count=len(cues),
            clock_policy="outward_centisecond_v1",
            text_policy="literal_braces_backslash_word_joiner_v1",
            format="ass",
            width=width,
            height=height,
            family=family,
            font_size=font_size,
        ),
    )


def burn_in(video, cues, destination, *, fonts, width, height, budget, font_size=42):
    destination = Path(destination)
    if destination.exists() or not fonts:
        raise invalid()
    source = json.loads(
        budget.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_streams",
                "-count_frames",
                "-of",
                "json",
                str(video),
            ]
        )
    )["streams"]
    if (
        len(source) != 1
        or source[0].get("width") != width
        or source[0].get("height") != height
        or not 0 < int(source[0].get("nb_read_frames", 0)) <= budget.limits.max_video_frames
    ):
        raise invalid()
    with tempfile.TemporaryDirectory(prefix="vt-subs-", dir=destination.parent) as d:
        root = Path(d)
        fontsdir = root / "fonts"
        fontsdir.mkdir()
        for index, font in enumerate(fonts):
            budget.preflight(font.path.stat().st_size, output=False)
            target = fontsdir / (str(index) + font.path.suffix)
            shutil.copyfile(font.path, target)
            if digest(target, budget.check) != font.sha256:
                raise invalid()
        subtitle = ass_file(
            cues,
            root / "captions.ass",
            width=width,
            height=height,
            family=fonts[0].family,
            font_size=font_size,
            fonts=fonts,
        )

        # Paths come only from a server-owned tempfile and are escaped for the
        # FFmpeg filter grammar; dialogue lives in UTF-8 ASS, never filter text.
        def quote(path):
            return (
                "'"
                + str(path).replace("\\", "\\\\").replace("'", "'\\''").replace(":", "\\:")
                + "'"
            )

        budget.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-i",
                str(video),
                "-map",
                "0:v:0",
                "-an",
                "-sn",
                "-dn",
                "-vf",
                "subtitles=filename=" + quote(subtitle.path) + ":fontsdir=" + quote(fontsdir),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-threads",
                "2",
                "-pix_fmt",
                "yuv420p",
                "-fps_mode",
                "passthrough",
                "-movflags",
                "+faststart",
                str(destination),
            ],
            output=destination,
        )
        info = json.loads(
            budget.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-count_frames",
                    "-show_format",
                    "-of",
                    "json",
                    str(destination),
                ]
            )
        )
        streams = info["streams"]
        if (
            len(streams) != 1
            or streams[0].get("codec_name") != "h264"
            or streams[0].get("pix_fmt") != "yuv420p"
            or streams[0].get("width") != width
            or streams[0].get("height") != height
            or streams[0].get("nb_read_frames") != source[0]["nb_read_frames"]
            or streams[0].get("avg_frame_rate") != source[0]["avg_frame_rate"]
            or abs(float(streams[0]["duration"]) - float(source[0]["duration"])) > 0.001
        ):
            raise invalid()
        budget.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-i",
                str(destination),
                "-f",
                "null",
                "-",
            ]
        )
        return ExportedFile(
            destination,
            dict(
                sha256=digest(destination, budget.check),
                byte_size=destination.stat().st_size,
                source_video_sha256=digest(video, budget.check),
                width=width,
                height=height,
                codec="h264",
                container="mp4",
                frame_count=int(streams[0]["nb_read_frames"]),
                frame_rate=streams[0]["avg_frame_rate"],
                duration_ms=round(float(info["format"]["duration"]) * 1000),
                fonts=[font.facts() for font in fonts],
                cue_count=len(cues),
                ass_sha256=subtitle.metadata()["sha256"],
                policy="libass_literal_font_coverage_v1",
            ),
        )
