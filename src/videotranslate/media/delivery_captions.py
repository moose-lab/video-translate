"""UTF-8 sidecars on the shared selection-relative map, preserving overlaps."""

import hashlib
import html
import re

from .delivery_export import ExportedFile
from .fit_plan import map_time


def timestamp(value, separator):
    value = round(value)
    hours, value = divmod(value, 3600000)
    minutes, value = divmod(value, 60000)
    seconds, millis = divmod(value, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}{separator}{millis:03}"


def mapped_cues(plan, cues, tracks):
    placements = {(p.track_key, p.segment_key): p for p in plan.placements}
    source = {}
    grouped = {t["tag"]: [] for t in tracks}
    tags = {t["id"]: t["tag"] for t in tracks}
    for cue in cues:
        source[cue["segment_id"]] = dict(
            id="source:" + cue["segment_id"],
            start=map_time(plan, cue["start_ms"]),
            end=map_time(plan, cue["end_ms"]),
            text=cue["source_text"],
        )
        if cue["included"]:
            placement = placements[cue["track_id"], cue["segment_id"]]
            grouped[tags[cue["track_id"]]].append(
                dict(
                    id=tags[cue["track_id"]] + ":" + cue["segment_id"],
                    start=placement.output_start_ms,
                    end=placement.voice_end_ms,
                    text=cue["target_text"],
                )
            )
    grouped["source"] = list(source.values())
    result = {}
    for tag, rows in grouped.items():
        rows.sort(key=lambda r: (r["start"], r["id"]))
        normalized = []
        for row in rows:
            start, end = round(row["start"]), round(row["end"])
            if not 0 <= start < end <= round(plan.output_duration_ms) or not isinstance(
                row["text"], str
            ):
                raise ValueError("Invalid caption bounds")
            text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", row["text"]).strip()
            text = re.sub(r"\n\s*\n", "\n", text)
            if not text:
                raise ValueError("Empty included caption")
            normalized.append(dict(id=row["id"], start_ms=start, end_ms=end, text=text))
        result[tag] = normalized
    return result


def sidecars(plan, cues, tracks, directory, formats=("srt", "vtt")):
    results = []
    for index, (tag, rows) in enumerate(mapped_cues(plan, cues, tracks).items()):
        normalized = [dict(row, text=html.escape(row["text"], quote=False)) for row in rows]
        # Empty preview targets are explicit empty VTT/SRT artifacts, never filled from history.
        for format in formats:
            separator = "," if format == "srt" else "."
            chunks = ["WEBVTT\n"] if format == "vtt" else []
            for number, row in enumerate(normalized, 1):
                cue_id = str(number) if format == "srt" else row["id"]
                chunks.append(
                    f"{cue_id}\n{timestamp(row['start_ms'], separator)} --> {timestamp(row['end_ms'], separator)}\n{row['text']}\n"
                )
            content = "\n".join(chunks) + "\n"
            path = directory / f"captions-{index}.{format}"
            data = content.encode("utf-8")
            if len(data) > 2 * 1024 * 1024:
                raise ValueError("Caption limit")
            path.write_bytes(data)
            results.append(
                (
                    tag,
                    format,
                    ExportedFile(
                        path,
                        dict(
                            sha256=hashlib.sha256(data).hexdigest(),
                            byte_size=len(data),
                            cue_policy="target_actual_declared_speech_source_mapped_cue_v1",
                            clock="selection_relative_shared_map",
                            cue_ids=[row["id"] for row in normalized],
                            cue_manifest_sha256=hashlib.sha256(
                                repr(normalized).encode()
                            ).hexdigest(),
                            cue_count=len(normalized),
                            first_cue_ms=min((r["start_ms"] for r in normalized), default=None),
                            last_cue_ms=max((r["end_ms"] for r in normalized), default=None),
                            format=format,
                        ),
                    ),
                )
            )
    return results
