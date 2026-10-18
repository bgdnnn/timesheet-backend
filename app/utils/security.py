import base64
import hashlib
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from ..config import encryption_secret

# Header prepended to encrypted files to identify them unambiguously
MAGIC_FILE_HEADER = b"TS_ENC_V1::"

def get_fernet_key() -> bytes:
    # Derive a 32-byte key from ENCRYPTION_SECRET (falls back to JWT_SECRET)
    return base64.urlsafe_b64encode(hashlib.sha256(encryption_secret().encode()).digest())

def get_user_fernet_key(user_email: str | None = None) -> bytes:
    """
    Derives an isolated per-user 32-byte encryption key based on ENCRYPTION_SECRET and user_email.
    If no user_email is provided, falls back to the master key.
    """
    if not user_email:
        return get_fernet_key()
    salt = f"{encryption_secret()}:{user_email.strip().lower()}"
    return base64.urlsafe_b64encode(hashlib.sha256(salt.encode()).digest())

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

def is_file_encrypted(data: bytes) -> bool:
    """Checks if raw file bytes start with the encrypted file magic header."""
    return data.startswith(MAGIC_FILE_HEADER)

def encrypt_file_bytes(data: bytes, user_email: str | None = None) -> bytes:
    """
    Encrypts raw bytes using the user's derived Fernet key and attaches the MAGIC_FILE_HEADER.
    If already encrypted, returns the data as is to prevent double-encryption.
    """
    if not data:
        return b""
    if data.startswith(MAGIC_FILE_HEADER):
        return data
    key = get_user_fernet_key(user_email)
    f = Fernet(key)
    ciphertext = f.encrypt(data)
    return MAGIC_FILE_HEADER + ciphertext

def decrypt_file_bytes(data: bytes, user_email: str | None = None) -> bytes:
    """
    Decrypts encrypted file bytes.
    If the file does not have MAGIC_FILE_HEADER, treats it as a legacy unencrypted file (backward-compatible).
    Tries the user-specific key first; falls back to the master key if token is invalid.
    """
    if not data:
        return b""
    if not data.startswith(MAGIC_FILE_HEADER):
        # Legacy unencrypted file
        return data
    ciphertext = data[len(MAGIC_FILE_HEADER):]
    key = get_user_fernet_key(user_email)
    f = Fernet(key)
    try:
        return f.decrypt(ciphertext)
    except InvalidToken:
        # Fallback to master key in case it was encrypted with master key
        master_f = Fernet(get_fernet_key())
        return master_f.decrypt(ciphertext)

def read_decrypted_file(file_path: str | Path, user_email: str | None = None) -> bytes:
    """
    Reads a file from disk and decrypts it into an in-memory bytes buffer.
    """
    path = Path(file_path)
    raw = path.read_bytes()
    return decrypt_file_bytes(raw, user_email)

def write_encrypted_file(file_path: str | Path, data: bytes, user_email: str | None = None) -> None:
    """
    Encrypts data and atomically writes it to file_path on disk.
    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encrypted = encrypt_file_bytes(data, user_email)
    temp_path = path.with_suffix(f"{path.suffix}.tmp_enc")
    temp_path.write_bytes(encrypted)
    temp_path.replace(path)
