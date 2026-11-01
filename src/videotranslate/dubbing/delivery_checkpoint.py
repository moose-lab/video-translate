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

ASS = CAPTIONS | {
    "clock_policy",
    "text_policy",
    "width",
    "height",
    "family",
    "font_size",
    "fonts",
    "font_proof_sha256",
}
BURNED = {
    "sha256",
    "byte_size",
    "source_video_sha256",
    "width",
    "height",
    "codec",
    "container",
    "frame_count",
    "frame_rate",
    "duration_ms",
    "fonts",
    "cue_count",
    "ass_sha256",
    "policy",
    "caption_proof_sha256",
}


def validate_caption_proof(proof, expected):
    from ..media.subtitle_fonts import FAMILIES

    if type(proof) is not dict or set(proof) != {
        "policy",
        "input_manifest_sha256",
        "cue_manifest_sha256",
        "glyphs_sha256",
        "glyph_count",
        "fonts",
        "options",
    }:
        raise ValueError("Invalid caption proof")
    if (
        proof["policy"] != "mapped_current_font_faces_v1"
        or proof["input_manifest_sha256"] != expected["input_manifest_fingerprint"]
        or proof["options"] != expected["caption_options"]
        or type(proof["glyph_count"]) is not int
        or not 0 <= proof["glyph_count"] <= 65536
        or type(proof["fonts"]) is not list
        or not 1 <= len(proof["fonts"]) <= 4
    ):
        raise ValueError("Invalid bound caption proof")
    hashes = [proof["cue_manifest_sha256"], proof["glyphs_sha256"]]
    for font in proof["fonts"]:
        if (
            type(font) is not dict
            or set(font) != {"family", "face", "sha256", "glyphs_sha256", "glyph_count"}
            or font["family"] not in {name for names in FAMILIES.values() for name in names}
            or type(font["face"]) is not int
            or not 0 <= font["face"] < 256
            or type(font["glyph_count"]) is not int
            or not 0 <= font["glyph_count"] <= proof["glyph_count"]
        ):
            raise ValueError("Invalid measured font face")
        hashes += [font["sha256"], font["glyphs_sha256"]]
    if any(type(v) is not str or not re.fullmatch("[a-f0-9]{64}", v) for v in hashes):
        raise ValueError("Invalid caption proof digest")


def validate_entry(entry, fields):
    if (
        type(entry) is not dict
        or set(entry) != fields
        or type(entry["object_id"]) is not str
        or not re.fullmatch(r"[A-Za-z0-9-]{1,36}", entry["object_id"])
    ):
        raise ValueError("Invalid delivery entry")
    if entry["format"] not in {"wav", "mp4", "mp3", "srt", "vtt", "ass"}:
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
        else BURNED
        if entry["kind"] == "delivery_burned_picture"
        else EXPORT | ({"captions"} if "captions" in data else set())
        if entry["format"] == "mp4"
        else MP3
        if entry["format"] == "mp3"
        else ASS
        if entry["format"] == "ass"
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
    options = expected.get("caption_options")
    font_required = bool(options and (options["burn_in"] or "ass" in options["formats"]))
    fields = {"binding", "phase", "phases", "objects", "artifacts"} | (
        {"caption_proof"} if font_required else set()
    )
    if (
        type(payload) is not dict
        or set(payload) != fields
        or fingerprint(payload["binding"]) != fingerprint(expected)
        or payload["phase"] not in {"caption_preflight", "render", "mix", "export"}
    ):
        raise ValueError("Invalid delivery checkpoint")
    bounded(payload)
    if font_required:
        validate_caption_proof(payload["caption_proof"], expected)
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
    if payload["phase"] == "caption_preflight":
        if not font_required or phases or objects or payload["artifacts"]:
            raise ValueError("Invalid caption preflight checkpoint")
        return
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
    burned = [e for e in exported if e.get("kind") == "delivery_burned_picture"]
    if len(burned) != int(bool(options and options["burn_in"])):
        raise ValueError("Invalid burned picture coverage")
    if burned:
        proof = payload["caption_proof"]
        data = burned[0]["metadata"]
        if (
            data.get("caption_proof_sha256") != fingerprint(proof)
            or data.get("source_video_sha256") != render[0]["metadata"]["sha256"]
            or any(
                data.get(k) != render[0]["metadata"][k] for k in ("width", "height", "frame_count")
            )
            or data.get("frame_rate")
            != "/".join(str(v) for v in render[0]["metadata"]["frame_rate"])
            or data.get("fonts")
            != [{k: f[k] for k in ("family", "face", "sha256")} for f in proof["fonts"]]
            or data.get("policy") != "libass_literal_font_coverage_v1"
        ):
            raise ValueError("Invalid burned picture proof")
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
        if artifact["format"] == "ass":
            if (
                entry["metadata"].get("font_proof_sha256") != fingerprint(payload["caption_proof"])
                or entry["metadata"].get("fonts") != payload["caption_proof"]["fonts"]
            ):
                raise ValueError("ASS font proof changed")
        if artifact["format"] == "mp4":
            captions = entry["metadata"].get("captions")
            if options and options["burn_in"]:
                receipt = dict(
                    mode="burn_in",
                    track=options["track"],
                    target_track=options.get("target_track"),
                    font_size=options["font_size"],
                    style=options["style"],
                    fonts=payload["caption_proof"]["fonts"],
                    cue_manifest_sha256=payload["caption_proof"]["cue_manifest_sha256"],
                    font_proof_sha256=fingerprint(payload["caption_proof"]),
                    burned_picture_sha256=burned[0]["metadata"]["sha256"],
                    ass_sha256=burned[0]["metadata"]["ass_sha256"],
                )
                if captions != receipt:
                    raise ValueError("Invalid burned export caption receipt")
            elif captions is not None:
                raise ValueError("Unexpected burned export")
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
    if options or expected["captions"] == "sidecar":
        required |= {
            (tag, format)
            for tag in ["source"] + expected["tracks"]
            for format in (options["formats"] if options else ("srt", "vtt"))
        }
    if coverage != required or len(coverage) != len(artifacts):
        raise ValueError("Invalid complete artifact coverage")
