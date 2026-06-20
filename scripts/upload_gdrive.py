import sys
import os
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

def upload_file(file_path, folder_id, credentials_path):
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return False
    
    try:
        scopes = ['https://www.googleapis.com/auth/drive']
        
        # Determine the credential type from the JSON file content
        with open(credentials_path, 'r') as f:
            creds_data = json.load(f)
            
        if creds_data.get('type') == 'service_account':
            print("Authenticating using Google Service Account...")
            creds = service_account.Credentials.from_service_account_file(
                credentials_path, scopes=scopes
            )
        else:
            print("Authenticating using Google User Credentials (OAuth2)...")
            creds = Credentials.from_authorized_user_file(credentials_path, scopes=scopes)
            if creds and creds.expired and creds.refresh_token:
                print("Refreshing Google Drive access token...")
                creds.refresh(Request())
                with open(credentials_path, 'w') as token_file:
                    token_file.write(creds.to_json())
        
        # Build the Drive service
        service = build('drive', 'v3', credentials=creds)
        
        # File metadata
        file_name = os.path.basename(file_path)
        file_metadata = {
            'name': file_name,
            'parents': [folder_id] if folder_id else []
        }
        
        # Media upload handler
        media = MediaFileUpload(
            file_path, 
            mimetype='application/gzip',
            resumable=True
        )
        
        print(f"Uploading {file_name} to Google Drive...")
        # Upload the file
        uploaded_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        
        print(f"Google Drive Upload successful! File ID: {uploaded_file.get('id')}")
        return True
    except Exception as e:
        print(f"Google Drive Upload failed: {e}")
        return False

if __name__ == '__main__':
    if len(sys.argv) < 4:
        print("Usage: python upload_gdrive.py <file_path> <folder_id> <credentials_path>")
        sys.exit(1)
        
    f_path = sys.argv[1]
    f_id = sys.argv[2]
    creds_path = sys.argv[3]
    
    success = upload_file(f_path, f_id, creds_path)
    sys.exit(0 if success else 1)
