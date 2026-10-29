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
