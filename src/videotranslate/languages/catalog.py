"""Pinned OmniVoice metadata; language availability does not imply pipeline support."""

import json
import unicodedata
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data"


def key(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Language must be a string")
    return unicodedata.normalize("NFKC", value).strip().casefold()


@lru_cache(maxsize=1)
def catalog() -> list[dict]:
    return json.loads((DATA / "catalog.json").read_text())


def upstream() -> dict:
    return json.loads((DATA / "manifest.json").read_text())


def resolve(value: str) -> dict:
    normalized = key(value)
    matches = []
    for row in catalog():
        for candidate in [
            row["code"],
            row["name"],
            row["iso639_3"],
            *row["aliases"],
            *row["variants"],
        ]:
            if candidate and key(candidate) == normalized:
                tag = candidate if candidate in row["variants"] else row["code"]
                matches.append({**row, "tag": tag})
    tags = {row["tag"] for row in matches}
    if len(tags) != 1:
        raise ValueError("Unknown or ambiguous language")
    return matches[0]


def search(query: str, include_auto: bool) -> list[dict]:
    query = key(query)
    return [
        row
        for row in catalog()
        if (include_auto or not row["is_auto"])
        and any(
            query in key(value)
            for value in [
                row["code"],
                row["name"],
                row["iso639_3"] or "",
                *row["aliases"],
                *row["variants"],
            ]
        )
    ]
