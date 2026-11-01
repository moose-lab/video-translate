"""Real installed script fonts expand AUTO without accepting client font names."""

import subprocess

from test_float_audio import LIMITS


def test_auto_resolves_actual_indic_thai_armenian_and_bengali_and_burns(tmp_path):
    from videotranslate.media.float_audio import Budget
    from videotranslate.media.subtitle_finishing import ass_file, burn_in
    from videotranslate.media.subtitle_fonts import characters, select_fonts

    text = "नमस्ते दुनिया\nสวัสดีโลก\nՀայերեն\nবাংলা"
    budget = Budget(LIMITS, lambda: None, tmp_path)
    fonts = select_fonts(text, budget=budget)
    wanted = characters(text)
    assert wanted <= set().union(*(font.covered for font in fonts))
    assert all(len(font.sha256) == 64 and font.path.is_file() for font in fonts)
    cues = [dict(id="current-scripts", start_ms=0, end_ms=1000, text=text)]
    sidecar = ass_file(
        cues, tmp_path / "scripts.ass", width=640, height=360, family=fonts[0].family, fonts=fonts
    )
    assert all(char in sidecar.path.read_text() for char in "नสՀব")
    assert "{\\fn" in sidecar.path.read_text()
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=640x360:r=25:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        timeout=30,
    )
    movie = burn_in(
        source, cues, tmp_path / "scripts.mp4", fonts=fonts, width=640, height=360, budget=budget
    )
    pixels = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            "0.5",
            "-i",
            str(movie.path),
            "-frames:v",
            "1",
            "-pix_fmt",
            "gray",
            "-f",
            "rawvideo",
            "-",
        ],
        timeout=30,
    )
    assert len(pixels) == 640 * 360 and sum(value > 180 for value in pixels) > 300
    assert movie.facts["frame_count"] == 25 and movie.facts["fonts"] == [
        font.facts() for font in fonts
    ]


def test_auto_fallback_queries_only_missing_scripts_and_hashes_only_selected_faces(
    tmp_path, monkeypatch
):
    from videotranslate.media import subtitle_fonts as catalog
    from videotranslate.media.float_audio import Budget

    class RecordingBudget(Budget):
        def __init__(self):
            super().__init__(LIMITS, lambda: None, tmp_path)
            self.commands = []

        def run(self, args, **kwargs):
            self.commands.append(args)
            return super().run(args, **kwargs)

    hashed = []
    original_digest = catalog.digest

    def measured_digest(path, check):
        hashed.append(path)
        return original_digest(path, check)

    monkeypatch.setattr(catalog, "digest", measured_digest)
    budget = RecordingBudget()
    fixed = catalog.select_fonts("Hello 你好 مرحبا שלום", budget=budget)
    assert not any(args[0] == "fc-list" for args in budget.commands)
    assert hashed == [font.path for font in fixed]
    assert len(fixed) <= 4

    budget.commands.clear()
    hashed.clear()
    expanded = catalog.select_fonts("Hello नमस्ते สวัสดี Հայերեն বাংলা", budget=budget)
    discovery = [args for args in budget.commands if args[0] == "fc-list"]
    assert discovery and len(discovery) <= catalog.MAX_SELECTED_FONTS
    assert all(args[-1].startswith(catalog.OUTLINE_PATTERN + ":charset=") for args in discovery)
    assert hashed == [font.path for font in expanded]
    assert len({(font.path, font.face) for font in expanded}) == len(expanded)


def test_catalog_ignores_unsafe_families_and_has_explicit_bounds():
    import pytest

    from videotranslate.media import subtitle_fonts as catalog

    class CatalogBudget:
        def __init__(self, data):
            self.data = data
            self.commands = []

        def check(self):
            pass

        def run(self, args):
            self.commands.append(args)
            return self.data

    hostile = [
        r"Noto{\pos(1,1)}",
        r"Bad\fnArial",
        "Bad,Style",
        "Bad:charset=41",
        "Bad/Path",
        ".LastResort",
        " Bad",
        "Bad\x00Name",
        "Bad\tName",
        "Bad\u2028Name",
    ]
    for value in hostile:
        assert not catalog.safe_family(value), repr(value)
    data = "\n".join(hostile[:7] + ["Thai Text", "Noto Sans Thai", "Noto Sans Thai"]).encode()
    budget = CatalogBudget(data)
    assert catalog.discover_families(0xE01, budget) == ["Noto Sans Thai", "Thai Text"]
    assert budget.commands == [
        [
            "fc-list",
            "--format",
            "%{family[0]}\n",
            catalog.OUTLINE_PATTERN + ":charset=e01",
        ]
    ]
    for data in (
        b"x" * (catalog.MAX_CATALOG_BYTES + 1),
        "\n".join(f"Font {index}" for index in range(catalog.MAX_DISCOVERED_FAMILIES + 1)).encode(),
    ):
        with pytest.raises(catalog.FontCoverageError, match="FONT_CATALOG_LIMIT"):
            catalog.discover_families(0xE01, CatalogBudget(data))


def test_explicit_profiles_do_not_expand_and_client_families_remain_rejected(tmp_path):
    import pytest

    from videotranslate.media.float_audio import Budget
    from videotranslate.media.subtitle_fonts import FontCoverageError, select_fonts

    budget = Budget(LIMITS, lambda: None, tmp_path)
    with pytest.raises(FontCoverageError, match="FONT_GLYPHS_MISSING"):
        select_fonts("नमस्ते", profile="sans", budget=budget)
    with pytest.raises(FontCoverageError, match="FONT_UNAVAILABLE"):
        select_fonts("नमस्ते", profile="Noto Sans Devanagari", budget=budget)


def test_expanded_measured_font_proof_roundtrips_and_rejects_hostile_override(tmp_path):
    import copy
    from dataclasses import replace

    import pytest

    from videotranslate.dubbing.delivery_checkpoint import validate_caption_proof
    from videotranslate.execution.contracts import StageFailure
    from videotranslate.execution.inputs import fingerprint
    from videotranslate.media.float_audio import Budget
    from videotranslate.media.subtitle_finishing import ass_document, literal_font_runs
    from videotranslate.media.subtitle_fonts import FontCoverageError, characters, select_fonts

    text = "Hello 你好 مرحبا שלום नमस्ते สวัสดี Հայերեն বাংলা မြန်မာ සිංහල አማርኛ"
    fonts = select_fonts(text, budget=Budget(LIMITS, lambda: None, tmp_path))
    assert len(fonts) > 4
    wanted = characters(text)
    options = dict(font_profile="auto")
    proof = dict(
        policy="mapped_current_font_faces_v1",
        input_manifest_sha256="a" * 64,
        cue_manifest_sha256="b" * 64,
        glyphs_sha256=fingerprint(sorted(wanted)),
        glyph_count=len(wanted),
        fonts=[
            dict(
                font.facts(),
                glyphs_sha256=fingerprint(sorted(font.covered & wanted)),
                glyph_count=len(font.covered & wanted),
            )
            for font in fonts
        ],
        options=options,
    )
    expected = dict(input_manifest_fingerprint="a" * 64, caption_options=options)
    validate_caption_proof(proof, expected)
    for family in (r"Noto{\pos(1,1)}", "Bad,Style", "Bad\nName", "Bad:charset=41"):
        corrupted = copy.deepcopy(proof)
        corrupted["fonts"][0]["family"] = family
        with pytest.raises(ValueError, match="font face"):
            validate_caption_proof(corrupted, expected)
        invalid = (replace(fonts[0], family=family),)
        with pytest.raises(FontCoverageError, match="FONT_UNAVAILABLE"):
            literal_font_runs("A", invalid)
        with pytest.raises(StageFailure):
            ass_document([], width=640, height=360, family=family, fonts=invalid)
    corrupted = copy.deepcopy(proof)
    corrupted["fonts"] = [proof["fonts"][0]] * 17
    with pytest.raises(ValueError, match="bound caption proof"):
        validate_caption_proof(corrupted, expected)


def test_too_many_independently_covered_faces_stop_before_hashing(tmp_path, monkeypatch):
    import pytest

    from videotranslate.media import subtitle_fonts as catalog
    from videotranslate.media.float_audio import Budget

    text = "".join(chr(0xE000 + index) for index in range(catalog.MAX_SELECTED_FONTS + 1))

    def inspect(family, wanted, budget):
        if family.startswith("Private Font "):
            point = int(family.rsplit(" ", 1)[-1])
            return catalog.SubtitleFont(tmp_path / "unused.ttf", family, 0, "", frozenset({point}))
        return None

    monkeypatch.setattr(catalog, "inspect_font", inspect)
    monkeypatch.setattr(
        catalog, "discover_families", lambda point, budget: [f"Private Font {point}"]
    )
    monkeypatch.setattr(
        catalog, "digest", lambda *_: pytest.fail("Over-limit catalog must not hash")
    )
    with pytest.raises(catalog.FontCoverageError, match="FONT_CATALOG_LIMIT"):
        catalog.select_fonts(text, budget=Budget(LIMITS, lambda: None, tmp_path))
