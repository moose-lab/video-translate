"""Strict bounded CPU phase manifests, independent of SQL and storage."""

import math
import re

from ..execution.inputs import fingerprint
from ..execution.prepared import bounded

BASE = {"object_id", "metadata", "kind", "format"}
AUDIO = {
    "duration_ms",
    "sample_rate",
    "channels",
    "byte_size",
    "sha256",
    "codec",
    "container",
    "sample_count",
    "peak",
    "receipt",
}
VIDEO = {
    "sha256",
    "byte_size",
    "duration_ms",
    "codec",
    "container",
    "width",
    "height",
    "frame_rate",
    "frame_count",
    "receipt",
}
EXPORT = {
    "sha256",
    "byte_size",
    "duration_ms",
    "codec",
    "container",
    "audio_tracks",
    "audio_padding_policy",
    "audio_padding_limit_ms",
}
MP3 = {
    "sha256",
    "byte_size",
    "codec",
    "container",
    "sample_rate",
    "channels",
    "actual_decoded_samples",
    "decoded_peak",
    "duration_ms",
    "padding_policy",
}
CAPTIONS = {
    "sha256",
    "byte_size",
    "cue_policy",
    "clock",
    "cue_ids",
    "cue_manifest_sha256",
    "cue_count",
    "first_cue_ms",
    "last_cue_ms",
    "format",
}


def validate_entry(entry, fields):
    if (
        type(entry) is not dict
        or set(entry) != fields
        or type(entry["object_id"]) is not str
        or not re.fullmatch(r"[A-Za-z0-9-]{1,36}", entry["object_id"])
    ):
        raise ValueError("Invalid delivery entry")
    if entry["format"] not in {"wav", "mp4", "mp3", "srt", "vtt"}:
        raise ValueError("Unknown delivery format")
    data = entry["metadata"]
    if (
        type(data) is not dict
        or type(data.get("sha256")) is not str
        or not re.fullmatch(r"[0-9a-f]{64}", data["sha256"])
        or type(data.get("byte_size")) is not int
        or not 0 < data["byte_size"] <= 512 * 1024**2
    ):
        raise ValueError("Invalid measured delivery metadata")
    required = (
        AUDIO - {"sample_count", "peak", "receipt"}
        if entry["format"] == "wav"
        else VIDEO
        if entry["format"] == "mp4" and entry["kind"] == "delivery_picture"
        else EXPORT
        if entry["format"] == "mp4"
        else MP3
        if entry["format"] == "mp3"
        else CAPTIONS
    )
    if set(data) != required and not (entry["format"] == "wav" and set(data) == AUDIO):
        raise ValueError("Unknown or incomplete media metadata")
    if "duration_ms" in data and (
        type(data["duration_ms"]) is not int or not 0 < data["duration_ms"] <= 57600000
    ):
        raise ValueError("Invalid measured duration")
    for number in ("sample_count", "actual_decoded_samples", "frame_count"):
        if number in data and (type(data[number]) is not int or not 0 < data[number] <= 2764800000):
            raise ValueError("Invalid measured sample/frame count")
    for number in ("peak", "decoded_peak"):
        if number in data and (
            type(data[number]) not in {int, float}
            or not math.isfinite(data[number])
            or data[number] < 0
        ):
            raise ValueError("Invalid measured peak")
    bounded(data, 65536)
    if entry["format"] == "wav" and (
        data.get("sample_rate") != 48000
        or type(data.get("sample_rate")) is not int
        or data.get("channels") != 2
        or type(data.get("channels")) is not int
    ):
        raise ValueError("Invalid delivery audio format")
    if type(entry["kind"]) is not str or not re.fullmatch(
        r"delivery_[a-z0-9_]{1,30}", entry["kind"]
    ):
        raise ValueError("Invalid delivery media family")


def validate_checkpoint(payload, expected):
    if (
        type(payload) is not dict
        or set(payload) != {"binding", "phase", "phases", "objects", "artifacts"}
        or fingerprint(payload["binding"]) != fingerprint(expected)
        or payload["phase"] not in {"render", "mix", "export"}
    ):
        raise ValueError("Invalid delivery checkpoint")
    bounded(payload)
    phases = payload["phases"]
    objects = payload["objects"]
    if (
        type(phases) is not dict
        or type(objects) is not list
        or len(objects) > 1100
        or any(type(x) is not str for x in objects)
        or len(set(objects)) != len(objects)
    ):
        raise ValueError("Invalid delivery objects")
    if set(phases) not in ({"render"}, {"render", "mix"}, {"render", "mix", "export"}) or payload[
        "phase"
    ] != ("export" if "export" in phases else "mix" if "mix" in phases else "render"):
        raise ValueError("Invalid delivery phase order")
    entries = []
    for manifest in phases.values():
        if (
            type(manifest) is not dict
            or set(manifest) != {"outputs", "fingerprint"}
            or type(manifest["outputs"]) is not list
            or manifest["fingerprint"] != fingerprint(manifest["outputs"])
        ):
            raise ValueError("Invalid immutable phase manifest")
        entries.extend(manifest["outputs"])
    render = phases["render"]["outputs"]
    if len(render) != 3 + len(expected["voice_keys"]):
        raise ValueError("Incomplete render manifest")
    for entry, kind, format in zip(
        render[:3],
        ("delivery_picture", "delivery_working", "delivery_original"),
        ("mp4", "wav", "wav"),
        strict=True,
    ):
        validate_entry(entry, BASE)
        if entry["kind"] != kind or entry["format"] != format:
            raise ValueError("Invalid render family")
    for i, (entry, key) in enumerate(zip(render[3:], expected["voice_keys"], strict=True)):
        validate_entry(entry, BASE | {"track_id", "segment_id"})
        if (
            entry["format"] != "wav"
            or entry["kind"] != "delivery_voice_" + str(i)
            or entry["track_id"] + ":" + entry["segment_id"] != key
        ):
            raise ValueError("Invalid fitted voice binding")
    if "mix" in phases:
        mixed = phases["mix"]["outputs"]
        tracks = (["original"] if expected["comparison"] else []) + expected["tracks"]
        if [entry.get("track") for entry in mixed] != tracks:
            raise ValueError("Invalid mix track coverage")
        for entry in mixed:
            validate_entry(
                entry,
                BASE | {"track"}
                if entry["track"] == "original"
                else BASE | {"track", "included_source_intervals"},
            )
            if (
                entry["format"] != "wav"
                or entry["metadata"].get("receipt", {}).get("policy")
                != "float_additive_uniform_ceiling_v1"
            ):
                raise ValueError("Invalid protected mix family")
    if len({e["object_id"] for e in entries}) != len(entries) or {
        e["object_id"] for e in entries
    } != set(objects):
        raise ValueError("Object manifest is not exact")
    artifacts = payload["artifacts"]
    if type(artifacts) is not list or len(artifacts) > 100:
        raise ValueError("Invalid artifact manifest")
    if "export" not in phases:
        if artifacts:
            raise ValueError("Partial delivery has published artifacts")
        return
    exported = phases["export"]["outputs"]
    for entry in exported:
        validate_entry(entry, BASE)
    published = {e["object_id"]: e for e in phases["mix"]["outputs"] + exported}
    if len({a.get("object_id") for a in artifacts}) != len(artifacts):
        raise ValueError("Duplicate delivery artifact")
    for artifact in artifacts:
        if (
            type(artifact) is not dict
            or set(artifact) != {"object_id", "format", "track"}
            or artifact["object_id"] not in published
            or artifact["format"] != published[artifact["object_id"]]["format"]
            or artifact["track"] not in {"all", "source", "original", *expected["tracks"]}
        ):
            raise ValueError("Invalid delivery artifact family")
    mixes = {entry["track"]: entry for entry in phases["mix"]["outputs"]}
    for artifact in artifacts:
        entry = published[artifact["object_id"]]
        tag = artifact["track"]
        if artifact["format"] == "wav" and mixes[tag]["object_id"] != entry["object_id"]:
            raise ValueError("Artifact track uses the wrong mix")
        if (
            artifact["format"] == "mp3"
            and entry["metadata"]["actual_decoded_samples"]
            != mixes[tag]["metadata"]["sample_count"]
        ):
            raise ValueError("MP3 sample count differs from its captured mix")
        if artifact["format"] == "mp4":
            main = tag == ("all" if expected["tracks"] else "original")
            tags = (
                (["original"] if expected["comparison"] else []) + expected["tracks"]
                if main
                else (["original"] if expected["comparison"] else []) + [tag]
            )
            tracks = entry["metadata"].get("audio_tracks")
            default = expected["default_track"] if main else tag
            if (
                type(tracks) is not list
                or [t.get("tag") for t in tracks] != tags
                or any(
                    type(t) is not dict
                    or set(t) != {"tag", "language", "default"}
                    or type(t["default"]) is not bool
                    or t["default"] != (t["tag"] == default)
                    or not re.fullmatch("[a-z]{3}", t["language"])
                    for t in tracks
                )
            ):
                raise ValueError("Invalid complete export audio metadata")
    coverage = {(a["track"], a["format"]) for a in artifacts}
    required = {
        (tag, "wav")
        for tag in ((["original"] if expected["comparison"] else []) + expected["tracks"])
    }
    required |= {
        (tag, "mp3")
        for tag in ((["original"] if expected["comparison"] else []) + expected["tracks"])
    }
    required |= {(tag, "mp4") for tag in expected["tracks"]}
    required.add(("all" if expected["tracks"] else "original", "mp4"))
    if expected["captions"] == "sidecar":
        required |= {
            (tag, format) for tag in ["source"] + expected["tracks"] for format in ("srt", "vtt")
        }
    if coverage != required or len(coverage) != len(artifacts):
        raise ValueError("Invalid complete artifact coverage")
