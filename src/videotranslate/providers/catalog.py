"""Immutable declarations for the supported remote adapters; no runtime dispatch."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, get_args

from .contracts import AdapterId, ProviderCapabilities, ProviderRole

SLOTS = get_args(ProviderRole)
HF_ROUTER_ENDPOINT = "https://router.huggingface.co/v1"
MULTISTEM_SPACE = "teamup-tech/Demucs"
MULTISTEM_HOST = "https://teamup-tech-demucs.hf.space"
MULTISTEM_REVISION = "541b5b5bdee7e1eb6163d6f4e064e9e24f33c40c"


@dataclass(frozen=True)
class AdapterSpec:
    roles: tuple[ProviderRole, ...]
    credential_refs: tuple[str | None, ...]
    capabilities: ProviderCapabilities
    fixed_model: str | None = None
    fixed_space: str | None = None
    fixed_endpoint: str | None = None
    endpoint_optional: bool = True
    gradio_endpoint: str | None = None
    checked_space: str | None = None
    checked_capabilities: tuple[tuple[str, str | tuple[str, ...]], ...] = ()


_UNKNOWN = ProviderCapabilities(language_support="unknown", resumable=False, cancel_supported=False)
ADAPTERS: Mapping[AdapterId, AdapterSpec] = MappingProxyType(
    {
        "hf_router": AdapterSpec(
            ("translation", "verification"),
            ("huggingface",),
            _UNKNOWN,
            fixed_endpoint=HF_ROUTER_ENDPOINT,
        ),
        "openai_compatible": AdapterSpec(("translation",), ("translation", None), _UNKNOWN),
        "omnivoice": AdapterSpec(
            ("synthesis",),
            ("huggingface", None),
            ProviderCapabilities(
                language_support="unknown",
                resumable=True,
                cancel_supported=False,
                controls=("ns", "gs", "dn", "sp", "du", "pp", "po"),
            ),
            fixed_model="OmniVoice",
            gradio_endpoint="/_clone_fn",
            checked_space="k2-fsa/OmniVoice",
            checked_capabilities=(
                ("model_license", "CC-BY-NC"),
                ("upstream_code_license", "Apache-2.0"),
                ("model_source", "https://huggingface.co/k2-fsa/OmniVoice#license"),
            ),
        ),
        "demucs": AdapterSpec(
            ("separation",),
            (None,),
            ProviderCapabilities(
                language_support="unknown", resumable=True, cancel_supported=False
            ),
            fixed_model="htdemucs_ft",
            gradio_endpoint="/predict",
            checked_capabilities=(("outputs", ("vocals", "instrumental")),),
        ),
        "demucs_multistem": AdapterSpec(
            ("separation",),
            (None,),
            ProviderCapabilities(
                language_support="unknown", resumable=True, cancel_supported=False
            ),
            fixed_model="htdemucs",
            fixed_space=MULTISTEM_SPACE,
            fixed_endpoint=MULTISTEM_HOST,
            gradio_endpoint="/process",
        ),
        "nvidia_stream": AdapterSpec(
            ("transcription",),
            (None,),
            ProviderCapabilities(
                language_support="unsupported",
                resumable=False,
                cancel_supported=False,
                supported_languages=("en", "en-US", "en-GB"),
                max_duration_seconds=120,
                controls=("max_speakers",),
            ),
            fixed_model="nemotron-diarization",
            fixed_space="nvidia/nemotron-diarization",
            fixed_endpoint="https://nvidia-nemotron-diarization.hf.space",
            endpoint_optional=False,
        ),
        "hf_asr": AdapterSpec(
            ("transcription",), ("huggingface",), _UNKNOWN, fixed_endpoint=HF_ROUTER_ENDPOINT
        ),
    }
)
DEFAULT_ADAPTERS = MappingProxyType(
    {
        "separation": "demucs",
        "transcription": "nvidia_stream",
        "translation": "hf_router",
        "synthesis": "omnivoice",
        "verification": "hf_router",
    }
)
