"""Provider modules expose the durable execution path without obsolete helpers."""

import importlib

import pytest


@pytest.mark.parametrize(
    "module,name",
    [
        ("chat", "translate"),
        ("omnivoice", "submit_clone"),
        ("omnivoice", "poll_clone"),
        ("demucs", "submit_separation"),
        ("demucs", "poll_separation"),
        ("contracts", "RemoteResult"),
    ],
)
def test_obsolete_unfenced_provider_helpers_are_absent(module, name):
    provider = importlib.import_module("videotranslate.providers." + module)
    assert not hasattr(provider, name)
