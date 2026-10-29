"""Pure Gradio protocol parsing; remote paths remain opaque provider data."""

import json
import re

from .contracts import ProviderError, ProviderTerminalError


def parse_submission(data: dict) -> str:
    value = data.get("event_id") if isinstance(data, dict) else None
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
        raise ValueError("Provider returned no valid event ID")
    return value


def parse_sse(text: str):
    if len(text.encode()) > 1024 * 1024:
        raise ValueError("Provider event stream too large")
    for block in re.split(r"\r?\n\r?\n", text):
        event = None
        data = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        if event == "error":
            raise ProviderTerminalError()
        if event == "complete":
            try:
                return json.loads("\n".join(data))
            except (json.JSONDecodeError, ValueError):
                raise ProviderTerminalError() from None
    return None


class GradioClient:
    def __init__(self, http, base_url, prefix, *, hf_token=None):
        from urllib.parse import urlsplit

        from .network import validate_url

        validate_url(base_url, allowed_hosts=getattr(http, "allowed_hosts", set()))
        if hf_token and urlsplit(base_url).hostname != "k2-fsa-omnivoice.hf.space":
            raise ValueError("HF credential cannot be sent to this host")
        self.headers = {"Authorization": "Bearer " + hf_token} if hf_token else {}
        if prefix not in ("", "/gradio_api"):
            raise ValueError("Unsupported Gradio API prefix")
        self.http, self.base_url, self.prefix = http, base_url.rstrip("/"), prefix

    def _path(self, api_name):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", api_name):
            raise ValueError("Invalid Gradio API name")
        return f"{self.base_url}{self.prefix}/call/{api_name}"

    def upload(self, filename, content, content_type):
        paths = self.http.upload(
            self.base_url + self.prefix + "/upload",
            filename=filename,
            content=content,
            content_type=content_type,
            headers=self.headers,
        )
        return {
            "path": paths[0],
            "orig_name": filename,
            "mime_type": content_type,
            "meta": {"_type": "gradio.FileData"},
        }

    def download(self, file_data, *, max_bytes=64 * 1024 * 1024):
        from urllib.parse import quote

        if not isinstance(file_data, dict):
            raise ValueError("Invalid provider file")
        path = file_data.get("path")
        if (
            not isinstance(path, str)
            or not path
            or path.lower().startswith(("file:", "http:", "https:"))
            or any(ord(c) < 32 for c in path)
        ):
            raise ValueError("Invalid provider file")
        return self.http.download(
            self.base_url + self.prefix + "/file=" + quote(path, safe=""),
            max_bytes=max_bytes,
            headers=self.headers,
        )

    def submit(self, api_name, args):
        raw = self.http.post_json(
            self._path(api_name), {"data": args}, max_bytes=1024 * 1024, headers=self.headers
        )
        try:
            return parse_submission(json.loads(raw))
        except (ValueError, TypeError):
            raise ProviderError("uncertain") from None

    def poll(self, api_name, event_id):
        event_id = parse_submission({"event_id": event_id})
        content = self.http.get_sse(
            self._path(api_name) + "/" + event_id, max_bytes=1024 * 1024, headers=self.headers
        )
        try:
            return parse_sse(content.decode("utf-8"))
        except UnicodeDecodeError:
            raise ValueError("Invalid Gradio event stream") from None


def discover_prefix(http, base_url, endpoint):
    for prefix in ("/gradio_api", ""):
        try:
            schema = json.loads(
                http.get(base_url.rstrip("/") + prefix + "/info", max_bytes=2 * 1024 * 1024)
            )
            named = schema.get("named_endpoints", {})
            spec = named.get(endpoint)
            if (
                isinstance(spec, dict)
                and isinstance(spec.get("parameters"), list)
                and isinstance(spec.get("returns"), list)
            ):
                return prefix
        except ProviderError as error:
            if error.code != "configuration":
                raise
            continue
        except (ValueError, TypeError, AttributeError):
            continue
    raise ValueError("Provider schema unavailable or endpoint unsupported")


def resolve_space(http, space_id, *, expected_revision=None):
    from urllib.parse import urlsplit

    from .network import validate_url

    if not isinstance(space_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", space_id
    ):
        raise ValueError("Invalid Space ID")
    try:
        info = json.loads(
            http.get("https://huggingface.co/api/spaces/" + space_id, max_bytes=1024 * 1024)
        )
        if expected_revision is not None and info.get("sha") != expected_revision:
            raise ValueError()
        host = info["host"]
        if not isinstance(host, str):
            raise ValueError()
        validate_url(host)
        parts = urlsplit(host)
        if not (parts.hostname or "").endswith(".hf.space") or parts.path not in ("", "/"):
            raise ValueError()
        return host.rstrip("/")
    except ProviderError:
        raise
    except (ValueError, KeyError, TypeError):
        raise ValueError("Space host unavailable") from None


def validate_endpoint_schema(info, adapter):
    specs = {
        "omnivoice": (
            "/_clone_fn",
            [
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
            ],
            ["Audio", "Textbox"],
        ),
        "demucs": ("/predict", ["audio"], ["Audio", "Audio"]),
        "demucs_multistem": ("/process", ["input_0", "input_1"], ["Audio"] * 4),
    }
    if adapter not in specs:
        raise ValueError("Unsupported Gradio adapter")
    endpoint, parameters, outputs = specs[adapter]
    try:
        spec = info["named_endpoints"][endpoint]
        if [x["parameter_name"] for x in spec["parameters"]] != parameters or [
            x["component"] for x in spec["returns"]
        ] != outputs:
            raise ValueError()
        if adapter == "demucs" and [x.get("label") for x in spec["returns"]] != [
            "Vocals",
            "Instrumental",
        ]:
            raise ValueError()
        if adapter == "demucs_multistem":
            audio, model = spec["parameters"]
            if (
                [x.get("component") for x in spec["parameters"]] != ["Audio", "Dropdown"]
                or [x.get("label") for x in spec["returns"]] != ["Drums", "Bass", "Vocals", "Other"]
                or model["type"].get("type") != "string"
                or "htdemucs" not in model["type"].get("enum", [])
            ):
                raise ValueError()
            for item in [audio, *spec["returns"]]:
                data = item["type"]
                if (
                    data.get("type") != "object"
                    or data.get("title") != "FileData"
                    or data["properties"]["path"].get("type") != "string"
                    or "path" not in data.get("required", [])
                    or item["python_type"].get("type") != "filepath"
                ):
                    raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError("Incompatible provider schema") from None
