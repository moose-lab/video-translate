"""Bounded recognition evidence. NFKC/casefold; punctuation/separators become spaces.

Letters, numbers and combining marks remain intact. WER is only offered for
space-tokenized languages; it is unavailable for scripts requiring segmentation.
Neither metric measures voice identity, pronunciation or listening acceptance.
"""

import unicodedata

MAX_CHARS = 4000
MAX_WORK = 1_000_000
UNSEGMENTED = {"zh", "ja", "ko", "th", "lo", "km", "my"}


def normalize(value):
    return " ".join(
        "".join(
            " " if unicodedata.category(c)[0] in {"P", "Z", "C"} else c
            for c in unicodedata.normalize("NFKC", value).casefold()
        ).split()
    )


def distance(left, right):
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def reported_language_status(target, detected):
    from ..languages.catalog import resolve

    if detected is None:
        return "not_reported"
    try:
        left, right = resolve(target), resolve(detected)
    except ValueError:
        return "unrecognized_report"
    if right["is_auto"]:
        return "unrecognized_report"
    return "compatible_base" if left["code"] == right["code"] else "mismatch"


def carryover(expected, recognized, reference, target):
    # At most eight token window sizes over <=4000 characters. Keep longest
    # unexpected shared excerpts, with bounded evidence; never single tokens.
    matches = set()
    left, right = reference.split(), recognized.split()
    for size in range(3, 9):
        ref = {" ".join(left[i : i + size]) for i in range(max(0, len(left) - size + 1))}
        heard = {" ".join(right[i : i + size]) for i in range(max(0, len(right) - size + 1))}
        matches.update(p for p in ref & heard if p not in expected)
    if target.split("-")[0] in UNSEGMENTED:
        if (
            reference
            and reference in recognized
            and reference not in expected
            and len(reference) >= 8
        ):
            matches.add(reference)
        else:
            heard = {recognized[i : i + 8] for i in range(max(0, len(recognized) - 7))}
            matches.update(
                reference[i : i + 8]
                for i in range(max(0, len(reference) - 7))
                if reference[i : i + 8] in heard and reference[i : i + 8] not in expected
            )
    if len(matches) > 128:
        return None
    longest = []
    for phrase in sorted(matches, key=lambda p: (-len(p), p)):
        if not any(phrase in previous for previous in longest):
            longest.append(phrase)
    return longest


def compare(expected, recognized, *, target, detected, reference=""):
    base = {
        "status": "available",
        "text_match": False,
        "character_error_rate": None,
        "word_error_rate": None,
        "reference_carryover": [],
        "language_status": reported_language_status(target, detected),
        "detected_language": detected,
        "listening_acceptance": "not_assessed",
        "policy": "nfkc_casefold_punctuation_space_v1",
    }
    if max(len(expected), len(recognized), len(reference)) > MAX_CHARS:
        return base | {"status": "unavailable", "reason": "comparison_length_limit"}
    a, b, r = map(normalize, (expected, recognized, reference))
    if not a or not b:
        return base | {"status": "unavailable", "reason": "empty_normalized_text"}
    if len(a) * len(b) > MAX_WORK:
        return base | {"status": "unavailable", "reason": "comparison_work_limit"}
    base.update(text_match=a == b, character_error_rate=distance(a, b) / len(a))
    if target.split("-")[0] not in UNSEGMENTED and (" " in a or " " in b):
        base["word_error_rate"] = distance(a.split(), b.split()) / len(a.split())
    excerpts = carryover(a, b, r, target)
    if excerpts is None:
        return base | {
            "status": "unavailable",
            "reason": "reference_evidence_limit",
            "text_match": False,
        }
    base["reference_carryover"] = excerpts
    return base
