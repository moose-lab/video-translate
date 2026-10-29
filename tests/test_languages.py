import unicodedata


def test_catalog_count_and_exact_upstream_names():
    from videotranslate.languages.catalog import catalog, resolve

    assert len(catalog()) == 647
    assert len({row["code"] for row in catalog()}) == 647
    assert resolve("cmn")["code"] == "zh"
    assert resolve("zh-Hant")["tag"] == "zh-Hant"
    assert resolve("ja")["name"] == "Japanese"
    assert resolve("kbt")["code"] == "kbt"
    accented = next(
        row for row in catalog() if row["name"] != unicodedata.normalize("NFC", row["name"])
    )
    assert resolve(unicodedata.normalize("NFC", accented["name"]))["name"] == accented["name"]


def test_language_api_search_and_limits(client_factory):
    client = client_factory()
    response = client.get("/api/languages", params={"q": "日本", "include_auto": True})
    assert response.status_code == 200
    assert any(item["code"] == "ja" for item in response.json()["items"])
    assert client.get("/api/languages", params={"limit": 1001}).status_code == 422
    assert client.get("/api/languages", params={"q": "x" * 101}).status_code == 422


def test_project_languages_normalize_before_validation(client_factory, register):
    client = client_factory()
    auth = register(client)
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    response = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "Film",
            "source_language": "日本語",
            "target_languages": ["cmn", "zh-Hant", "English"],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["source_language"] == "ja"
    assert response.json()["target_languages"] == ["zh", "zh-Hant", "en"]
    for targets in (["auto"], ["English", "en"], ["unknown-language"]):
        assert (
            client.post(
                "/api/projects", headers=headers, json={"name": "Film", "target_languages": targets}
            ).status_code
            == 422
        )


def test_default_catalog_includes_auto_and_manifest_hash_matches(client_factory):
    import hashlib
    import json
    from pathlib import Path

    from videotranslate.languages.catalog import catalog

    response = client_factory().get("/api/languages", params={"limit": 1000})
    assert response.json()["total"] == 647
    assert any(row["is_auto"] for row in response.json()["items"])
    data = Path(__file__).parents[1] / "src/videotranslate/languages/data"
    manifest = json.loads((data / "manifest.json").read_text())
    assert (
        hashlib.sha256((data / "catalog.json").read_bytes()).hexdigest()
        == manifest["catalog_sha256"]
    )
    source = Path(
        "/Users/moose/Documents/Codex/2026-10-28/ace-studio-3/work/video-translate-research/omnivoice/docs/languages.md"
    )
    if source.exists():
        import re

        assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest["source_sha256"]
        rows = re.findall(
            r"^\|\s*\d+\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|", source.read_text(), re.M
        )
        assert [(r["name"], r["code"], r["iso639_3"]) for r in catalog()[1:]] == rows
