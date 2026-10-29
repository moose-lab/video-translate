"""Fernet encryption with purpose- and workspace-bound keys and payload."""

import base64
import json

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def _fernet(settings, workspace_id):
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=("videotranslate:credential:" + workspace_id).encode(),
    ).derive(settings.server_secret.get_secret_value().encode())
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_credential(settings, workspace_id, token):
    payload = json.dumps({"workspace_id": workspace_id, "token": token}).encode()
    return _fernet(settings, workspace_id).encrypt(payload).decode()


def decrypt_credential(settings, workspace_id, ciphertext):
    try:
        payload = json.loads(_fernet(settings, workspace_id).decrypt(ciphertext.encode()))
        if payload["workspace_id"] != workspace_id or not isinstance(payload["token"], str):
            raise ValueError("Credential ownership mismatch")
        return payload["token"]
    except (InvalidToken, KeyError, ValueError, TypeError):
        raise ValueError("Credential unavailable") from None
