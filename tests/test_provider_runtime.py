"""Shared execution helpers retain provider and immutable-media policies."""

import ast
import hashlib
import importlib.util
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from videotranslate.execution.contracts import FailureCode, StageFailure
from videotranslate.providers.contracts import ProviderError, ProviderTerminalError


def test_shared_runtime_and_media_input_boundaries_exist():
    assert importlib.util.find_spec("videotranslate.execution.provider_runtime") is not None
    assert importlib.util.find_spec("videotranslate.execution.media_inputs") is not None


def test_remote_handlers_do_not_depend_on_sibling_stage_helpers():
    root = Path(__file__).parents[1] / "src/videotranslate/dubbing"
    for name in ("remote_translation", "remote_synthesis", "remote_voice_qc"):
        imports = [
            node
            for node in ast.walk(ast.parse((root / f"{name}.py").read_text()))
            if isinstance(node, ast.ImportFrom)
        ]
        assert not any(node.module in {"analysis", "remote_synthesis"} for node in imports)


def test_http_settings_and_context_share_allowlist_proxy_and_dns(monkeypatch):
    from videotranslate.execution.provider_runtime import http_for, make_http

    settings = SimpleNamespace(
        provider_allowed_hosts=" EXAMPLE.com, , Other.example ",
        provider_proxy_url=SecretStr("http://127.0.0.1:7890"),
        provider_dns_over_https=True,
    )
    seen = []
    monkeypatch.setattr("videotranslate.providers.network.SafeHTTP", lambda **kw: seen.append(kw))
    http_for(settings)
    make_http(SimpleNamespace(settings=settings))
    assert (
        seen
        == [
            {
                "allowed_hosts": {"example.com", "other.example"},
                "proxy_url": "http://127.0.0.1:7890",
                "use_doh": True,
            }
        ]
        * 2
    )


@pytest.mark.parametrize(
    "error,remote_id,phase,code,failed,retryable,review",
    [
        (ProviderTerminalError(), "job", "accepted", FailureCode.INVALID_MEDIA, True, False, False),
        (ProviderError("auth"), None, "submitting", FailureCode.AUTHENTICATION, True, False, False),
        (ProviderError("quota"), "job", "accepted", FailureCode.CONFIGURATION, False, False, False),
        (
            ProviderError("uncertain"),
            None,
            "submitting",
            FailureCode.SUBMISSION_UNCERTAIN,
            False,
            False,
            True,
        ),
        (ProviderError("network"), "job", "accepted", FailureCode.TRANSIENT, False, True, False),
        (ValueError(), None, "ready", FailureCode.INVALID_MEDIA, True, False, False),
        (ValueError(), "job", "accepted", FailureCode.INVALID_MEDIA, False, False, False),
    ],
)
def test_provider_failure_preserves_accepted_job_and_terminal_policies(
    error, remote_id, phase, code, failed, retryable, review
):
    from videotranslate.execution.provider_runtime import provider_failure

    failures = []
    operations = SimpleNamespace(
        failed=lambda: failures.append(True),
        current=lambda: SimpleNamespace(remote_id=remote_id, phase=phase),
    )
    result = provider_failure(operations, error)
    assert (result.code, result.retryable, result.review) == (code, retryable, review)
    assert bool(failures) is failed
    assert provider_failure(operations, RuntimeError()) is None


def test_hf_credential_policy_keeps_optional_and_invalid_credentials_distinct(monkeypatch):
    from videotranslate.execution.provider_runtime import credential_token

    project = SimpleNamespace(workspace_id="workspace")
    context = SimpleNamespace(settings=object())
    db = SimpleNamespace(scalar=lambda _: None)
    assert credential_token(db, project, context, {}) is None
    for config, code in [
        ({"credential_ref": "openai"}, FailureCode.CONFIGURATION),
        ({"credential_ref": "huggingface"}, FailureCode.AUTHENTICATION),
    ]:
        with pytest.raises(StageFailure) as caught:
            credential_token(db, project, context, config)
        assert caught.value.code == code
    db.scalar = lambda _: SimpleNamespace(ciphertext="encrypted")
    monkeypatch.setattr("videotranslate.providers.vault.decrypt_credential", lambda *args: "token")
    assert credential_token(db, project, context, {"credential_ref": "huggingface"}) == "token"

    def invalid(*args):
        raise ValueError()

    monkeypatch.setattr("videotranslate.providers.vault.decrypt_credential", invalid)
    with pytest.raises(StageFailure) as caught:
        credential_token(db, project, context, {"credential_ref": "huggingface"})
    assert caught.value.code == FailureCode.AUTHENTICATION


def test_materialize_preserves_hash_size_limit_and_chunk_cancellation(tmp_path):
    from videotranslate.execution.media_inputs import materialize

    data = b"a" * (1024 * 1024 + 1)
    checks = []
    context = SimpleNamespace(
        storage=SimpleNamespace(open=lambda _: BytesIO(data)),
        check_active=lambda: checks.append(True),
    )
    asset = SimpleNamespace(
        storage_key="object", byte_size=len(data), sha256=hashlib.sha256(data).hexdigest()
    )
    target = tmp_path / "source"
    materialize(context, asset, target, max_bytes=len(data))
    assert target.read_bytes() == data and len(checks) == 2
    for limit, size, code in [
        (len(data) - 1, len(data), FailureCode.MEDIA_LIMIT),
        (len(data), len(data) - 1, FailureCode.INVALID_MEDIA),
    ]:
        asset.byte_size = size
        with pytest.raises(StageFailure) as caught:
            materialize(context, asset, target, max_bytes=limit)
        assert caught.value.code == code
