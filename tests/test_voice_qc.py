"""Independent text evidence never substitutes for listening."""

import pytest


def test_unicode_punctuation_nonempty_and_no_invented_cjk_word_metric():
    from videotranslate.dubbing.qc_comparison import compare

    result = compare("ＡI， café!", "ai cafe\u0301", target="en", detected=None)
    assert result["text_match"] is True
    assert result["language_status"] == "not_reported"
    assert result["listening_acceptance"] == "not_assessed"
    assert (
        compare("你好世界", "你好世界", target="zh-Hant", detected="zh")["word_error_rate"] is None
    )
    assert compare("مرحبا بالعالم", "مرحبا بالعالم", target="ar", detected="ar")["text_match"]
    assert not compare("!?", "...", target="en", detected="en")["text_match"]


def test_limits_and_real_reference_phrase_evidence():
    from videotranslate.dubbing.qc_comparison import compare

    assert compare("a" * 5000, "a" * 5000, target="en", detected="en")["status"] == "unavailable"
    assert not compare(
        "AI is useful", "AI is useful", target="en", detected="en", reference="AI tools matter"
    )["reference_carryover"]
    result = compare(
        "Different target",
        "Human supplied exact words",
        target="en",
        detected="ja",
        reference="Human supplied exact words",
    )
    assert result["reference_carryover"] == ["human supplied exact words"]
    assert result["language_status"] == "mismatch"
    assert not compare(
        "Human supplied exact words",
        "Human supplied exact words",
        target="en",
        detected="en",
        reference="Human supplied exact words",
    )["reference_carryover"]


@pytest.mark.parametrize("text", ["नमस्ते", "اَلْعَرَبِيَّةُ", "ไทย"])
def test_combining_letters_survive_normalization(text):
    import unicodedata

    from videotranslate.dubbing.qc_comparison import normalize

    assert normalize(text) == unicodedata.normalize("NFKC", text).casefold()


def test_partial_reference_phrase_and_language_aliases_are_honest():
    from videotranslate.dubbing.qc_comparison import compare

    result = compare(
        "Correct target wording",
        "My secret reference phrase leaked",
        target="en",
        detected="English",
        reference="Before my secret reference phrase after",
    )
    assert "my secret reference phrase" in result["reference_carryover"]
    assert result["language_status"] == "compatible_base"
    assert result["detected_language"] == "English"
    assert (
        compare("猫", "猫", target="ja", detected="Japanese")["language_status"]
        == "compatible_base"
    )
    unknown = compare("猫", "猫", target="ja", detected="MysteryLanguage")
    assert unknown["language_status"] == "unrecognized_report"
    assert unknown["detected_language"] == "MysteryLanguage"
