"""Pure bounded caption parser. Text is data; styling and external payloads are discarded."""

import hashlib
import html
import re
from html.parser import HTMLParser

MAX_BODY = 262144
MAX_CUES = 1000
MAX_TEXT = 10000
MAX_TOTAL_TEXT = 200000
_TIMESTAMP = re.compile(r"^(?:(\d{1,3}):)?(\d{2}):(\d{2})[.,](\d{3})$")


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "object", "audio", "video"}:
            self.blocked += 1
        if tag == "br" and not self.blocked:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "iframe", "object", "audio", "video"} and self.blocked:
            self.blocked -= 1

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(data)


def plain_text(text):
    parser = PlainText()
    parser.feed(text)
    return "".join(parser.parts).strip()


def timestamp(value):
    match = _TIMESTAMP.fullmatch(value)
    if not match:
        raise ValueError("Invalid timestamp")
    hours, minutes, seconds, millis = match.groups()
    if int(minutes) >= 60 or int(seconds) >= 60:
        raise ValueError("Invalid timestamp")
    return ((int(hours or 0) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


def parse_subtitles(content, format):
    if (
        format not in {"srt", "vtt", "numbered"}
        or len(content) > MAX_BODY
        or len(content.encode()) > MAX_BODY
    ):
        raise ValueError("Caption body limit")
    content = content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    total = 0
    blocks = re.split(r"\n[ \t]*\n", content.strip())
    if format == "numbered":
        blocks = [line for line in content.splitlines() if line.strip()]
    for block in blocks:
        lines = block.splitlines()
        if not lines:
            continue
        if format == "vtt" and (lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION"))):
            continue
        voice = None
        voices = []
        warnings = []
        errors = []
        start = end = None
        if format == "numbered":
            match = re.fullmatch(r"\s*\d+[.)]\s*(.+)", block)
            if not match:
                raise ValueError("Numbered captions required")
            text = match[1]
        else:
            timing = 0 if "-->" in lines[0] else 1
            if timing >= len(lines) or "-->" not in lines[timing]:
                raise ValueError("Caption timing required")
            bounds = lines[timing].split("-->")
            try:
                start, end = timestamp(bounds[0].strip()), timestamp(bounds[1].strip().split()[0])
                if end <= start:
                    errors.append("INVALID_TIMING")
            except (ValueError, IndexError):
                errors.append("INVALID_TIMING")
            text = "\n".join(lines[timing + 1 :])
            voices = list(
                dict.fromkeys(
                    plain_text(html.unescape(label))[:100]
                    for label in re.findall(r"<v(?:\.[^\s>]*)?\s+([^>]{1,100})>", text)
                )
            )
            if len(voices) == 1:
                voice = voices[0] or None
            elif len(voices) > 1:
                warnings.append("AMBIGUOUS_VOICE_LABEL")
        text = plain_text(text)
        if not text:
            errors.append("EMPTY_TEXT")
        total += len(text)
        if len(text) > MAX_TEXT or total > MAX_TOTAL_TEXT or len(cues) >= MAX_CUES:
            raise ValueError("Caption text limit")
        index = len(cues)
        digest = hashlib.sha256(f"{index}\0{start}\0{end}\0{text}\0{voice}".encode()).hexdigest()[
            :20
        ]
        cues.append(
            {
                "id": f"cue-{index + 1}-{digest}",
                "index": index,
                "start_ms": start,
                "end_ms": end,
                "text": text,
                "voice_label": voice,
                "voice_labels": voices,
                "warnings": warnings,
                "errors": errors,
            }
        )
    if not cues:
        raise ValueError("Captions required")
    return cues
