"""Current mapped captions and actual fixed-family font proofs, outside SQL."""

from ..execution.contracts import FailureCode, StageFailure
from ..execution.inputs import fingerprint
from ..media.delivery_captions import mapped_cues
from ..media.subtitle_fonts import FontCoverageError, characters, select_fonts


class CaptionFailure(StageFailure):
    def __init__(self, failure):
        super().__init__(FailureCode.CONFIGURATION, review=True)
        self.issue, self.missing = failure.code, list(failure.missing)

    def public(self):
        return dict(super().public(), issue=self.issue, missing=self.missing)


def groups(snapshot, plan):
    return mapped_cues(plan, snapshot["cues"], snapshot["parent_snapshot"]["tracks"])


def burn_cues(grouped, options):
    if options["track"] == "source":
        return grouped["source"]
    target = grouped[options["target_track"]]
    return (
        sorted(grouped["source"] + target, key=lambda row: (row["start_ms"], row["id"]))
        if options["track"] == "bilingual"
        else target
    )


def needed(choices):
    options = choices.get("caption_options")
    return bool(options and (options["burn_in"] or "ass" in options["formats"]))


def preflight(snapshot, plan, budget):
    """Select only measured covering faces; no paths in immutable/public proof."""
    options = snapshot["choices"]["caption_options"]
    grouped = groups(snapshot, plan)
    selected = (
        [row for rows in grouped.values() for row in rows] if "ass" in options["formats"] else []
    )
    if options["burn_in"]:
        selected += burn_cues(grouped, options)
    text = "\n".join(row["text"] for row in selected)
    try:
        if options["burn_in"] and not burn_cues(grouped, options):
            raise FontCoverageError("CAPTION_TRACK_EMPTY")
        fonts = select_fonts(text, profile=options["font_profile"], budget=budget)
    except FontCoverageError as failure:
        raise CaptionFailure(failure) from None
    wanted = characters(text)
    proof = dict(
        policy="mapped_current_font_faces_v1",
        input_manifest_sha256=fingerprint(snapshot),
        cue_manifest_sha256=fingerprint(grouped),
        glyphs_sha256=fingerprint(sorted(wanted)),
        glyph_count=len(wanted),
        fonts=[
            dict(
                font.facts(),
                glyphs_sha256=fingerprint(sorted(font.covered & wanted)),
                glyph_count=len(font.covered & wanted),
            )
            for font in fonts
        ],
        options=options,
    )
    return grouped, fonts, proof


def validate_capture(payload, snapshot, plan):
    """Re-derive exact cue IDs/timing/text proofs, never trust re-hashed JSON alone."""
    import hashlib
    import html

    options = snapshot["choices"].get("caption_options")
    if not options:
        return
    grouped = groups(snapshot, plan)
    proof = payload.get("caption_proof")
    if needed(snapshot["choices"]):
        selected = (
            [row for rows in grouped.values() for row in rows]
            if "ass" in options["formats"]
            else []
        )
        if options["burn_in"]:
            selected += burn_cues(grouped, options)
        wanted = characters("\n".join(row["text"] for row in selected))
        if (
            proof["cue_manifest_sha256"] != fingerprint(grouped)
            or proof["glyphs_sha256"] != fingerprint(sorted(wanted))
            or proof["glyph_count"] != len(wanted)
        ):
            raise ValueError("Caption proof differs from current mapped cues")
    for entry in payload["phases"].get("export", {}).get("outputs", []):
        if entry["kind"] == "delivery_burned_picture":
            if entry["metadata"]["cue_count"] != len(burn_cues(grouped, options)):
                raise ValueError("Burned cue coverage changed")
        if entry["format"] not in {"ass", "srt", "vtt"}:
            continue
        track = next(
            (a["track"] for a in payload["artifacts"] if a["object_id"] == entry["object_id"]), None
        )
        if track not in grouped:
            raise ValueError("Unknown caption target")
        rows = grouped[track]
        rows = (
            [dict(row, text=html.escape(row["text"], quote=False)) for row in rows]
            if entry["format"] != "ass"
            else rows
        )
        metadata = entry["metadata"]
        expected = dict(
            cue_policy="target_actual_declared_speech_source_mapped_cue_v1",
            clock="selection_relative_shared_map",
            cue_ids=[row["id"] for row in rows],
            cue_count=len(rows),
            cue_manifest_sha256=fingerprint(rows)
            if entry["format"] == "ass"
            else hashlib.sha256(repr(rows).encode()).hexdigest(),
            first_cue_ms=min((r["start_ms"] for r in rows), default=None),
            last_cue_ms=max((r["end_ms"] for r in rows), default=None),
            format=entry["format"],
        )
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise ValueError("Caption artifact differs from captured cue identity")
        if entry["format"] == "ass":
            picture = payload["phases"]["render"]["outputs"][0]["metadata"]
            expected = dict(
                width=picture["width"],
                height=picture["height"],
                font_size=options["font_size"],
                family=proof["fonts"][0]["family"],
                clock_policy="outward_centisecond_v1",
                text_policy="literal_braces_backslash_word_joiner_v1",
            )
            if any(metadata.get(key) != value for key, value in expected.items()):
                raise ValueError("ASS style or quantization changed")
