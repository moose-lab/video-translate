import pytest


def test_url_policy_denies_private_credentials_non_https_and_unknown_hosts():
    from videotranslate.providers.network import validate_url

    assert validate_url("https://router.huggingface.co/v1") == "https://router.huggingface.co/v1"
    for url in [
        "http://router.huggingface.co/",
        "https://user:pass@router.huggingface.co/",
        "https://router.huggingface.co/#fragment",
        "https://127.0.0.1/",
        "https://evil.example/",
        "https://router.huggingface.co:444/",
        "https://router.huggingface.co/?token=secret",
        "file:///tmp/audio",
    ]:
        with pytest.raises(ValueError):
            validate_url(url)
    assert (
        validate_url("https://custom.example/v1", allowed_hosts={"custom.example"})
        == "https://custom.example/v1"
    )
