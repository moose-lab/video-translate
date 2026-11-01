"""Shared provider transport, failure mapping, and Hugging Face credentials."""

from .contracts import FailureCode, StageFailure


def http_for(settings):
    from ..providers.network import SafeHTTP

    runtime = settings
    return SafeHTTP(
        allowed_hosts={
            host.strip().lower()
            for host in runtime.provider_allowed_hosts.split(",")
            if host.strip()
        },
        proxy_url=runtime.provider_proxy_url.get_secret_value() or None,
        use_doh=runtime.provider_dns_over_https,
    )


def make_http(context):
    return http_for(context.settings)


def provider_failure(operations, error):
    from ..providers.contracts import ProviderError, ProviderTerminalError

    if isinstance(error, ProviderTerminalError):
        operations.failed()
        return StageFailure(FailureCode.INVALID_MEDIA)
    if isinstance(error, ProviderError):
        if error.code in {"auth", "quota", "configuration", "invalid_response"}:
            operation = operations.current()
            # Poll/download access failures say nothing about an accepted job's outcome.
            if operation and not operation.remote_id and operation.phase == "submitting":
                operations.failed()
            return StageFailure(
                FailureCode.AUTHENTICATION if error.code == "auth" else FailureCode.CONFIGURATION
            )
        if error.code == "uncertain":
            return StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)
        return StageFailure(FailureCode.TRANSIENT, retryable=True)
    # A received but invalid terminal result must never be polled indefinitely.
    if isinstance(error, ValueError):
        operation = operations.current()
        if operation and not operation.remote_id:
            operations.failed()
        # Malformed/non-UTF8 polling transport is not an authoritative terminal event.
        return StageFailure(FailureCode.INVALID_MEDIA)
    return None


def credential_token(db, project, context, config):
    from sqlalchemy import select

    from ..models.providers import WorkspaceCredential
    from ..providers.vault import decrypt_credential

    kind = config.get("credential_ref")
    if kind not in {None, "huggingface"}:
        raise StageFailure(FailureCode.CONFIGURATION)
    if not kind:
        return None
    credential = db.scalar(
        select(WorkspaceCredential).where(
            WorkspaceCredential.workspace_id == project.workspace_id,
            WorkspaceCredential.kind == kind,
        )
    )
    if not credential or not credential.ciphertext:
        raise StageFailure(FailureCode.AUTHENTICATION)
    try:
        return decrypt_credential(context.settings, project.workspace_id, credential.ciphertext)
    except ValueError:
        raise StageFailure(FailureCode.AUTHENTICATION) from None
