"""Hugging Face Whisper ASR and timestamp validation; no local inference."""

import math


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
