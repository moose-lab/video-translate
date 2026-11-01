import pytest


def test_omnivoice_uses_exact_model_name_and_requires_real_audio_and_status():
    from videotranslate.providers.omnivoice import clone_arguments, normalize_result

    args = clone_arguments("hello", "ja", {"path": "/upload/ref.wav"}, "reference")
    assert args == [
        "hello",
        "Japanese",
        {"path": "/upload/ref.wav"},
        "reference",
        "",
        32,
        2.0,
        True,
        1.0,
        None,
        True,
        True,
    ]
    with pytest.raises(ValueError):
        clone_arguments("hello", "not-a-language", {"path": "/x"}, "")
    with pytest.raises(ValueError):
        normalize_result([None, "success"])
    with pytest.raises(ValueError):
        normalize_result([{"path": "/tmp/result.wav"}, "failed"])
    assert (
        normalize_result([{"path": "/tmp/result.wav"}, "Done."])["audio"]["path"]
        == "/tmp/result.wav"
    )


def test_gradio_sse_requires_event_id_and_terminal_completion():
    from videotranslate.providers.gradio import parse_sse, parse_submission

    with pytest.raises(ValueError):
        parse_submission({})
    assert parse_submission({"event_id": "abc"}) == "abc"
    assert parse_sse("event: heartbeat\ndata: null\n\nevent: generating\ndata: {}\n\n") is None
    assert parse_sse("event: complete\ndata: [1, 2]\n\n") == [1, 2]
    with pytest.raises(ValueError):
        parse_sse('event: error\ndata: "sensitive error"\n\n')


def test_translation_response_requires_exact_segment_ids_and_types():
    from videotranslate.providers.chat import normalize_translation

    result = normalize_translation(
        {"segments": [{"id": "a", "text": "你好"}, {"id": "b", "text": "世界"}]}, ["a", "b"]
    )
    assert result == {"a": "你好", "b": "世界"}
    for value in (
        {"segments": [{"id": "a", "text": "你好"}]},
        {"segments": [{"id": "a", "text": "a"}, {"id": "a", "text": "b"}]},
        {"segments": [{"id": "a", "text": 1}, {"id": "b", "text": "b"}]},
        "prose",
    ):
        with pytest.raises(ValueError):
            normalize_translation(value, ["a", "b"])


def test_asr_normalization_preserves_actual_timestamps_and_no_speakers():
    from videotranslate.providers.whisper import normalize_asr

    chunks = normalize_asr(
        {"text": "hello", "chunks": [{"text": "hello", "timestamp": [0.1, 0.8]}]}
    )
    assert chunks == [{"text": "hello", "start": 0.1, "end": 0.8}]
    for value in (
        {"text": "hello"},
        {"chunks": [{"text": "a", "timestamp": [1, None]}]},
        {"chunks": [{"text": "a", "timestamp": [2, 1]}]},
    ):
        with pytest.raises(ValueError):
            normalize_asr(value)


def test_omnivoice_selects_exact_current_space_enum_not_assumed_casing():
    from videotranslate.providers.omnivoice import model_name_from_enum

    assert model_name_from_enum("ldb", ["Du\u0303Ya"]) == "Du\u0303Ya"
    assert model_name_from_enum("ja", ["JAPANESE"]) == "JAPANESE"
    with pytest.raises(ValueError):
        model_name_from_enum("ja", ["Japanese", "JAPANESE"])
    with pytest.raises(ValueError):
        model_name_from_enum("ja", ["English"])


def test_remote_result_does_not_invent_a_pollable_id():
    from videotranslate.providers.contracts import ProviderCapabilities, RemoteResult

    result = RemoteResult(status="succeeded", payload={"text": "ok"})
    assert result.remote_id is None
    capability = ProviderCapabilities(
        language_support="unknown", resumable=False, cancel_supported=False
    )
    assert capability.inference_verified is False
    assert capability.resumable is False


def test_demucs_requires_two_distinct_stems():
    from videotranslate.providers.demucs import normalize_stems

    vocals = {"path": "/tmp/vocals.wav"}
    background = {"path": "/tmp/instrumental.wav"}
    assert normalize_stems([vocals, background]) == {"vocals": vocals, "instrumental": background}
    with pytest.raises(ValueError):
        normalize_stems([vocals, vocals])
    with pytest.raises(ValueError):
        normalize_stems([vocals, None])


def test_nvidia_preserves_real_final_timestamps_and_labels():
    from videotranslate.providers.nvidia_stream import normalize_final

    value = {
        "type": "result",
        "isFinal": True,
        "receivedAudioMs": 1000,
        "segments": [{"startTime": 0.1, "endTime": 0.8, "speaker": "speaker_2", "text": "hello"}],
    }
    assert normalize_final(value) == [
        {"start": 0.1, "end": 0.8, "speaker": "speaker_2", "text": "hello"}
    ]
    for bad in (
        {**value, "isFinal": False},
        {**value, "segments": [{"startTime": 2, "endTime": 1, "speaker": "s", "text": "x"}]},
    ):
        with pytest.raises(ValueError):
            normalize_final(bad)


def test_gradio_polls_same_real_event_id_without_resubmitting():
    from videotranslate.providers.gradio import GradioClient

    class Http:
        def __init__(self):
            self.posts = []
            self.gets = []

        def post_json(self, url, body, **kwargs):
            self.posts.append((url, body))
            return b'{"event_id":"remote123"}'

        def get_sse(self, url, **kwargs):
            self.gets.append(url)
            return (
                b"event: heartbeat\ndata: null\n\n"
                if len(self.gets) == 1
                else b'event: complete\ndata: ["finished"]\n\n'
            )

    http = Http()
    client = GradioClient(http, "https://test.hf.space", "/gradio_api")
    remote_id = client.submit("_clone_fn", ["hello"])
    assert remote_id == "remote123"
    assert client.poll("_clone_fn", remote_id) is None
    assert client.poll("_clone_fn", remote_id) == ["finished"]
    assert len(http.posts) == 1
    assert http.gets == ["https://test.hf.space/gradio_api/call/_clone_fn/remote123"] * 2


def test_gradio_detects_actual_prefix_from_valid_schema():
    from videotranslate.providers.gradio import discover_prefix

    class Http:
        def get(self, url, **kwargs):
            if "/gradio_api/" in url:
                raise ValueError("not found")
            return b'{"named_endpoints":{"/predict":{"parameters":[],"returns":[]}}}'

    assert discover_prefix(Http(), "https://test.hf.space", "/predict") == ""
    with pytest.raises(ValueError):
        discover_prefix(Http(), "https://test.hf.space", "/missing")


def test_nvidia_stream_protocol_sends_only_real_audio_and_requires_final():
    import json

    from videotranslate.providers.nvidia_stream import stream_file

    class WS:
        def __init__(self):
            self.sent = []
            self.messages = iter(
                [
                    json.dumps({"type": "ready"}),
                    json.dumps(
                        {"type": "result", "isFinal": False, "receivedAudioMs": 100, "segments": []}
                    ),
                    json.dumps(
                        {
                            "type": "result",
                            "isFinal": True,
                            "receivedAudioMs": 100,
                            "segments": [
                                {"startTime": 0, "endTime": 0.1, "speaker": "one", "text": "hello"}
                            ],
                        }
                    ),
                ]
            )

        def send(self, data):
            self.sent.append(data)

        def recv(self, timeout=None):
            return next(self.messages)

    ws = WS()
    pcm = b"\x01\x02" * 50000
    result = stream_file(ws, pcm, source_language="en", max_speakers=2)
    assert json.loads(ws.sent[0]) == {"type": "start", "sampleRateHz": 16000, "maxSpeakers": 2}
    assert b"".join(item for item in ws.sent if isinstance(item, bytes)) == pcm
    assert all(len(item) <= 65536 for item in ws.sent if isinstance(item, bytes))
    assert json.loads(ws.sent[-1]) == {"type": "end"}
    assert result[0]["speaker"] == "one"
    with pytest.raises(ValueError):
        stream_file(WS(), b"\x00" * 3840002, source_language="en", max_speakers=2)


def test_nvidia_connection_pins_public_address_and_does_not_send_origin(monkeypatch):
    import json

    from videotranslate.providers import nvidia_stream

    sent = []
    connected = []

    class Sock:
        def close(self):
            pass

    class WS:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send(self, value):
            sent.append(value)

        def recv(self, timeout=None):
            return (
                json.dumps({"type": "ready"})
                if len(sent) == 1
                else json.dumps(
                    {"type": "result", "isFinal": True, "receivedAudioMs": 1, "segments": []}
                )
            )

    def connect(uri, **kwargs):
        connected.append((uri, kwargs))
        return WS()

    monkeypatch.setattr(nvidia_stream, "resolve_public", lambda host: ["1.1.1.1"])
    monkeypatch.setattr(nvidia_stream.socket, "create_connection", lambda address, timeout: Sock())
    monkeypatch.setattr(nvidia_stream, "ws_connect", connect)
    assert nvidia_stream.stream_remote(b"\x00\x00", source_language="en", max_speakers=1) == []
    assert (
        connected[0][0] == "wss://nvidia-nemotron-diarization.hf.space/api/diarization/file/stream"
    )
    assert connected[0][1]["server_hostname"] == "nvidia-nemotron-diarization.hf.space"
    assert connected[0][1].get("origin") is None
    assert connected[0][1]["proxy"] is None


def test_nvidia_final_requires_reported_received_audio_time():
    from videotranslate.providers.nvidia_stream import normalize_final

    with pytest.raises(ValueError):
        normalize_final({"type": "result", "isFinal": True, "segments": []})
    with pytest.raises(ValueError):
        normalize_final(
            {
                "type": "result",
                "isFinal": True,
                "receivedAudioMs": 100,
                "segments": [{"startTime": 0, "endTime": 2, "speaker": "one", "text": "x"}],
            }
        )


def test_gradio_upload_constructs_filedata_from_remote_path():
    from videotranslate.providers.gradio import GradioClient

    class Http:
        def upload(self, url, **kwargs):
            assert url == "https://test.hf.space/gradio_api/upload"
            assert kwargs["content"] == b"fake-audio"
            return ["/tmp/provider/reference.wav"]

    result = GradioClient(Http(), "https://test.hf.space", "/gradio_api").upload(
        "ref.wav", b"fake-audio", "audio/wav"
    )
    assert result == {
        "path": "/tmp/provider/reference.wav",
        "orig_name": "ref.wav",
        "mime_type": "audio/wav",
        "meta": {"_type": "gradio.FileData"},
    }


def test_gradio_output_download_uses_provider_file_route_and_bounded_temp(tmp_path):
    from videotranslate.providers.gradio import GradioClient

    class Http:
        def download(self, url, **kwargs):
            assert url == "https://test.hf.space/gradio_api/file=%2Ftmp%2Faudio.wav"
            path = tmp_path / "download.wav"
            path.write_bytes(b"audio")
            return path

    client = GradioClient(Http(), "https://test.hf.space", "/gradio_api")
    assert client.download({"path": "/tmp/audio.wav"}).read_bytes() == b"audio"
    for path in ("file:///etc/passwd", "https://evil.example/x"):
        with pytest.raises(ValueError):
            client.download({"path": path})


def test_hf_translation_sends_explicit_ids_and_validates_reply():
    import json

    from videotranslate.providers.chat import translate

    class Http:
        def post_json(self, url, body, **kwargs):
            assert url == "https://router.huggingface.co/v1/chat/completions"
            assert kwargs["headers"]["Authorization"] == "Bearer hf_fake"
            assert body["model"] == "test/model"
            request = json.loads(body["messages"][1]["content"])
            assert request["target_language"] == "zh-Hant"
            assert request["segments"] == [{"id": "s1", "text": "hello"}]
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "target_language": "zh-Hant",
                                        "segments": [{"id": "s1", "text": "你好"}],
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()

    assert translate(
        Http(),
        model="test/model",
        token="hf_fake",
        target="zh-Hant",
        segments=[{"id": "s1", "text": "hello"}],
    ) == {"s1": "你好"}


def test_hf_credential_cannot_be_sent_to_custom_translation_host():
    from videotranslate.providers.chat import translate

    class Http:
        allowed_hosts = {"custom.example"}

        def post_json(self, *args, **kwargs):
            raise AssertionError("must not send")

    with pytest.raises(ValueError):
        translate(
            Http(),
            model="m",
            token="hf_fake",
            target="en",
            segments=[{"id": "a", "text": "x"}],
            endpoint="https://custom.example/v1",
        )


def test_omnivoice_official_space_status_is_done():
    from videotranslate.providers.omnivoice import normalize_result

    audio = {"path": "/tmp/generated.wav"}
    assert normalize_result([audio, "Done."])["audio"] == audio
    with pytest.raises(ValueError):
        normalize_result([audio, "Error: failure"])


def test_omnivoice_serializes_only_supported_controls_in_schema_order():
    from videotranslate.providers.omnivoice import clone_arguments

    args = clone_arguments(
        "hello",
        "en",
        {"path": "/upload/ref.wav"},
        "ref",
        controls={"ns": 48, "gs": 1.2, "dn": False, "sp": 1.1, "du": 3.0, "pp": False, "po": False},
    )
    assert args[5:] == [48, 1.2, False, 1.1, 3.0, False, False]
    with pytest.raises(ValueError):
        clone_arguments("hello", "en", {"path": "/x"}, "ref", controls={"seed": 1})


def test_gradio_optional_hf_credential_never_goes_to_non_hf_host():
    from videotranslate.providers.gradio import GradioClient

    class Http:
        allowed_hosts = {"custom.example"}

        def post_json(self, url, body, **kwargs):
            assert kwargs["headers"] == {"Authorization": "Bearer hf_fake"}
            return b'{"event_id":"job1"}'

    assert (
        GradioClient(
            Http(), "https://k2-fsa-omnivoice.hf.space", "/gradio_api", hf_token="hf_fake"
        ).submit("predict", [])
        == "job1"
    )
    with pytest.raises(ValueError):
        GradioClient(Http(), "https://custom.example", "", hf_token="hf_fake")


def test_gradio_preserves_uncertain_post_failure_without_retry():
    from videotranslate.providers.gradio import GradioClient

    class Http:
        def post_json(self, *args, **kwargs):
            raise ValueError("Provider submission outcome uncertain")

    with pytest.raises(ValueError, match="uncertain"):
        GradioClient(Http(), "https://test.hf.space", "").submit("predict", [])


def test_hf_asr_sends_base64_with_timestamps_to_official_router():
    import base64

    from videotranslate.providers.whisper import transcribe

    class Http:
        def post_json(self, url, body, **kwargs):
            assert (
                url == "https://router.huggingface.co/hf-inference/models/openai/whisper-large-v3"
            )
            assert body == {
                "inputs": base64.b64encode(b"fake-audio").decode(),
                "parameters": {"return_timestamps": True},
            }
            assert kwargs["headers"]["Authorization"] == "Bearer hf_fake"
            return b'{"text":"hello","chunks":[{"text":"hello","timestamp":[0,1]}]}'

    assert transcribe(
        Http(), audio=b"fake-audio", model="openai/whisper-large-v3", token="hf_fake"
    ) == [{"text": "hello", "start": 0, "end": 1}]


def test_resolve_space_uses_validated_official_metadata_host():
    from videotranslate.providers.gradio import resolve_space

    class Http:
        def get(self, url, **kwargs):
            assert url == "https://huggingface.co/api/spaces/k2-fsa/OmniVoice"
            return b'{"host":"https://k2-fsa-omnivoice.hf.space"}'

    assert resolve_space(Http(), "k2-fsa/OmniVoice") == "https://k2-fsa-omnivoice.hf.space"

    class Missing:
        def get(self, *args, **kwargs):
            return b"{}"

    with pytest.raises(ValueError):
        resolve_space(Missing(), "k2-fsa/OmniVoice")
    with pytest.raises(ValueError):
        resolve_space(Http(), "../private")


def test_gradio_schema_rejects_incompatible_parameter_and_output_order():
    from videotranslate.providers.gradio import validate_endpoint_schema

    names = [
        "text",
        "lang",
        "ref_aud",
        "ref_text",
        "instruct",
        "ns",
        "gs",
        "dn",
        "sp",
        "du",
        "pp",
        "po",
    ]
    info = {
        "named_endpoints": {
            "/_clone_fn": {
                "parameters": [{"parameter_name": n} for n in names],
                "returns": [{"component": "Audio"}, {"component": "Textbox"}],
            }
        }
    }
    validate_endpoint_schema(info, "omnivoice")
    info["named_endpoints"]["/_clone_fn"]["parameters"][1]["parameter_name"] = "wrong"
    with pytest.raises(ValueError):
        validate_endpoint_schema(info, "omnivoice")


def test_omnivoice_rejects_url_and_local_file_reference():
    from videotranslate.providers.omnivoice import clone_arguments

    for path in ("file:///etc/passwd", "https://evil.example/audio.wav"):
        with pytest.raises(ValueError):
            clone_arguments("hello", "en", {"path": path}, "ref")


def test_omnivoice_submits_real_event_id_with_space_schema_and_uploaded_reference():
    import json

    from videotranslate.providers.omnivoice import submit_clone

    class Http:
        allowed_hosts = set()

        def get(self, url, **kwargs):
            if "/api/spaces/" in url:
                return b'{"host":"https://k2-fsa-omnivoice.hf.space"}'
            names = [
                "text",
                "lang",
                "ref_aud",
                "ref_text",
                "instruct",
                "ns",
                "gs",
                "dn",
                "sp",
                "du",
                "pp",
                "po",
            ]
            params = [{"parameter_name": n} for n in names]
            params[1]["type"] = {"enum": ["Japanese"]}
            return json.dumps(
                {
                    "named_endpoints": {
                        "/_clone_fn": {
                            "parameters": params,
                            "returns": [{"component": "Audio"}, {"component": "Textbox"}],
                        }
                    }
                }
            ).encode()

        def upload(self, url, **kwargs):
            return ["/tmp/provider/ref.wav"]

        def post_json(self, url, body, **kwargs):
            assert url == "https://k2-fsa-omnivoice.hf.space/gradio_api/call/_clone_fn"
            assert body["data"][1] == "Japanese"
            assert body["data"][2]["path"] == "/tmp/provider/ref.wav"
            return b'{"event_id":"real-remote-id"}'

    result = submit_clone(
        Http(),
        text="hi",
        language="ja",
        reference_audio=b"fake-audio",
        filename="ref.wav",
        reference_text="hi",
    )
    assert result.remote_id == "real-remote-id"
    assert result.status == "pending"


def test_omnivoice_does_not_upload_when_text_or_controls_invalid():
    import json

    from videotranslate.providers.omnivoice import submit_clone

    class Http:
        allowed_hosts = set()

        def get(self, url, **kwargs):
            if "/api/spaces/" in url:
                return b'{"host":"https://k2-fsa-omnivoice.hf.space"}'
            names = [
                "text",
                "lang",
                "ref_aud",
                "ref_text",
                "instruct",
                "ns",
                "gs",
                "dn",
                "sp",
                "du",
                "pp",
                "po",
            ]
            params = [{"parameter_name": n} for n in names]
            params[1]["type"] = {"enum": ["Japanese"]}
            return json.dumps(
                {
                    "named_endpoints": {
                        "/_clone_fn": {
                            "parameters": params,
                            "returns": [{"component": "Audio"}, {"component": "Textbox"}],
                        }
                    }
                }
            ).encode()

        def upload(self, *args, **kwargs):
            raise AssertionError("must not upload invalid request")

    with pytest.raises(ValueError):
        submit_clone(
            Http(),
            text="",
            language="ja",
            reference_audio=b"x",
            filename="ref.wav",
            reference_text="",
        )


def test_omnivoice_poll_validates_status_before_copying_audio(tmp_path):
    import json

    from videotranslate.providers.contracts import RemoteResult
    from videotranslate.providers.omnivoice import poll_clone

    class Http:
        allowed_hosts = set()

        def get_sse(self, url, **kwargs):
            return (
                "event: complete\ndata: "
                + json.dumps([{"path": "/tmp/audio.wav"}, "Done."])
                + "\n\n"
            ).encode()

        def download(self, url, **kwargs):
            p = tmp_path / "audio"
            p.write_bytes(b"audio")
            return p

    handle = RemoteResult(
        status="pending",
        remote_id="job",
        payload={"host": "https://test.hf.space", "prefix": "/gradio_api"},
    )
    result = poll_clone(Http(), handle)
    assert result.status == "succeeded" and result.remote_id == "job"
    assert result.payload["local_audio_path"] == str(tmp_path / "audio")


def test_demucs_submits_and_polls_two_real_stems(tmp_path):
    import json

    from videotranslate.providers.demucs import poll_separation, submit_separation

    class Http:
        allowed_hosts = set()

        def get(self, url, **kwargs):
            if "/api/spaces/" in url:
                return b'{"host":"https://kajise-demucs-v4-ft-2s.hf.space"}'
            if "/gradio_api/" in url:
                raise ValueError("not found")
            return b'{"named_endpoints":{"/predict":{"parameters":[{"parameter_name":"audio"}],"returns":[{"component":"Audio","label":"Vocals"},{"component":"Audio","label":"Instrumental"}]}}}'

        def upload(self, url, **kwargs):
            return ["/tmp/source.wav"]

        def post_json(self, url, body, **kwargs):
            assert url.endswith("/call/predict")
            return b'{"event_id":"demucs-1"}'

        def get_sse(self, url, **kwargs):
            return (
                "event: complete\ndata: "
                + json.dumps([{"path": "/tmp/vocals.wav"}, {"path": "/tmp/instrumental.wav"}])
                + "\n\n"
            ).encode()

        def download(self, url, **kwargs):
            p = tmp_path / ("vocals" if "vocals" in url else "instrumental")
            p.write_bytes(b"audio")
            return p

    http = Http()
    handle = submit_separation(http, audio=b"fake-audio", filename="source.wav")
    assert handle.remote_id == "demucs-1"
    result = poll_separation(http, handle)
    assert result.status == "succeeded"
    assert result.payload["vocals_path"] != result.payload["instrumental_path"]


def test_demucs_cleans_first_temp_if_second_download_fails(tmp_path):
    import json

    from videotranslate.providers.contracts import RemoteResult
    from videotranslate.providers.demucs import poll_separation

    first = tmp_path / "vocals"
    calls = 0

    class Http:
        allowed_hosts = set()

        def get_sse(self, *args, **kwargs):
            return (
                "event: complete\ndata: "
                + json.dumps([{"path": "/tmp/a.wav"}, {"path": "/tmp/b.wav"}])
                + "\n\n"
            ).encode()

        def download(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                first.write_bytes(b"audio")
                return first
            raise ValueError("download failure")

    with pytest.raises(ValueError):
        poll_separation(
            Http(),
            RemoteResult(
                status="pending",
                remote_id="job",
                payload={"host": "https://test.hf.space", "prefix": ""},
            ),
        )
    assert not first.exists()


def test_gradio_malformed_submission_is_safely_rejected():
    from videotranslate.providers.gradio import parse_submission

    for value in (None, [], {"event_id": ""}, {"event_id": "../../other"}):
        with pytest.raises(ValueError):
            parse_submission(value)


def test_demucs_schema_rejects_reversed_stem_labels():
    from videotranslate.providers.gradio import validate_endpoint_schema

    info = {
        "named_endpoints": {
            "/predict": {
                "parameters": [{"parameter_name": "audio"}],
                "returns": [
                    {"component": "Audio", "label": "Instrumental"},
                    {"component": "Audio", "label": "Vocals"},
                ],
            }
        }
    }
    with pytest.raises(ValueError):
        validate_endpoint_schema(info, "demucs")


def test_hf_key_is_not_sent_to_unrelated_public_space():
    from videotranslate.providers.gradio import GradioClient

    class Http:
        allowed_hosts = set()

    with pytest.raises(ValueError):
        GradioClient(Http(), "https://unrelated.hf.space", "", hf_token="hf_fake")


def test_nvidia_can_use_admin_proxy_and_doh_without_changing_sni(monkeypatch):
    import json

    from videotranslate.providers import nvidia_stream

    calls = []
    sent = []

    class Sock:
        def close(self):
            pass

    class WS:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send(self, value):
            sent.append(value)

        def recv(self, timeout=None):
            return (
                json.dumps({"type": "ready"})
                if len(sent) == 1
                else json.dumps(
                    {"type": "result", "isFinal": True, "receivedAudioMs": 1, "segments": []}
                )
            )

    monkeypatch.setattr(nvidia_stream, "resolve_doh", lambda host, proxy: ["1.1.1.1"])
    monkeypatch.setattr(
        nvidia_stream,
        "open_proxy_tunnel",
        lambda proxy, ip, port, timeout: (calls.append((proxy, ip, port)), Sock())[1],
    )
    monkeypatch.setattr(nvidia_stream, "ws_connect", lambda uri, **kwargs: WS())
    assert (
        nvidia_stream.stream_remote(
            b"\x00\x00",
            source_language="en",
            max_speakers=1,
            proxy_url="http://127.0.0.1:7897",
            use_doh=True,
        )
        == []
    )
    assert calls == [("http://127.0.0.1:7897", "1.1.1.1", 443)]


def test_custom_translation_may_use_explicitly_uncredentialed_host():
    import json

    from videotranslate.providers.chat import translate

    class Http:
        allowed_hosts = {"custom.example"}

        def post_json(self, url, body, **kwargs):
            assert kwargs["headers"] == {}
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "target_language": "en",
                                        "segments": [{"id": "a", "text": "hello"}],
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()

    assert translate(
        Http(),
        model="custom-model",
        token=None,
        target="en",
        segments=[{"id": "a", "text": "x"}],
        endpoint="https://custom.example/v1",
        credential_kind="translation",
    ) == {"a": "hello"}


def test_hf_asr_model_identifier_rejects_traversal():
    from videotranslate.providers.whisper import transcribe

    class Http:
        def post_json(self, *args, **kwargs):
            raise AssertionError("invalid model must not be sent")

    for model in ("../..", "openai/..", "/etc/passwd"):
        with pytest.raises(ValueError):
            transcribe(Http(), audio=b"audio", model=model, token="hf_fake")


def test_remote_output_paths_cannot_be_urls_or_file_uris():
    from videotranslate.providers.demucs import normalize_stems
    from videotranslate.providers.omnivoice import normalize_result

    for path in ("FILE:///tmp/x.wav", "HTTPS://evil.example/x.wav"):
        with pytest.raises(ValueError):
            normalize_result([{"path": path}, "Done."])
        with pytest.raises(ValueError):
            normalize_stems([{"path": path}, {"path": "/tmp/other.wav"}])


def test_nvidia_rejects_unsupported_source_before_network(monkeypatch):
    from videotranslate.providers import nvidia_stream

    monkeypatch.setattr(
        nvidia_stream,
        "resolve_public",
        lambda host: (_ for _ in ()).throw(AssertionError("must not connect")),
    )
    with pytest.raises(ValueError):
        nvidia_stream.stream_remote(b"\0\0", source_language="ja")


def test_nvidia_distinguishes_unsent_from_uncertain_stream_failure():
    from videotranslate.providers.contracts import ProviderError
    from videotranslate.providers.nvidia_stream import stream_file

    class WS:
        def send(self, value):
            raise OSError("raw provider error")

        def recv(self, timeout=None):
            raise AssertionError()

    with pytest.raises(ProviderError) as error:
        stream_file(WS(), b"\0\0", source_language="en")
    assert error.value.code == "uncertain"
    assert "raw provider error" not in str(error.value)
    with pytest.raises(ValueError) as invalid:
        stream_file(WS(), b"", source_language="en")
    assert not isinstance(invalid.value, ProviderError) or invalid.value.code != "uncertain"


def test_unsupported_preset_model_is_rejected_before_any_remote_requests():
    from videotranslate.providers.demucs import submit_separation
    from videotranslate.providers.omnivoice import submit_clone

    class Http:
        def get(self, *args, **kwargs):
            raise AssertionError("must not contact service")

    with pytest.raises(ValueError):
        submit_clone(
            Http(),
            text="x",
            language="en",
            reference_audio=b"fake",
            filename="x.wav",
            reference_text="x",
            model="different",
        )
    with pytest.raises(ValueError):
        submit_separation(Http(), audio=b"fake", filename="x.wav", model="different")


def test_nvidia_unsent_connection_failure_has_network_code(monkeypatch):
    from videotranslate.providers import nvidia_stream
    from videotranslate.providers.contracts import ProviderError

    monkeypatch.setattr(nvidia_stream, "resolve_public", lambda host: ["1.1.1.1"])
    monkeypatch.setattr(
        nvidia_stream.socket,
        "create_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("sensitive error")),
    )
    with pytest.raises(ProviderError) as error:
        nvidia_stream.stream_remote(b"\0\0", source_language="en")
    assert error.value.code == "network" and "sensitive error" not in str(error.value)


def test_nvidia_rejects_unimplemented_model_before_network(monkeypatch):
    from videotranslate.providers import nvidia_stream

    monkeypatch.setattr(
        nvidia_stream,
        "resolve_public",
        lambda host: (_ for _ in ()).throw(AssertionError("must not connect")),
    )
    with pytest.raises(ValueError):
        nvidia_stream.stream_remote(b"\0\0", source_language="en", model="wrong")


def test_nvidia_requires_explicit_source_language_before_connect(monkeypatch):
    from videotranslate.providers import nvidia_stream

    monkeypatch.setattr(
        nvidia_stream,
        "resolve_public",
        lambda host: (_ for _ in ()).throw(AssertionError("must not connect")),
    )
    with pytest.raises(TypeError):
        nvidia_stream.stream_remote(b"\0\0")


def test_nvidia_failure_closing_a_submitted_stream_is_uncertain(monkeypatch):
    import json

    from videotranslate.providers import nvidia_stream
    from videotranslate.providers.contracts import ProviderError

    sent = []

    class Socket:
        def close(self):
            pass

    class WS:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            raise OSError("disconnect details")

        def send(self, value):
            sent.append(value)

        def recv(self, timeout=None):
            return (
                json.dumps({"type": "ready"})
                if len(sent) == 1
                else json.dumps(
                    {"type": "result", "isFinal": True, "receivedAudioMs": 1, "segments": []}
                )
            )

    monkeypatch.setattr(nvidia_stream, "resolve_public", lambda host: ["1.1.1.1"])
    monkeypatch.setattr(nvidia_stream.socket, "create_connection", lambda *args, **kwargs: Socket())
    monkeypatch.setattr(nvidia_stream, "ws_connect", lambda *args, **kwargs: WS())
    with pytest.raises(ProviderError) as error:
        nvidia_stream.stream_remote(b"\0\0", source_language="en")
    assert error.value.code == "uncertain"


def test_gradio_submission_without_real_event_id_is_uncertain():
    from videotranslate.providers.contracts import ProviderError
    from videotranslate.providers.gradio import GradioClient

    class Http:
        def post_json(self, *args, **kwargs):
            return b"{}"

    with pytest.raises(ProviderError) as error:
        GradioClient(Http(), "https://test.hf.space", "").submit("predict", [])
    assert error.value.code == "uncertain"


def test_demucs_preparation_does_not_submit_paid_named_call():
    from videotranslate.providers.demucs import prepare_separation, submit_prepared

    class Recording:
        allowed_hosts = set()

        def __init__(self):
            self.calls = []

        def get(self, url, **kw):
            self.calls.append(("GET", url))
            if "api/spaces" in url:
                return b'{"host":"https://demucs-test.hf.space"}'
            return b'{"named_endpoints":{"/predict":{"parameters":[{"parameter_name":"audio"}],"returns":[{"component":"Audio","label":"Vocals"},{"component":"Audio","label":"Instrumental"}]}}}'

        def upload(self, url, **kw):
            self.calls.append(("UPLOAD", url))
            assert kw["filename"] == "audio.wav"
            return ["/tmp/upload.wav"]

        def post_json(self, url, body, **kw):
            self.calls.append(("POST", url))
            return b'{"event_id":"actual-42"}'

    http = Recording()
    prepared = prepare_separation(http, audio=b"test audio", space_id="test/demucs")
    assert not any(method == "POST" for method, _ in http.calls)
    assert prepared.host == "https://demucs-test.hf.space"
    assert submit_prepared(http, prepared) == "actual-42"
    assert http.calls[-1] == ("POST", "https://demucs-test.hf.space/gradio_api/call/predict")


def test_gradio_terminal_failure_distinct_from_pending_network():
    from videotranslate.providers.contracts import ProviderTerminalError
    from videotranslate.providers.gradio import parse_sse

    assert parse_sse("event: generating\ndata: null\n\n") is None
    with pytest.raises(ProviderTerminalError):
        parse_sse("event: error\ndata: provider-private-error\n\n")
    with pytest.raises(ProviderTerminalError):
        parse_sse("event: complete\ndata: not json\n\n")


def test_hf_source_preserves_only_actually_returned_language_metadata():
    import json

    from videotranslate.providers.whisper import transcribe

    class HTTP:
        def __init__(self, language):
            self.language = language

        def post_json(self, url, body, **kw):
            value = {"chunks": [{"text": "exact words", "timestamp": [0, 1]}]}
            if self.language is not None:
                value["language"] = self.language
            return json.dumps(value).encode()

    assert (
        transcribe(
            HTTP(None), audio=b"audio", model="test/model", token="fake", include_metadata=True
        )["detected_language"]
        is None
    )
    assert (
        transcribe(
            HTTP("ja"), audio=b"audio", model="test/model", token="fake", include_metadata=True
        )["detected_language"]
        == "ja"
    )
