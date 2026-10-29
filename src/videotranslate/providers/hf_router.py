"""Validate actual HF response data before making it available to the domain."""

import math


def normalize_translation(value, expected_ids):
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("segments"), list)
        or len(set(expected_ids)) != len(expected_ids)
    ):
        raise ValueError("Invalid translation response")
    rows = value["segments"]
    if len(rows) != len(expected_ids):
        raise ValueError("Translation segment count mismatch")
    result = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"id", "text"}
            or not isinstance(row["id"], str)
            or not isinstance(row["text"], str)
            or not row["text"].strip()
            or row["id"] in result
        ):
            raise ValueError("Invalid translation segment")
        result[row["id"]] = row["text"]
    if set(result) != set(expected_ids):
        raise ValueError("Translation segment IDs mismatch")
    return result


def normalize_asr(value):
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("chunks"), list)
        or not value["chunks"]
    ):
        raise ValueError("Provider returned no timestamped chunks")
    result = []
    for chunk in value["chunks"]:
        if not isinstance(chunk, dict) or not isinstance(chunk.get("text"), str):
            raise ValueError("Invalid speech chunk")
        timestamps = chunk.get("timestamp")
        if (
            not isinstance(timestamps, list)
            or len(timestamps) != 2
            or not all(
                isinstance(t, (float, int)) and not isinstance(t, bool) and math.isfinite(t)
                for t in timestamps
            )
            or timestamps[0] < 0
            or timestamps[1] < timestamps[0]
        ):
            raise ValueError("Invalid speech timestamps")
        result.append({"text": chunk["text"], "start": timestamps[0], "end": timestamps[1]})
    return result


def translate(
    http,
    *,
    model,
    token,
    target,
    segments,
    endpoint="https://router.huggingface.co/v1",
    credential_kind="huggingface",
):
    """Submit a single structured chat request; callers persist successful results durably."""
    import json
    from urllib.parse import urlsplit

    from ..languages.catalog import resolve
    from .network import validate_url

    validate_url(endpoint, allowed_hosts=getattr(http, "allowed_hosts", set()))
    host = urlsplit(endpoint).hostname
    if (
        credential_kind not in {"huggingface", "translation"}
        or (credential_kind == "huggingface" and host != "router.huggingface.co")
        or (credential_kind == "translation" and host not in getattr(http, "allowed_hosts", set()))
    ):
        raise ValueError("Credential cannot be sent to this provider")
    if not model or (credential_kind == "huggingface" and not token) or resolve(target)["is_auto"]:
        raise ValueError("Translation model, credential and explicit target are required")
    if not isinstance(segments, list) or not segments:
        raise ValueError("Translation segments required")
    ids = []
    for row in segments:
        if (
            not isinstance(row, dict)
            or set(row) != {"id", "text"}
            or not all(isinstance(row[k], str) and row[k] for k in ("id", "text"))
        ):
            raise ValueError("Invalid translation segment")
        ids.append(row["id"])
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate translation segment IDs")
    normalized_target = resolve(target)["tag"]
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Translate each segment. Return JSON with target_language and segments containing exactly the provided ids and translated text.",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"target_language": normalized_target, "segments": segments}, ensure_ascii=False
                ),
            },
        ],
        "response_format": {"type": "json_object"},
    }
    raw = http.post_json(
        endpoint.rstrip("/") + "/chat/completions",
        body,
        headers={"Authorization": "Bearer " + token} if token else {},
    )
    try:
        message = json.loads(raw)["choices"][0]["message"]["content"]
        data = json.loads(message)
        if data.get("target_language") != normalized_target:
            raise ValueError()
        return normalize_translation(data, ids)
    except (ValueError, KeyError, TypeError, IndexError):
        raise ValueError("Invalid structured translation response") from None


def transcribe(http, *, audio, model, token, include_metadata=False):
    """HF Inference ASR with timestamps. This is a synchronous, non-resumable call."""
    import base64
    import json
    import re

    if (
        not isinstance(audio, bytes)
        or not audio
        or len(audio) > 16 * 1024 * 1024
        or not token
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", model)
    ):
        raise ValueError("Valid audio, model and HF credential are required")
    body = {
        "inputs": base64.b64encode(audio).decode("ascii"),
        "parameters": {"return_timestamps": True},
    }
    raw = http.post_json(
        "https://router.huggingface.co/hf-inference/models/" + model,
        body,
        headers={"Authorization": "Bearer " + token},
        max_request_bytes=24 * 1024 * 1024,
    )
    try:
        value = json.loads(raw)
        rows = normalize_asr(value)
        language = value.get("language")
        if language is not None and (
            not isinstance(language, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,39}", language)
        ):
            raise ValueError()
        return {"segments": rows, "detected_language": language} if include_metadata else rows
    except (ValueError, TypeError):
        raise ValueError("Invalid ASR response") from None
