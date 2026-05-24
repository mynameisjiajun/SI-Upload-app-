"""
Run this ONCE locally to get your Google OAuth2 refresh token.

Steps:
  1. pip install google-auth-oauthlib
  2. python setup_oauth.py
  3. A browser window opens — sign in with your Google account and allow access
  4. Copy the three values printed at the end into your .env file and Render env vars
"""

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive"]

flow = InstalledAppFlow.from_client_secrets_file("client_secrets.json", SCOPES)
creds = flow.run_local_server(port=0)

print("\n✅ Success! Add these to your .env and Render environment variables:\n")
print(f"GOOGLE_CLIENT_ID={creds.client_id}")
print(f"GOOGLE_CLIENT_SECRET={creds.client_secret}")
print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
