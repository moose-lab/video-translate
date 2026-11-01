"""Bounded fontconfig discovery from fixed families, with real cmap coverage."""

import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .float_audio import digest

FAMILIES = {
    "sans": ("Noto Sans", "DejaVu Sans", "Arial"),
    "cjk": ("Noto Sans CJK SC", "Noto Sans CJK JP", "Hiragino Sans GB"),
    "arabic": ("Noto Sans Arabic", "DejaVu Sans", "Arial"),
    "hebrew": ("Noto Sans Hebrew", "DejaVu Sans", "Arial"),
}


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
    value = budget.run(["fc-match", "--format", "%{file}\n%{family}\n%{index}\n", family])
    rows = value.decode("utf-8").strip().splitlines()
    if len(rows) != 3 or family.casefold() not in {
        v.strip().casefold() for v in rows[1].split(",")
    }:
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
        if not 0 <= left <= right <= 0x10FFFF or len(intervals) >= 10000:
            raise FontCoverageError("FONT_UNAVAILABLE")
        intervals.append((left, right))
    covered = frozenset(point for point in wanted if any(a <= point <= b for a, b in intervals))
    return SubtitleFont(path, family, face, digest(path, budget.check), covered)


def select_fonts(text, *, profile="auto", budget):
    if profile != "auto" and profile not in FAMILIES:
        raise FontCoverageError("FONT_UNAVAILABLE")
    wanted = characters(text)
    candidates = []
    for key in FAMILIES if profile == "auto" else (profile,):
        for family in FAMILIES[key]:
            font = inspect_font(family, wanted, budget)
            if font:
                if not any((v.sha256, v.face) == (font.sha256, font.face) for v in candidates):
                    candidates.append(font)
                break
    if not candidates:
        raise FontCoverageError("FONT_UNAVAILABLE")
    remaining, selected = set(wanted), []
    while remaining:
        best = max(candidates, key=lambda value: len(value.covered & remaining))
        if not best.covered & remaining:
            raise FontCoverageError(
                "FONT_GLYPHS_MISSING", [f"U+{v:04X}" for v in sorted(remaining)[:256]]
            )
        selected.append(best)
        remaining -= best.covered
    return tuple(selected or candidates[:1])
