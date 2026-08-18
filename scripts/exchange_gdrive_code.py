import os
import sys
import json
import urllib.parse
import requests

CLIENT_SECRETS_PATH = "/srv/timesheet-backend/gdrive-client-secrets.json"
TOKEN_PATH = "/srv/timesheet-backend/gdrive-token.json"

def exchange_code(code_or_url: str):
    if not os.path.exists(CLIENT_SECRETS_PATH):
        print(f"Error: Client secrets file not found at {CLIENT_SECRETS_PATH}")
        sys.exit(1)

    with open(CLIENT_SECRETS_PATH, "r") as f:
        secrets = json.load(f)

    cfg = secrets.get("installed") or secrets.get("web") or {}
    client_id = cfg.get("client_id")
    client_secret = cfg.get("client_secret")
    token_uri = cfg.get("token_uri", "https://oauth2.googleapis.com/token")

    # If full URL was pasted, parse the code query parameter
    code = code_or_url.strip()
    if "?" in code or "&" in code or code.startswith("http"):
        parsed = urllib.parse.urlparse(code)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            code = params["code"][0]
        else:
            print("Error: Could not find 'code' parameter in the provided URL.")
            sys.exit(1)

    print(f"Exchanging authorization code with Google OAuth token endpoint...")
    
    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": "http://localhost",
        "grant_type": "authorization_code",
    }

    resp = requests.post(token_uri, data=data)
    if resp.status_code != 200:
        print(f"Token exchange failed ({resp.status_code}): {resp.text}")
        sys.exit(1)

    token_data = resp.json()
    
    # Structure formatted for google.oauth2.credentials.Credentials
    saved_creds = {
        "token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "token_uri": token_uri,
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": ["https://www.googleapis.com/auth/drive"],
        "universe_domain": "googleapis.com",
        "account": "",
        "expiry": None
    }

    with open(TOKEN_PATH, "w") as tf:
        json.dump(saved_creds, tf, indent=2)

    print(f"Successfully saved new credentials to {TOKEN_PATH}!")
    print(f"Has Refresh Token: {bool(saved_creds.get('refresh_token'))}")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 exchange_gdrive_code.py '<redirected_url_or_code>'")
        sys.exit(1)
    exchange_code(sys.argv[1])
