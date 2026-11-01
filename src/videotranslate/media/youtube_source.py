"""Official YouTube extractor with one pinned network path and no credentials.

No generic extractors, playlists, browser cookies, ambient JS runtimes, manifests,
plugins, downloader subprocesses or media requests outside PublicVideoHTTP.
Availability is upstream dependent; failures explicitly offer file upload.
"""

import os
from pathlib import Path
from urllib.parse import urlsplit

# yt-dlp's library constructor loads plugins even with auto_init=False.
# This worker owns its yt-dlp embedding; never execute ambient plugins.
os.environ["YTDLP_NO_PLUGINS"] = "1"


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
        formats = [
            f
            for f in info.get("formats", [])
            if f.get("ext") == "mp4"
            and f.get("protocol") in (None, "https")
            and not f.get("fragments")
            and not f.get("manifest_url")
            and f.get("vcodec") not in (None, "none")
            and f.get("acodec") not in (None, "none")
            and not f.get("has_drm")
            and isinstance(f.get("url"), str)
            and urlsplit(f["url"]).scheme == "https"
        ]
        if not formats:
            raise ImportRejected()
        selected = max(formats, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
        youtube_host(selected["url"])
        return selected["url"]
    except (ImportRejected, CancellationRequested, LeaseLost, StageFailure):
        raise
    except Exception:
        # Never expose yt-dlp tracebacks, titles, cookies, request URLs or query.
        raise ImportRejected() from None
