import sys
import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account

def upload_file(file_path, folder_id, credentials_path):
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return False
    
    try:
        # Load service account credentials
        scopes = ['https://www.googleapis.com/auth/drive']
        creds = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=scopes
        )
        
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
