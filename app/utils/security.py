import base64
import hashlib
from cryptography.fernet import Fernet
from ..config import settings

def get_fernet_key() -> bytes:
    # Derive a 32-byte key from settings.JWT_SECRET
    return base64.urlsafe_b64encode(hashlib.sha256(settings.JWT_SECRET.encode()).digest())

def encrypt_value(val: str | None) -> str | None:
    if not val:
        return None
    f = Fernet(get_fernet_key())
    return f.encrypt(val.encode()).decode()

def decrypt_value(val: str | None) -> str | None:
    if not val:
        return None
    try:
        f = Fernet(get_fernet_key())
        return f.decrypt(val.encode()).decode()
    except Exception:
        return None
