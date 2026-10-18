#!/srv/timesheet-backend/.venv/bin/python3
"""
Migration Script: Transparently encrypt existing PDF payslips at rest.
Features:
- Two-phase validation: encrypts in RAM, decrypts, and verifies SHA-256 hash byte-for-byte.
- Atomically replaces files on disk only after 100% hash verification.
- Skips already-encrypted files.
- Full reporting on files scanned, encrypted, skipped, and errors.
"""
import os
import sys
import hashlib
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(SCRIPT_DIR, "../")))

from app.utils.security import (
    MAGIC_FILE_HEADER,
    encrypt_file_bytes,
    decrypt_file_bytes,
    is_file_encrypted,
    read_decrypted_file,
    write_encrypted_file,
    get_user_fernet_key
)

SLUG_TO_EMAIL = {
    "bogdan.tirnauca": "bogdan.tirnauca@gmail.com",
    "tinauca.bogdan": "tinauca.bogdan@gmail.com",
    "tirnauca.bogdan": "tirnauca.bogdan@gmail.com",
    "lenazamurca": "lenazamurca@gmail.com",
}

def resolve_user_email(file_path: Path) -> str | None:
    parts = file_path.parts
    # /srv/timesheet-backend/media/{slug}/payslips_pdf/...
    for slug, email in SLUG_TO_EMAIL.items():
        if slug in parts:
            return email
    return None

def migrate_media_payslips(media_root: Path = Path("/srv/timesheet-backend/media")):
    print(f"[*] Starting payslip at-rest encryption migration in: {media_root}")
    if not media_root.exists():
        print(f"[!] Error: {media_root} does not exist.")
        sys.exit(1)

    pdf_files = list(media_root.rglob("*.pdf"))
    total_found = len(pdf_files)
    print(f"[*] Found {total_found} PDF files in media folder.")

    encrypted_count = 0
    skipped_count = 0
    error_count = 0

    for idx, pdf_path in enumerate(pdf_files, 1):
        user_email = resolve_user_email(pdf_path)
        try:
            raw_bytes = pdf_path.read_bytes()
            if is_file_encrypted(raw_bytes):
                skipped_count += 1
                continue

            orig_hash = hashlib.sha256(raw_bytes).hexdigest()
            file_size = len(raw_bytes)

            # 1. Encrypt in RAM
            encrypted = encrypt_file_bytes(raw_bytes, user_email)

            # 2. Decrypt in RAM and verify SHA-256 match
            decrypted = decrypt_file_bytes(encrypted, user_email)
            dec_hash = hashlib.sha256(decrypted).hexdigest()

            if dec_hash != orig_hash:
                print(f"[!] ERROR: Hash mismatch for {pdf_path}! Original: {orig_hash}, Decrypted: {dec_hash}")
                error_count += 1
                continue

            # 3. Write encrypted file atomically
            write_encrypted_file(pdf_path, raw_bytes, user_email)

            # 4. Read back from disk and verify
            disk_decrypted = read_decrypted_file(pdf_path, user_email)
            disk_hash = hashlib.sha256(disk_decrypted).hexdigest()

            if disk_hash != orig_hash:
                print(f"[!] ERROR: Disk readback hash mismatch for {pdf_path}!")
                error_count += 1
                continue

            encrypted_count += 1
            if encrypted_count % 50 == 0 or encrypted_count == total_found:
                print(f"    -> Progress: Encrypted {encrypted_count}/{total_found} ({idx}/{total_found} processed)...")

        except Exception as e:
            print(f"[!] Exception while processing {pdf_path}: {e}")
            error_count += 1

    print("\n" + "=" * 60)
    print(f"[*] Migration Completed!")
    print(f"    - Total PDF files scanned : {total_found}")
    print(f"    - Successfully Encrypted  : {encrypted_count}")
    print(f"    - Already Encrypted/Skip  : {skipped_count}")
    print(f"    - Errors Encountered      : {error_count}")
    print("=" * 60)

    if error_count > 0:
        print(f"[!] WARNING: {error_count} errors encountered during migration!")
        sys.exit(1)
    else:
        print("[✓] All payslips verified and securely encrypted at rest.")

if __name__ == "__main__":
    migrate_media_payslips()
