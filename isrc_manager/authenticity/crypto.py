"""Ed25519 key management helpers for authenticity manifests."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing-only imports
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
else:  # pragma: no cover - fallback aliases when cryptography is optional
    Ed25519PrivateKey = Any
    Ed25519PublicKey = Any

try:  # pragma: no cover - optional dependency import boundary
    from cryptography.hazmat.primitives import (
        hashes as _hashes,
    )
    from cryptography.hazmat.primitives import (
        serialization as _serialization,
    )
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey as _Ed25519PrivateKey,
    )
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey as _Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF as _HKDF
except ModuleNotFoundError as exc:  # pragma: no cover - environment-specific fallback
    if exc.name != "cryptography":
        raise
    _CRYPTOGRAPHY_IMPORT_ERROR = exc
    _hashes = None
    _serialization = None
    _Ed25519PrivateKey = None
    _Ed25519PublicKey = None
    _HKDF = None
else:  # pragma: no cover - imported when dependency is present
    _CRYPTOGRAPHY_IMPORT_ERROR = None

WATERMARK_KEY_INFO = b"isrcm-watermark-v1"


def cryptography_available() -> bool:
    return _CRYPTOGRAPHY_IMPORT_ERROR is None


def require_cryptography() -> None:
    if cryptography_available():
        return
    raise RuntimeError(
        "Audio authenticity requires the optional 'cryptography' package. "
        "Install the app dependencies from requirements.txt or run "
        "'pip install cryptography'."
    ) from _CRYPTOGRAPHY_IMPORT_ERROR


def canonical_json_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    normalized = current.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def generate_private_key() -> Ed25519PrivateKey:
    require_cryptography()
    return _Ed25519PrivateKey.generate()


def private_key_raw_bytes(private_key: Ed25519PrivateKey) -> bytes:
    require_cryptography()
    return private_key.private_bytes(
        encoding=_serialization.Encoding.Raw,
        format=_serialization.PrivateFormat.Raw,
        encryption_algorithm=_serialization.NoEncryption(),
    )


def private_key_pem_bytes(private_key: Ed25519PrivateKey) -> bytes:
    require_cryptography()
    return private_key.private_bytes(
        encoding=_serialization.Encoding.PEM,
        format=_serialization.PrivateFormat.PKCS8,
        encryption_algorithm=_serialization.NoEncryption(),
    )


def public_key_b64(public_key: Ed25519PublicKey) -> str:
    require_cryptography()
    raw = public_key.public_bytes(
        encoding=_serialization.Encoding.Raw,
        format=_serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def public_key_from_b64(public_key_b64_value: str) -> Ed25519PublicKey:
    require_cryptography()
    return _Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64_value))


def key_id_for_public_key(public_key: Ed25519PublicKey) -> str:
    require_cryptography()
    raw = public_key.public_bytes(
        encoding=_serialization.Encoding.Raw,
        format=_serialization.PublicFormat.Raw,
    )
    return f"ed25519-{hashlib.sha256(raw).hexdigest()[:16]}"


def sign_bytes(private_key: Ed25519PrivateKey, payload: bytes) -> str:
    require_cryptography()
    signature = private_key.sign(payload)
    return base64.b64encode(signature).decode("ascii")


def verify_signature(public_key: Ed25519PublicKey, payload: bytes, signature_b64: str) -> bool:
    require_cryptography()
    try:
        public_key.verify(base64.b64decode(signature_b64), payload)
        return True
    except Exception:
        return False


def write_private_key(private_key: Ed25519PrivateKey, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(private_key_pem_bytes(private_key))
    try:
        destination.chmod(0o600)
    except Exception:
        pass


def load_private_key(path: str | Path) -> Ed25519PrivateKey:
    require_cryptography()
    raw = Path(path).read_bytes()
    key = _serialization.load_pem_private_key(raw, password=None)
    if not isinstance(key, _Ed25519PrivateKey):
        raise TypeError("Private key is not an Ed25519 key.")
    return key


def derive_watermark_key(private_key: Ed25519PrivateKey) -> bytes:
    require_cryptography()
    return _HKDF(
        algorithm=_hashes.SHA256(),
        length=32,
        salt=None,
        info=WATERMARK_KEY_INFO,
    ).derive(private_key_raw_bytes(private_key))
