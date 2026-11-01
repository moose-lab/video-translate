"""Provider declarations and semantic import boundaries stay explicit and immutable."""

import importlib
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import get_args

import pytest


def test_catalog_covers_http_adapter_ids_and_role_credential_contracts():
    from videotranslate.providers import catalog
    from videotranslate.providers.contracts import AdapterId, ProviderRole
    from videotranslate.routes.providers import ProviderBody

    assert set(catalog.ADAPTERS) == set(get_args(AdapterId))
    assert list(get_args(ProviderBody.model_fields["adapter"].annotation)) == list(
        get_args(AdapterId)
    )
    assert tuple(get_args(ProviderRole)) == catalog.SLOTS
    assert {
        role: {adapter for adapter, spec in catalog.ADAPTERS.items() if role in spec.roles}
        for role in catalog.SLOTS
    } == {
        "separation": {"demucs", "demucs_multistem"},
        "transcription": {"nvidia_stream", "hf_asr"},
        "translation": {"hf_router", "openai_compatible"},
        "synthesis": {"omnivoice"},
        "verification": {"hf_router"},
    }
    assert catalog.ADAPTERS["hf_router"].credential_refs == ("huggingface",)
    assert catalog.ADAPTERS["openai_compatible"].credential_refs == ("translation", None)
    with pytest.raises(TypeError):
        catalog.ADAPTERS["new"] = catalog.ADAPTERS["hf_router"]
    with pytest.raises(FrozenInstanceError):
        catalog.ADAPTERS["hf_router"].roles = ()


def test_chat_and_whisper_have_separate_implementation_boundaries():
    chat = importlib.import_module("videotranslate.providers.chat")
    whisper = importlib.import_module("videotranslate.providers.whisper")
    assert callable(chat.structured_chat)
    assert callable(chat.normalize_translation)
    assert callable(whisper.transcribe)
    assert callable(whisper.normalize_asr)
    assert not hasattr(chat, "transcribe")
    assert not hasattr(whisper, "structured_chat")
    assert not Path(chat.__file__).with_name("hf_router.py").exists()
