"""Trusted bounded installed outline-font discovery, with measured cmap coverage."""

import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, replace
from pathlib import Path

from .float_audio import digest

FAMILIES = {
    "sans": ("Noto Sans", "DejaVu Sans", "Arial"),
    "cjk": ("Noto Sans CJK SC", "Noto Sans CJK JP", "Hiragino Sans GB"),
    "arabic": ("Noto Sans Arabic", "DejaVu Sans", "Arial"),
    "hebrew": ("Noto Sans Hebrew", "DejaVu Sans", "Arial"),
}

MAX_SELECTED_FONTS = 16
MAX_DISCOVERED_FAMILIES = 512
MAX_CATALOG_BYTES = 128 * 1024
OUTLINE_PATTERN = ":outline=true:scalable=true:color=false"


def safe_family(value):
    # Family names are inserted in server-authored ASS \fn and style fields.
    # Exclude private placeholder families (.LastResort), separators, overrides,
    # pattern/filter syntax and controls, including every form of line break.
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and len(value.encode("utf-8")) <= 256
        and value == value.strip()
        and value[0].isalnum()
        and all(unicodedata.category(c)[0] in {"L", "M", "N"} or c in " .-_" for c in value)
    )


def measured_font(font):
    return (
        isinstance(font, SubtitleFont)
        and safe_family(font.family)
        and type(font.face) is int
        and 0 <= font.face < 256
        and isinstance(font.path, Path)
        and font.path.is_absolute()
        and isinstance(font.sha256, str)
        and re.fullmatch("[a-f0-9]{64}", font.sha256) is not None
        and isinstance(font.covered, frozenset)
        and len(font.covered) <= 65536
    )


def discover_families(point, budget):
    # One query for a missing codepoint finds covering candidates without a
    # subprocess per character or querying every installed font's charset.
    budget.check()
    data = budget.run(
        ["fc-list", "--format", "%{family[0]}\n", OUTLINE_PATTERN + f":charset={point:x}"]
    )
    if len(data) > MAX_CATALOG_BYTES:
        raise FontCoverageError("FONT_CATALOG_LIMIT")
    rows = data.decode("utf-8").splitlines()
    if len(rows) > MAX_DISCOVERED_FAMILIES * 16:
        raise FontCoverageError("FONT_CATALOG_LIMIT")
    families = set()
    for index, row in enumerate(rows):
        if index % 64 == 0:
            budget.check()
        if safe_family(row):
            families.add(row)
            if len(families) > MAX_DISCOVERED_FAMILIES:
                raise FontCoverageError("FONT_CATALOG_LIMIT")
    return sorted(families, key=lambda name: (not name.startswith("Noto "), name.casefold(), name))


class FontCoverageError(ValueError):
    def __init__(self, code, missing=()):
        super().__init__(code)
        self.code = code
        self.missing = tuple(missing)


@dataclass(frozen=True)
class SubtitleFont:
    path: Path
    family: str
    face: int
    sha256: str
    covered: frozenset[int]

    def facts(self):
        return dict(family=self.family, face=self.face, sha256=self.sha256)


def characters(text):
    if not isinstance(text, str) or len(text.encode("utf-8")) > 2 * 1024 * 1024:
        raise FontCoverageError("CAPTION_LIMIT")
    values = frozenset(
        ord(c)
        for c in text
        if not c.isspace()
        and unicodedata.category(c) not in {"Cf", "Cc"}
        and not 0xFE00 <= ord(c) <= 0xFE0F
        and not 0xE0100 <= ord(c) <= 0xE01EF
    )
    if len(values) > 65536:
        raise FontCoverageError("CAPTION_LIMIT")
    return values


def inspect_font(family, wanted, budget):
    if not safe_family(family):
        return None
    value = budget.run(
        [
            "fc-match",
            "--format",
            "%{file}\n%{family}\n%{index}\n%{outline}\n%{scalable}\n%{color}\n",
            family + OUTLINE_PATTERN,
        ]
    )
    rows = value.decode("utf-8").strip().splitlines()
    if (
        len(rows) != 6
        or rows[3:] != ["True", "True", "False"]
        or family.casefold() not in {v.strip().casefold() for v in rows[1].split(",")}
    ):
        return None  # Fontconfig's silent family substitution is not an installed font proof.
    path, face = Path(rows[0]), int(rows[2])
    if not path.is_file() or not 0 < path.stat().st_size <= 64 * 1024 * 1024 or not 0 <= face < 256:
        return None
    charset = budget.run(["fc-query", "--index", str(face), "--format", "%{charset}", str(path)])
    intervals = []
    for value in charset.decode("ascii").split():
        bounds = value.split("-")
        if len(bounds) not in {1, 2}:
            raise FontCoverageError("FONT_UNAVAILABLE")
        left, right = int(bounds[0], 16), int(bounds[-1], 16)
        if (
            not 0 <= left <= right <= 0x10FFFF
            or len(intervals) >= 10000
            or (intervals and left <= intervals[-1][1])
        ):
            raise FontCoverageError("FONT_UNAVAILABLE")
        intervals.append((left, right))
    starts, covered = [pair[0] for pair in intervals], set()
    for count, point in enumerate(wanted):
        if count % 256 == 0:
            budget.check()
        index = bisect_right(starts, point) - 1
        if index >= 0 and point <= intervals[index][1]:
            covered.add(point)
    # Delay hashing until this measured candidate actually adds coverage.
    return SubtitleFont(path, family, face, "", frozenset(covered))


def select_fonts(text, *, profile="auto", budget):
    if profile != "auto" and profile not in FAMILIES:
        raise FontCoverageError("FONT_UNAVAILABLE")
    wanted = characters(text)
    candidates = []
    for key in FAMILIES if profile == "auto" else (profile,):
        for family in FAMILIES[key]:
            font = inspect_font(family, wanted, budget)
            if font:
                if not any((v.path, v.face) == (font.path, font.face) for v in candidates):
                    candidates.append(font)
                break
    remaining, selected = set(wanted), []
    while candidates and remaining:
        best = max(candidates, key=lambda value: len(value.covered & remaining))
        if not best.covered & remaining:
            break
        selected.append(best)
        remaining -= best.covered
    if not wanted and candidates:
        selected = candidates[:1]  # Explicit empty ASS still names one actual font.
    attempts = 0
    while remaining and profile == "auto":
        if len(selected) >= MAX_SELECTED_FONTS:
            raise FontCoverageError("FONT_CATALOG_LIMIT")
        point, found = min(remaining), None
        for family in discover_families(point, budget):
            attempts += 1
            if attempts > MAX_DISCOVERED_FAMILIES:
                raise FontCoverageError("FONT_CATALOG_LIMIT")
            candidate = inspect_font(family, remaining, budget)
            if candidate and point in candidate.covered:
                found = candidate
                break
        if found is None:
            # This point was independently queried and has no usable outline
            # face. Report the proven missing point; do not invent others.
            raise FontCoverageError("FONT_GLYPHS_MISSING", [f"U+{point:04X}"])
        selected.append(found)
        remaining -= found.covered
    if remaining:
        raise FontCoverageError(
            "FONT_GLYPHS_MISSING", [f"U+{v:04X}" for v in sorted(remaining)[:256]]
        )
    if not selected:
        raise FontCoverageError("FONT_UNAVAILABLE")
    return tuple(replace(font, sha256=digest(font.path, budget.check)) for font in selected)
