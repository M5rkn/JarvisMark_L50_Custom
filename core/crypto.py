"""Machine-bound Fernet encryption for the Gemini API key + module-level cache."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
from pathlib import Path

_ENC_PREFIX = "enc:"
_api_key_cache: str | None = None


def invalidate_api_key_cache() -> None:
    global _api_key_cache
    _api_key_cache = None


def get_api_key_cache() -> str | None:
    return _api_key_cache


def set_api_key_cache(key: str | None) -> None:
    global _api_key_cache
    _api_key_cache = key


def _get_machine_id() -> str:
    parts = [platform.node()]
    if platform.system() == "Windows":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography"
            ) as k:
                parts.append(winreg.QueryValueEx(k, "MachineGuid")[0])
        except Exception:
            pass
    return "|".join(parts)


def _get_fernet(keyfile: Path):
    from cryptography.fernet import Fernet

    if keyfile.exists():
        salt = keyfile.read_bytes()
    else:
        salt = os.urandom(16)
        keyfile.parent.mkdir(parents=True, exist_ok=True)
        keyfile.write_bytes(salt)

    machine_id = _get_machine_id().encode()
    key = hashlib.pbkdf2_hmac("sha256", machine_id, salt, 100_000, dklen=32)
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_api_key(raw_key: str, keyfile: Path) -> str:
    """Return the key as an ``enc:<token>`` string, or plaintext on failure."""
    try:
        fernet = _get_fernet(keyfile)
        return _ENC_PREFIX + fernet.encrypt(raw_key.encode()).decode()
    except Exception as e:
        print(f"[Crypto] ⚠️ Encryption unavailable: {e} — storing plaintext")
        return raw_key


def decrypt_api_key(stored: str, keyfile: Path) -> str:
    """Decrypt an ``enc:<token>`` key; return plaintext as-is if not encrypted."""
    if not stored.startswith(_ENC_PREFIX):
        return stored
    try:
        fernet = _get_fernet(keyfile)
        return fernet.decrypt(stored[len(_ENC_PREFIX):].encode()).decode()
    except Exception as e:
        print(f"[Crypto] ⚠️ Decryption failed: {e} — returning raw token")
        return stored[len(_ENC_PREFIX):]
