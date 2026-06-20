#!/srv/timesheet-backend/.venv/bin/python3
import os
import sys
import json
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
import traceback
import pypdf
import re
import subprocess
import base64
import hashlib
from cryptography.fernet import Fernet
from datetime import date, timedelta, datetime
import socket

# Set default socket timeout to 30 seconds to prevent hanging connections
socket.setdefaulttimeout(30)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, "../payslip_config.json"))
HISTORY_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, "../.payslip_history.json"))

def load_history():
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, 'r') as f:
                return set(json.load(f))
        except Exception as e:
            print(f"Warning: Could not read history file ({e}). Starting fresh.")
    return set()

def save_history(history):
    try:
        with open(HISTORY_PATH, 'w') as f:
            json.dump(list(history), f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save history file: {e}")

def decode_mime_words(s):
    if not s:
        return ""
    try:
        decoded_words = decode_header(s)
        parts = []
        for word, encoding in decoded_words:
            if isinstance(word, bytes):
                parts.append(word.decode(encoding or 'utf-8', errors='replace'))
            else:
                parts.append(word)
        return "".join(parts)
    except Exception:
        return str(s)

def sanitize_filename(name):
    return "".join(c for c in name if c.isalnum() or c in (' ', '_', '-', '.')).strip()

def get_safe_user_slug(email_addr):
    if not email_addr:
        return "user"
    raw = email_addr.split("@")[0]
    slug = re.sub(r"[^a-z0-9._-]+", "-", raw.lower()).strip("-._")
    return slug or "user"

def get_tax_year(dt):
    year = dt.year
    month = dt.month
    day = dt.day
    if month < 4 or (month == 4 and day < 6):
        start_year = year - 1
        end_year = year
    else:
        start_year = year
        end_year = year + 1
    return f"{str(start_year)[2:]}-{str(end_year)[2:]}"

def get_tax_week(dt):
    year = dt.year
    tax_start = date(year, 4, 6)
    if dt < tax_start:
        tax_start = date(year - 1, 4, 6)
    
    delta = dt - tax_start
    week = (delta.days // 7) + 1
    return week

def load_db_url():
    env_path = "/srv/timesheet-backend/.env"
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if line.strip().startswith("DATABASE_URL="):
                    return line.strip().split("=", 1)[1]
    return None

def load_jwt_secret():
    env_path = "/srv/timesheet-backend/.env"
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if line.strip().startswith("JWT_SECRET="):
                    return line.strip().split("=", 1)[1]
    return None

def decrypt_val(encrypted_val, jwt_secret):
    if not encrypted_val or encrypted_val == "None" or encrypted_val == "":
        return None
    try:
        key = base64.urlsafe_b64encode(hashlib.sha256(jwt_secret.encode()).digest())
        f = Fernet(key)
        return f.decrypt(encrypted_val.encode()).decode()
    except Exception as e:
        print(f"  Decryption failed: {e}")
        return None

def get_auto_upload_users(target_email=None):
    db_url = load_db_url()
    if not db_url:
        print("Error: Could not load DATABASE_URL")
        return []
    
    psql_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    if target_email:
        safe_email = target_email.replace("'", "''")
        sql = f"SELECT email, auto_upload_provider, auto_upload_folder, auto_upload_company, auto_upload_email, auto_upload_app_password, pdf_password FROM users WHERE email = '{safe_email}';"
    else:
        sql = "SELECT email, auto_upload_provider, auto_upload_folder, auto_upload_company, auto_upload_email, auto_upload_app_password, pdf_password FROM users WHERE is_auto_upload_enabled = true;"
    
    try:
        res = subprocess.run(['psql', psql_url, '-F', '\t', '-A', '-t', '-c', sql], capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Error fetching users from DB: {res.stderr.strip()}")
            return []
            
        users = []
        for line in res.stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split('\t')
            if len(parts) >= 7:
                users.append({
                    "user_email": parts[0],
                    "provider": parts[1],
                    "folder": parts[2],
                    "company": parts[3],
                    "email": parts[4],
                    "app_password_encrypted": parts[5],
                    "pdf_password_encrypted": parts[6]
                })
        return users
    except Exception as e:
        print(f"Error querying database: {e}")
        return []

def db_insert_payslip(email_addr, file_path, filename, tax_year, tax_week, process_date):
    db_url = load_db_url()
    if not db_url:
        print("  Error: Could not load DATABASE_URL from backend .env")
        return False
    
    try:
        psql_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        
        # Check if record already exists
        check_sql = f"SELECT id FROM payslip_files WHERE created_by='{email_addr}' AND filename='{filename}';"
        res = subprocess.run(['psql', psql_url, '-t', '-A', '-c', check_sql], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            print(f"  Record for {filename} already exists in database. Skipping DB insert.")
            return True
            
        # Insert record
        sql = f"""
        INSERT INTO payslip_files (created_by, file_path, filename, tax_year, tax_week, process_date, created_at)
        VALUES ('{email_addr}', '{file_path}', '{filename}', '{tax_year}', {tax_week}, '{process_date}', NOW());
        """
        res = subprocess.run(['psql', psql_url, '-c', sql], capture_output=True, text=True)
        if res.returncode == 0:
            print(f"  Database record inserted for {filename}.")
            return True
        else:
            print(f"  Failed to insert into database: {res.stderr.strip()}")
            return False
    except Exception as e:
        print(f"  Database insertion error: {e}")
        return False

def is_payslip_missing(user_email):
    today = date.today()
    tax_start = date(today.year, 4, 6)
    if today < tax_start:
        tax_start = date(today.year - 1, 4, 6)
    delta = today - tax_start
    current_week = (delta.days // 7) + 1
    
    if today.month < 4 or (today.month == 4 and today.day < 6):
        start_y = today.year - 1
        end_y = today.year
    else:
        start_y = today.year
        end_y = today.year + 1
    current_year_str = f"{str(start_y)[2:]}-{str(end_y)[2:]}"
    
    db_url = load_db_url()
    if not db_url:
        return True
        
    try:
        psql_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        sql = f"SELECT id FROM payslip_files WHERE created_by = '{user_email}' AND tax_year = '{current_year_str}' AND tax_week = {current_week};"
        res = subprocess.run(['psql', psql_url, '-t', '-A', '-c', sql], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return False
    except Exception as e:
        print(f"Error checking if payslip is missing: {e}")
        
    return True

def parse_tax_info_from_filename(filename, email_date):
    is_p60 = "p60" in filename.lower() or bool(re.search(r'(^|[^a-zA-Z0-9])p6([^a-zA-Z0-9]|$)', filename.lower()))
    
    week_match = re.search(r'(?:week|period|wk)[_\s-]?(\d+)', filename, re.IGNORECASE)
    year_pattern = re.search(r'(\d{4})[_\-\s]?(\d{4})', filename)
    year_short_pattern = re.search(r'(\d{2})[_\-\s]?(\d{2})', filename)
    single_year_pattern = re.search(r'\b(20\d{2})\b', filename)
    
    tax_week = None
    tax_year = None
    
    if is_p60:
        tax_week = 0
    elif week_match:
        try:
            tax_week = int(week_match.group(1))
        except ValueError:
            pass
            
    if year_pattern:
        start_y = year_pattern.group(1)
        end_y = year_pattern.group(2)
        tax_year = f"{start_y[2:]}-{end_y[2:]}"
    elif year_short_pattern:
        tax_year = f"{year_short_pattern.group(1)}-{year_short_pattern.group(2)}"
    elif single_year_pattern:
        yr = int(single_year_pattern.group(1))
        tax_year = f"{str(yr-1)[2:]}-{str(yr)[2:]}"
        
    if tax_week is None and not is_p60:
        tax_week = get_tax_week(email_date.date())
    if not tax_year:
        tax_year = get_tax_year(email_date.date())
        
    return tax_year, tax_week

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--email', help='Process a single user by email')
    args = parser.parse_args()

    jwt_secret = load_jwt_secret()
    if not jwt_secret:
        print("Error: Could not load JWT_SECRET from backend .env", file=sys.stderr)
        sys.exit(1)
        
    db_users = get_auto_upload_users(args.email)
    if not db_users:
        if args.email:
            print(f"Error: User '{args.email}' not found in database.", file=sys.stderr)
            sys.exit(1)
        else:
            print("No users with automatic upload enabled found in database.")
            sys.exit(0)
        
    print(f"Found {len(db_users)} users to process. Processing...")
    
    media_dir = "/srv/timesheet-backend/media"
    history = load_history()
    new_downloads = 0
    
    for u in db_users:
        user_email = u["user_email"]
        
        # Sunday Try-Again Check: only scan if user does NOT have the current week's payslip
        if not args.email and date.today().weekday() == 6:
            if not is_payslip_missing(user_email):
                print(f"Skipping user {user_email}: already has payslip for the current tax week (Sunday check).")
                continue
                
        provider = u["provider"]
        email_addr = u["email"]
        if not provider:
            if email_addr and "gmail.com" in email_addr.lower():
                provider = "gmail"
            elif email_addr and ("yahoo.com" in email_addr.lower() or "yahoo.co.uk" in email_addr.lower()):
                provider = "yahoo"
            else:
                provider = "gmail"

        folder_name = u["folder"] or "INBOX"
        company = u["company"]
        app_password = decrypt_val(u["app_password_encrypted"], jwt_secret)
        if app_password:
            app_password = app_password.replace(" ", "").strip()
        pdf_password = decrypt_val(u["pdf_password_encrypted"], jwt_secret)
        
        if not email_addr or not app_password:
            msg = f"Skipping user {user_email}: missing email/password details."
            if args.email:
                print(f"Error: {msg}", file=sys.stderr)
                sys.exit(1)
            else:
                print(msg)
                continue
            
        safe_user = get_safe_user_slug(user_email)
        target_dir = os.path.join(media_dir, safe_user, "payslips_pdf")
        
        if not os.path.exists(target_dir):
            try:
                os.makedirs(target_dir, exist_ok=True)
                print(f"Created target directory: {target_dir}")
            except Exception as e:
                msg = f"Error creating target directory {target_dir}: {e}"
                if args.email:
                    print(f"Error: {msg}", file=sys.stderr)
                    sys.exit(1)
                else:
                    print(msg)
                    continue
                
        imap_server = "imap.gmail.com" if provider == "gmail" else "imap.mail.yahoo.com"
        print(f"\n[{user_email}] Connecting to IMAP server {imap_server} ({email_addr})...")
        try:
            mail = imaplib.IMAP4_SSL(imap_server, 993)
            mail.login(email_addr, app_password)
        except Exception as e:
            msg = f"Connection/Login failed for {email_addr}: {e}"
            if args.email:
                print(f"Error: {msg}", file=sys.stderr)
                sys.exit(1)
            else:
                print(f"  {msg}")
                continue
            
        print(f"  Selecting folder: '{folder_name}'...")
        status, data = mail.select(f'"{folder_name}"')
        if status != 'OK':
            msg = f"Could not select folder '{folder_name}'. Status: {status}"
            if args.email:
                print(f"Error: {msg}", file=sys.stderr)
                sys.exit(1)
            else:
                print(f"  {msg}")
                print("  Available folders:")
                status, folder_list = mail.list()
                if status == 'OK':
                    for f in folder_list:
                        print(f"   - {decode_mime_words(f.decode('utf-8', errors='ignore'))}")
                mail.logout()
                continue
            
        search_status = False
        if company:
            search_query = f'SUBJECT "{company}"'
            print(f"  Searching folder with query: {search_query}...")
            status, messages = mail.uid('search', None, search_query)
            if status == 'OK':
                search_status = True
            else:
                print(f"  Search failed for query '{search_query}'. Falling back to ALL...")
                
        if not search_status:
            status, messages = mail.uid('search', None, 'ALL')
            if status != 'OK':
                msg = f"Error searching folder: {status}"
                if args.email:
                    print(f"Error: {msg}", file=sys.stderr)
                    sys.exit(1)
                else:
                    print(f"  {msg}")
                    mail.logout()
                    continue
                
        message_uids = messages[0].split()
        print(f"  Found {len(message_uids)} messages matching search criteria.")
        
        chunk_size = 50
        uid_str_list = [uid.decode('utf-8') for uid in message_uids]
        email_headers = []
        
        print(f"  Fetching message headers in batches of {chunk_size}...")
        for idx in range(0, len(uid_str_list), chunk_size):
            chunk = uid_str_list[idx : idx + chunk_size]
            range_str = ",".join(chunk)
            
            try:
                status, data = mail.uid('fetch', range_str, '(BODY[HEADER.FIELDS (MESSAGE-ID DATE)])')
                if status != 'OK' or not data:
                    continue
                    
                for item in data:
                    if isinstance(item, tuple):
                        envelope = item[0].decode('utf-8', errors='ignore')
                        header_bytes = item[1]
                        
                        uid_match = re.search(r'UID (\d+)', envelope, re.IGNORECASE)
                        if uid_match:
                            msg_uid = uid_match.group(1)
                            header_msg = email.message_from_bytes(header_bytes)
                            
                            msg_id = header_msg.get('Message-ID')
                            if msg_id:
                                msg_id = msg_id.strip()
                            else:
                                msg_id = f"uid_{msg_uid}"
                                
                            date_str = header_msg.get('Date')
                            email_headers.append((msg_uid, msg_id, date_str))
            except Exception as batch_err:
                print(f"    Error fetching headers batch at index {idx}: {batch_err}")
                
        print(f"  Successfully fetched {len(email_headers)} message headers. Processing...")
        
        user_downloads = 0
        for msg_uid, msg_id, date_str in email_headers:
            history_key = f"{user_email}:{msg_id}"
            if history_key in history or msg_id in history:
                if history_key not in history:
                    history.add(history_key)
                continue
                
            email_date = None
            if date_str:
                try:
                    email_date = parsedate_to_datetime(date_str)
                except Exception:
                    pass
            if not email_date:
                email_date = datetime.now()
                
            print(f"  [{user_email}] Fetching new email UID {msg_uid}...")
            try:
                status, msg_data = mail.uid('fetch', msg_uid.encode('utf-8'), '(RFC822)')
                if status != 'OK' or not msg_data or not msg_data[0]:
                    print(f"    Failed to fetch message UID {msg_uid}")
                    continue
                    
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                downloaded_any = False
                for part in msg.walk():
                    filename = part.get_filename()
                    if filename:
                        decoded_filename = decode_mime_words(filename)
                        sanitized_name = sanitize_filename(decoded_filename)
                        
                        if sanitized_name.lower().endswith('.pdf'):
                            tax_year, tax_week = parse_tax_info_from_filename(sanitized_name, email_date)
                            process_date = email_date.strftime('%Y-%m-%d')
                            
                            if tax_week == 0:
                                final_filename = f"{tax_year}_0.pdf"
                            else:
                                final_filename = f"{tax_year}_{tax_week}.pdf"
                                
                            dest_path = os.path.join(target_dir, final_filename)
                            
                            if os.path.exists(dest_path):
                                print(f"    File '{final_filename}' already exists on disk. Registering in DB if needed.")
                                db_insert_payslip(user_email, dest_path, final_filename, tax_year, tax_week, process_date)
                                downloaded_any = True
                                continue
                            
                            temp_path = dest_path + ".tmp"
                            
                            try:
                                payload = part.get_payload(decode=True)
                                if payload:
                                    with open(temp_path, 'wb') as f:
                                        f.write(payload)
                                        
                                    decrypted = False
                                    try:
                                        reader = pypdf.PdfReader(temp_path)
                                        if reader.is_encrypted:
                                            print(f"    File '{sanitized_name}' is encrypted. Attempting decryption...")
                                            if pdf_password:
                                                dec_status = reader.decrypt(pdf_password)
                                                if dec_status:
                                                    writer = pypdf.PdfWriter()
                                                    for page in reader.pages:
                                                        writer.add_page(page)
                                                    with open(dest_path, 'wb') as f:
                                                        writer.write(f)
                                                    print(f"    Saved decrypted: {final_filename}")
                                                    decrypted = True
                                                else:
                                                    print("    Decryption failed (incorrect password).")
                                            else:
                                                print("    No 'pdf_password' configured.")
                                        else:
                                            os.rename(temp_path, dest_path)
                                            print(f"    Saved: {final_filename}")
                                            decrypted = True
                                    except Exception as pdf_err:
                                        print(f"    PDF processing failed: {pdf_err}")
                                        if os.path.exists(temp_path):
                                            os.rename(temp_path, dest_path)
                                            print(f"    Saved (kept original): {final_filename}")
                                            decrypted = True
                                            
                                    if os.path.exists(temp_path):
                                        try:
                                            os.remove(temp_path)
                                        except Exception:
                                            pass
                                            
                                    if decrypted:
                                        db_insert_payslip(user_email, dest_path, final_filename, tax_year, tax_week, process_date)
                                        downloaded_any = True
                            except Exception as e:
                                print(f"    Failed to save attachment {decoded_filename}: {e}")
                                
                if downloaded_any:
                    user_downloads += 1
                    new_downloads += 1
            except Exception as email_err:
                print(f"    Failed to process message UID {msg_uid}: {email_err}")
                if args.email:
                    print(f"Error: Failed to process message: {email_err}", file=sys.stderr)
                    sys.exit(1)
                
            history.add(history_key)
            
        print(f"  [{user_email}] Finished. Processed {user_downloads} new payslips.")
        mail.logout()
        
    save_history(history)
    print(f"\nFinished run. Processed {new_downloads} new emails total.")

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        traceback.print_exc()
        sys.exit(1)
