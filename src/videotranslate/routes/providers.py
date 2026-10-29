"""Owner-controlled nonsecret provider settings and encrypted credentials."""

import re
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import APIError
from ..execution.inputs import set_inputs
from ..models.core import Project, Workspace, utcnow
from ..models.providers import ProviderConnection, ProviderConnectionRevision, WorkspaceCredential
from ..providers.network import validate_url
from ..providers.settings import SLOTS, capability_contract, preset_supported, validate_controls
from ..providers.vault import encrypt_credential
from ..security import Identity, require_csrf, require_identity

router = APIRouter(tags=["providers"])


class CredentialBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    token: SecretStr | None = None
    clear: bool = False

    @model_validator(mode="after")
    def validate_token(self):
        if self.token is not None and (self.clear or not self.token.get_secret_value().strip()):
            raise ValueError("Invalid credential operation")
        return self


class ProviderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    adapter: Literal["hf_router", "openai_compatible", "omnivoice", "demucs", "nvidia_stream"]
    endpoint: str | None = Field(default=None, max_length=300)
    space_id: str | None = Field(default=None, max_length=150)
    model: str | None = Field(default=None, max_length=200)
    controls: dict = Field(default_factory=dict)
    credential_ref: Literal["huggingface", "translation"] | None = None


def owner(identity):
    if identity.membership.role != "owner":
        raise APIError(403, "FORBIDDEN", "Owner access required")


def conflict():
    raise APIError(409, "REVISION_CONFLICT", "Settings changed; reload and try again")


def lock_workspace(db, workspace_id):
    db.execute(update(Workspace).where(Workspace.id == workspace_id).values(name=Workspace.name))


def safe_credential(row):
    return {
        "configured": bool(row and row.ciphertext),
        "revision": row.revision if row else 0,
        "updated_at": row.updated_at if row else None,
    }


@router.get("/provider-settings")
def get_settings(identity: Identity = Depends(require_identity), db: Session = Depends(get_db)):
    creds = db.scalars(
        select(WorkspaceCredential).where(WorkspaceCredential.workspace_id == identity.workspace.id)
    ).all()
    connections = db.scalars(
        select(ProviderConnection).where(ProviderConnection.workspace_id == identity.workspace.id)
    ).all()

    def safe_connection(connection):
        check = dict(connection.check_state) if connection.check_state else None
        credential_kind = connection.settings.get("credential_ref")
        if check and credential_kind:
            current = next((c.revision for c in creds if c.kind == credential_kind), 0)
            if check.get("credential_revision") != current:
                check["credentials_valid"] = None
        capabilities = capability_contract(connection.slot, connection.settings["adapter"])
        if check and isinstance(check.get("capabilities"), dict):
            capabilities.update(check["capabilities"])
        return {
            "revision": connection.revision,
            **connection.settings,
            "check_state": check,
            "capabilities": capabilities,
        }

    return {
        "credentials": {
            kind: safe_credential(next((c for c in creds if c.kind == kind), None))
            for kind in ("huggingface", "translation")
        },
        "providers": {
            slot: next(
                (safe_connection(c) for c in connections if c.slot == slot),
                {
                    "revision": 0,
                    "capabilities": capability_contract(
                        slot,
                        {
                            "separation": "demucs",
                            "transcription": "nvidia_stream",
                            "translation": "hf_router",
                            "synthesis": "omnivoice",
                            "verification": "hf_router",
                        }[slot],
                    ),
                },
            )
            for slot in SLOTS
        },
    }


@router.put("/credentials/{kind}")
def put_credential(
    kind: Literal["huggingface", "translation"],
    body: CredentialBody,
    request: Request,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    owner(identity)
    lock_workspace(db, identity.workspace.id)
    row = db.scalar(
        select(WorkspaceCredential).where(
            WorkspaceCredential.workspace_id == identity.workspace.id,
            WorkspaceCredential.kind == kind,
        )
    )
    if (row.revision if row else 0) != body.revision:
        conflict()
    ciphertext = (
        None
        if body.clear
        else (
            encrypt_credential(
                request.app.state.settings, identity.workspace.id, body.token.get_secret_value()
            )
            if body.token is not None
            else (row.ciphertext if row else None)
        )
    )
    if row is None:
        row = WorkspaceCredential(
            workspace_id=identity.workspace.id, kind=kind, revision=1, ciphertext=ciphertext
        )
        db.add(row)
    else:
        changed = db.execute(
            update(WorkspaceCredential)
            .where(WorkspaceCredential.id == row.id, WorkspaceCredential.revision == body.revision)
            .values(revision=body.revision + 1, ciphertext=ciphertext, updated_at=utcnow())
        )
        if changed.rowcount != 1:
            conflict()
        db.refresh(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        conflict()
    return safe_credential(row)


@router.put("/providers/{slot}")
def put_provider(
    slot: str,
    body: ProviderBody,
    request: Request,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    owner(identity)
    if slot not in SLOTS:
        raise APIError(404, "NOT_FOUND", "Resource not found")
    allowed_adapters = {
        "separation": {"demucs"},
        "transcription": {"nvidia_stream"},
        "translation": {"hf_router", "openai_compatible"},
        "synthesis": {"omnivoice"},
        "verification": {"hf_router"},
    }
    valid_refs = {
        "hf_router": {"huggingface"},
        "openai_compatible": {"translation", None},
        "omnivoice": {"huggingface", None},
        "demucs": {None},
        "nvidia_stream": {None},
    }
    if (
        body.adapter not in allowed_adapters[slot]
        or body.credential_ref not in valid_refs[body.adapter]
    ):
        raise APIError(422, "VALIDATION_ERROR", "Invalid provider configuration")
    if slot == "verification" and body.adapter == "hf_router" and body.model and ":" in body.model:
        raise APIError(422, "VALIDATION_ERROR", "Provider suffix is unsupported for verification")
    if not preset_supported(body.adapter, body.model, body.space_id, body.endpoint):
        raise APIError(422, "VALIDATION_ERROR", "Unsupported provider configuration")
    try:
        validate_controls(body.adapter, body.controls)
    except ValueError:
        raise APIError(422, "VALIDATION_ERROR", "Invalid provider controls") from None
    if body.space_id and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", body.space_id
    ):
        raise APIError(422, "VALIDATION_ERROR", "Invalid provider configuration")
    if body.endpoint:
        try:
            hosts = {
                h.strip().lower()
                for h in request.app.state.settings.provider_allowed_hosts.split(",")
                if h.strip()
            }
            validate_url(body.endpoint, allowed_hosts=hosts)
            parsed = urlsplit(body.endpoint)
            if (
                body.adapter == "hf_router"
                and body.endpoint.rstrip("/") != "https://router.huggingface.co/v1"
            ):
                raise ValueError()
            if body.adapter == "openai_compatible" and parsed.hostname not in hosts:
                raise ValueError()
        except ValueError:
            raise APIError(422, "VALIDATION_ERROR", "Invalid provider endpoint") from None
    row = db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.workspace_id == identity.workspace.id,
            ProviderConnection.slot == slot,
        )
    )
    if (row.revision if row else 0) != body.revision:
        conflict()
    values = body.model_dump(exclude={"revision"})
    if row is None:
        row = ProviderConnection(
            workspace_id=identity.workspace.id, slot=slot, revision=1, settings=values
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            conflict()
    else:
        result = db.execute(
            update(ProviderConnection)
            .where(ProviderConnection.id == row.id, ProviderConnection.revision == body.revision)
            .values(
                revision=body.revision + 1, settings=values, check_state=None, updated_at=utcnow()
            )
        )
        if result.rowcount != 1:
            conflict()
    db.add(
        ProviderConnectionRevision(
            workspace_id=identity.workspace.id,
            slot=slot,
            revision=body.revision + 1,
            settings=values,
        )
    )
    projects = db.scalars(
        select(Project)
        .where(Project.workspace_id == identity.workspace.id, Project.deleted_at.is_(None))
        .order_by(Project.id)
    ).all()
    for project in projects:
        set_inputs(db, project, {"provider." + slot: values})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        conflict()
    return {"revision": body.revision + 1, **values, "check_state": None}


class CheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)


@router.post("/providers/{slot}/check")
def check_provider(
    slot: str,
    body: CheckBody,
    request: Request,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    from ..providers.contracts import ProviderError
    from ..providers.gradio import discover_prefix, resolve_space, validate_endpoint_schema
    from ..providers.network import SafeHTTP
    from ..providers.vault import decrypt_credential

    owner(identity)
    row = db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.workspace_id == identity.workspace.id,
            ProviderConnection.slot == slot,
        )
    )
    if not row:
        raise APIError(404, "NOT_FOUND", "Resource not found")
    if row.revision != body.revision:
        conflict()
    values = row.settings
    credential = (
        db.scalar(
            select(WorkspaceCredential).where(
                WorkspaceCredential.workspace_id == identity.workspace.id,
                WorkspaceCredential.kind == values.get("credential_ref"),
            )
        )
        if values.get("credential_ref")
        else None
    )
    credential_revision = credential.revision if credential else 0
    required = values["adapter"] == "hf_router" or (
        values["adapter"] == "openai_compatible" and values.get("credential_ref") == "translation"
    )
    result = {
        "state": "not_checked",
        "reachable": None,
        "credentials_valid": None,
        "credential_revision": credential_revision,
        "inference_verified": False,
        "checked_at": utcnow().isoformat(),
        "capabilities": capability_contract(slot, values["adapter"]),
        "limits": {},
    }
    if values["adapter"] == "omnivoice":
        result["credential_mode"] = (
            "authenticated" if credential and credential.ciphertext else "public_demo"
        )
    if (
        slot == "verification"
        and values["adapter"] == "hf_router"
        and ":" in (values.get("model") or "")
    ):
        result["state"] = "configuration_required"
    elif not preset_supported(
        values["adapter"], values.get("model"), values.get("space_id"), values.get("endpoint")
    ):
        result["state"] = "configuration_required"
    elif required and not (credential and credential.ciphertext):
        result["state"] = "credential_required"
    elif values["adapter"] in {"hf_router", "openai_compatible"} and (
        not values.get("endpoint") or not values.get("model")
    ):
        result["state"] = "configuration_required"
    else:
        hosts = {
            h.strip().lower()
            for h in request.app.state.settings.provider_allowed_hosts.split(",")
            if h.strip()
        }
        runtime = request.app.state.settings
        client = SafeHTTP(
            allowed_hosts=hosts,
            proxy_url=runtime.provider_proxy_url.get_secret_value() or None,
            use_doh=runtime.provider_dns_over_https,
        )
        checking_account = False
        try:
            if values.get("space_id"):
                host = resolve_space(client, values["space_id"])
                if values.get("endpoint") and values["endpoint"].rstrip("/") != host:
                    raise ValueError("Space endpoint mismatch")
                if values["adapter"] in {"omnivoice", "demucs"}:
                    endpoint = "/_clone_fn" if values["adapter"] == "omnivoice" else "/predict"
                    import json

                    prefix = discover_prefix(client, host, endpoint)
                    schema = json.loads(
                        client.get(host + prefix + "/info", max_bytes=2 * 1024 * 1024)
                    )
                    validate_endpoint_schema(schema, values["adapter"])
                    result["capabilities"] = capability_contract(slot, values["adapter"], schema)
                    result["capabilities"]["api_prefix"] = prefix
                    if (
                        values["adapter"] == "omnivoice"
                        and values["space_id"] == "k2-fsa/OmniVoice"
                    ):
                        result["capabilities"].update(
                            {
                                "model_license": "CC-BY-NC",
                                "upstream_code_license": "Apache-2.0",
                                "model_source": "https://huggingface.co/k2-fsa/OmniVoice#license",
                                "controls": ["ns", "gs", "dn", "sp", "du", "pp", "po"],
                            }
                        )
                    if values["adapter"] == "demucs":
                        result["capabilities"].update({"outputs": ["vocals", "instrumental"]})
                elif values["adapter"] == "nvidia_stream":
                    import json

                    health = json.loads(client.get(host + "/health", max_bytes=65536))
                    config = json.loads(client.get(host + "/api/config", max_bytes=65536))
                    if health.get("ok") is not True or config.get("ready") is not True:
                        raise ValueError("Space health unavailable")
                    result["capabilities"] = capability_contract(slot, values["adapter"])
                    result["limits"] = {"max_duration_seconds": 120, "max_speakers": 8}
                else:
                    raise ValueError("Unsupported Space adapter")
            elif values["adapter"] == "hf_router":
                model = values.get("model") or ""
                match = re.fullmatch(
                    r"([A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*)(?::[A-Za-z0-9][A-Za-z0-9_.-]*)?",
                    model,
                )
                if not match:
                    raise ValueError("Model configuration required")
                model = match.group(1)
                import json

                metadata = json.loads(
                    client.get("https://huggingface.co/api/models/" + model, max_bytes=1024 * 1024)
                )
                if not isinstance(metadata, dict) or metadata.get("id") != model:
                    raise ValueError("Invalid model metadata")
            elif values.get("endpoint"):
                client.get(values["endpoint"], max_bytes=1024 * 1024)
            else:
                raise ValueError("Provider endpoint required")
            result["reachable"] = True
            result["state"] = "reachable"
            if (
                credential
                and credential.ciphertext
                and values.get("credential_ref") == "huggingface"
            ):
                token = decrypt_credential(
                    request.app.state.settings, identity.workspace.id, credential.ciphertext
                )
                checking_account = True
                client.get(
                    "https://huggingface.co/api/whoami-v2",
                    headers={"Authorization": "Bearer " + token},
                    max_bytes=256 * 1024,
                )
                result["credentials_valid"] = True
        except ProviderError as error:
            result["state"] = error.code
            if checking_account and error.code == "auth":
                result["credentials_valid"] = False
        except Exception:
            result["state"] = "check_failed"
        finally:
            client.close()
    # Serialize the final credential check with rotation, including creation of a new row.
    lock_workspace(db, identity.workspace.id)
    if values.get("credential_ref"):
        current_credential = (
            db.scalar(
                select(WorkspaceCredential.revision).where(
                    WorkspaceCredential.workspace_id == identity.workspace.id,
                    WorkspaceCredential.kind == values["credential_ref"],
                )
            )
            or 0
        )
        if current_credential != credential_revision:
            conflict()
    conditions = [ProviderConnection.id == row.id, ProviderConnection.revision == body.revision]
    if values.get("credential_ref"):
        credential_query = select(WorkspaceCredential.id).where(
            WorkspaceCredential.workspace_id == identity.workspace.id,
            WorkspaceCredential.kind == values["credential_ref"],
        )
        if credential_revision:
            conditions.append(
                credential_query.where(WorkspaceCredential.revision == credential_revision).exists()
            )
        else:
            conditions.append(~credential_query.exists())
    changed = db.execute(update(ProviderConnection).where(*conditions).values(check_state=result))
    if changed.rowcount != 1:
        conflict()
    db.commit()
    return result
