"""Armazenamento de tokens das redes sociais por usuário.

Os tokens ficam só no servidor do worker, nunca no app web. Os arquivos são
criptografados com Fernet (AES) quando TOKENS_ENCRYPTION_KEY está definido.
A chave `owner` identifica o dono: o e-mail do usuário no SaaS, ou "default"
no modo local.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import config

try:
    from cryptography.fernet import Fernet
except ImportError:  # pragma: no cover
    Fernet = None  # type: ignore

_KEY = config.env("TOKENS_ENCRYPTION_KEY")


def _path(platform: str, owner: str) -> Path:
    h = hashlib.sha256(owner.strip().lower().encode()).hexdigest()[:32]
    d = config.TOKENS_DIR / platform
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{h}.json"


def save(platform: str, owner: str, data: dict) -> None:
    raw = json.dumps(data).encode()
    if _KEY and Fernet:
        raw = Fernet(_KEY.encode()).encrypt(raw)
    p = _path(platform, owner)
    p.write_bytes(raw)
    p.chmod(0o600)


def load(platform: str, owner: str) -> dict | None:
    p = _path(platform, owner)
    if not p.exists():
        return None
    raw = p.read_bytes()
    if _KEY and Fernet and not raw.lstrip().startswith(b"{"):
        raw = Fernet(_KEY.encode()).decrypt(raw)
    return json.loads(raw)


def delete(platform: str, owner: str) -> None:
    _path(platform, owner).unlink(missing_ok=True)


def delete_all(owner: str) -> None:
    for platform in ("youtube", "tiktok", "instagram"):
        delete(platform, owner)
