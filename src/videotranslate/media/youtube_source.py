"""Official YouTube extractor with one pinned network path and no credentials.

No generic extractors, playlists, browser cookies, ambient JS runtimes, manifests,
plugins, downloader subprocesses or media requests outside PublicVideoHTTP.
Availability is upstream dependent; failures explicitly offer file upload.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

# yt-dlp's library constructor loads plugins even with auto_init=False.
# This worker owns its yt-dlp embedding; never execute ambient plugins.
os.environ["YTDLP_NO_PLUGINS"] = "1"


@dataclass(frozen=True, repr=False)
class DownloadSpec:
    """Private, short-lived URLs. Never serialize this object into task state."""

    video_url: str
    audio_url: str | None = None


def resolve_video(http, url, *, deadline, check_active, max_duration):
    from yt_dlp import YoutubeDL
    from yt_dlp.extractor.youtube import YoutubeIE

    from ..execution.contracts import CancellationRequested, LeaseLost, StageFailure
    from .source_download import ImportRejected, youtube_host

    class Quiet:
        def debug(self, *args, **kwargs):
            pass

        warning = error = debug

    class PinnedYoutubeDL(YoutubeDL):
        def urlopen(self, request):
            # Replaces the sole extractor HTTP entry point, including youtubei
            # POSTs. No fallback request director or proxy environment is used.
            return http.metadata(request, deadline=deadline, check_active=check_active)

    params = dict(
        quiet=True,
        no_warnings=True,
        logger=Quiet(),
        cachedir=False,
        noplaylist=True,
        skip_download=True,
        socket_timeout=5,
        retries=0,
        extractor_retries=0,
        js_runtimes={"deno": {"path": str(Path(__file__).with_name("deno_runner.py"))}},
        remote_components=[],
        cookiefile=None,
        cookiesfrombrowser=None,
        usenetrc=False,
        extractor_args={"youtube": {"skip": ["hls", "dash", "translated_subs"]}},
    )
    check_active()
    try:
        with PinnedYoutubeDL(params, auto_init=False) as ydl:
            ydl.add_info_extractor(YoutubeIE())
            info = ydl.extract_info(url, download=False, process=False, ie_key="Youtube")
        if (
            not isinstance(info, dict)
            or info.get("_type", "video") != "video"
            or info.get("is_live")
            or info.get("live_status") in {"is_live", "is_upcoming"}
            or not isinstance(info.get("duration"), (int, float))
            or not 0 < info["duration"] <= max_duration
        ):
            raise ImportRejected()
        direct = [
            f
            for f in info.get("formats", [])
            if f.get("protocol") in (None, "https")
            and not f.get("fragments")
            and not f.get("manifest_url")
            and not f.get("has_drm")
            and isinstance(f.get("url"), str)
            and urlsplit(f["url"]).scheme == "https"
        ]
        progressive = [
            f
            for f in direct
            if f.get("ext") == "mp4"
            and f.get("vcodec") not in (None, "none")
            and f.get("acodec") not in (None, "none")
        ]
        if progressive:
            selected = max(
                progressive,
                key=lambda f: (
                    f.get("language_preference") or -1,
                    f.get("height") or 0,
                    f.get("tbr") or 0,
                ),
            )
            youtube_host(selected["url"])
            return DownloadSpec(selected["url"])
        # Adaptive imports use only direct MP4/H.264-or-AV1 + M4A/AAC files.
        # Limit this fallback to 1080p; no manifests or downloader subprocesses.
        video = [
            f
            for f in direct
            if f.get("ext") == "mp4"
            and f.get("acodec") == "none"
            and str(f.get("vcodec", "")).startswith(("avc1", "h264", "av01", "av1"))
            and type(f.get("height")) is int
            and 0 < f["height"] <= 1080
        ]
        audio = [
            f
            for f in direct
            if f.get("ext") in {"m4a", "mp4"}
            and f.get("vcodec") == "none"
            and str(f.get("acodec", "")).startswith(("mp4a", "aac"))
        ]
        if not video or not audio:
            raise ImportRejected()
        selected_video = max(video, key=lambda f: (f["height"], f.get("tbr") or 0))
        # The official extractor ranks original/default audio above auto-dubs.
        # Bitrate alone can silently replace the source language with a dub.
        selected_audio = max(
            audio,
            key=lambda f: (f.get("language_preference") or -1, f.get("abr") or f.get("tbr") or 0),
        )
        youtube_host(selected_video["url"])
        youtube_host(selected_audio["url"])
        return DownloadSpec(selected_video["url"], selected_audio["url"])
    except (ImportRejected, CancellationRequested, LeaseLost, StageFailure):
        raise
    except Exception:
        # Never expose yt-dlp tracebacks, titles, cookies, request URLs or query.
        raise ImportRejected() from None
