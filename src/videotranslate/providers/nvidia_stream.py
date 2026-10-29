"""Validate real NVIDIA streaming diarization final results."""

import math
import socket
import ssl

from websockets.sync.client import connect as ws_connect

from .network import open_proxy_tunnel, resolve_doh, resolve_public, validate_public_addresses


def normalize_final(value):
    if (
        not isinstance(value, dict)
        or value.get("type") != "result"
        or value.get("isFinal") is not True
        or not isinstance(value.get("segments"), list)
    ):
        raise ValueError("No final diarization result")
    received = value.get("receivedAudioMs")
    if (
        not isinstance(received, (int, float))
        or isinstance(received, bool)
        or not math.isfinite(received)
        or not 0 <= received <= 120000
    ):
        raise ValueError("Invalid received audio duration")
    result = []
    for segment in value["segments"]:
        if not isinstance(segment, dict):
            raise ValueError("Invalid diarization segment")
        start, end = segment.get("startTime"), segment.get("endTime")
        speaker, text = segment.get("speaker"), segment.get("text")
        if (
            not all(
                isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t)
                for t in (start, end)
            )
            or start < 0
            or end < start
            or end > received / 1000 + 0.05
            or not isinstance(speaker, str)
            or not speaker
            or not isinstance(text, str)
        ):
            raise ValueError("Invalid diarization segment")
        result.append({"start": start, "end": end, "speaker": speaker, "text": text})
    return result


def stream_file(ws, pcm, *, max_speakers=8, timeout_seconds=180):
    """Use an established WebSocket for a bounded, non-resumable English file stream."""
    import json
    import time

    if not isinstance(pcm, bytes) or not pcm or len(pcm) % 2 or len(pcm) > 120 * 16000 * 2:
        raise ValueError("Audio must be 16 kHz mono PCM16, at most 120 seconds")
    if (
        not isinstance(max_speakers, int)
        or isinstance(max_speakers, bool)
        or not 1 <= max_speakers <= 8
    ):
        raise ValueError("Invalid maximum speaker count")
    deadline = time.monotonic() + timeout_seconds

    def receive():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Streaming result timed out")
        try:
            raw = ws.recv(timeout=remaining)
            if not isinstance(raw, str) or len(raw.encode()) > 1024 * 1024:
                raise ValueError()
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except Exception:
            raise ValueError("Streaming response unavailable or invalid") from None

    ws.send(json.dumps({"type": "start", "sampleRateHz": 16000, "maxSpeakers": max_speakers}))
    if receive().get("type") != "ready":
        raise ValueError("Provider did not become ready")
    for offset in range(0, len(pcm), 65536):
        ws.send(pcm[offset : offset + 65536])
    ws.send(json.dumps({"type": "end"}))
    while True:
        message = receive()
        if message.get("type") == "error":
            raise ValueError("Provider stream failed")
        if message.get("type") == "result" and message.get("isFinal") is True:
            return normalize_final(message)


def stream_remote(pcm, *, max_speakers=8, proxy_url=None, use_doh=False):
    """Connect directly to a pinned public IP with hostname-validated TLS."""
    host = "nvidia-nemotron-diarization.hf.space"
    if not isinstance(pcm, bytes) or not pcm or len(pcm) % 2 or len(pcm) > 120 * 16000 * 2:
        raise ValueError("Audio must be 16 kHz mono PCM16, at most 120 seconds")
    if use_doh and not proxy_url:
        raise ValueError("Trusted DNS requires an administrator proxy")
    addresses = resolve_doh(host, proxy_url) if use_doh else resolve_public(host)
    validate_public_addresses(addresses)
    sock = (
        open_proxy_tunnel(proxy_url, addresses[0], 443, 5)
        if proxy_url
        else socket.create_connection((addresses[0], 443), timeout=5)
    )
    try:
        with ws_connect(
            f"wss://{host}/api/diarization/file/stream",
            sock=sock,
            ssl=ssl.create_default_context(),
            server_hostname=host,
            proxy=None,
            open_timeout=10,
            max_size=1024 * 1024,
        ) as ws:
            return stream_file(ws, pcm, max_speakers=max_speakers)
    finally:
        sock.close()
