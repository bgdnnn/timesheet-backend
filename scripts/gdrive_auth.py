import os
import sys
from google_auth_oauthlib.flow import Flow

def main():
    # Allow HTTP transport for local redirect validation (required for headless localhost copy-paste)
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    
    client_secrets_path = "/srv/timesheet-backend/gdrive-client-secrets.json"
    token_path = "/srv/timesheet-backend/gdrive-token.json"
    
    if not os.path.exists(client_secrets_path):
        print(f"Error: Client secrets file not found at {client_secrets_path}")
        print("Please download your OAuth client secrets JSON file from Google Cloud Console,")
        print("save it to that path, and run this script again.")
        sys.exit(1)
        
    scopes = ['https://www.googleapis.com/auth/drive']
    
    # Initialize the flow
    # Desktop apps require redirect_uri to be http://localhost (or loopback)
    flow = Flow.from_client_secrets_file(
        client_secrets_path,
        scopes=scopes,
        redirect_uri='http://localhost'
    )
    
    # Generate the authorization URL
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    
    print("\n" + "="*80)
    print("GOOGLE DRIVE BACKUP AUTHORIZATION")
    print("="*80)
    print("1. Open the following URL in your web browser:")
    print(f"\n{auth_url}\n")
    print("2. Log in with your Google Account and grant permissions.")
    print("3. After consenting, your browser will try to redirect to a page like:")
    print("   http://localhost/?state=...&code=...")
    print("   (Note: This page will likely show 'Site cannot be reached' or 'Connection Refused'.)")
    print("4. Copy the ENTIRE URL from your browser's address bar and paste it below.")
    print("="*80 + "\n")
    
    try:
        redirect_response = input("Paste the redirected URL here: ").strip()
        if not redirect_response:
            print("Error: No URL provided.")
            sys.exit(1)
            
        print("\nExchanging code for access and refresh tokens...")
        flow.fetch_token(authorization_response=redirect_response)
        
        # Save credentials
        creds = flow.credentials
        with open(token_path, 'w') as token_file:
            token_file.write(creds.to_json())
            
        print(f"\nSuccess! Authorization completed successfully.")
        print(f"Credentials saved to {token_path}")
        
    except Exception as e:
        print(f"\nAuthorization failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
