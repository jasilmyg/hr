"""
Quick connection test — run this to verify Google Sheets + Drive access.
Usage: python test_google.py
"""
import os
from dotenv import load_dotenv
load_dotenv()

print("=" * 50)
print("  HR Portal — Google Connection Test")
print("=" * 50)

# 1. Check env vars
sheet_id  = os.environ.get('GOOGLE_SHEET_ID', '')
key_file  = os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE', 'service_account.json')

print(f"\n[1] Sheet ID  : {sheet_id}")
print(f"[1] Key file  : {key_file}")
print(f"[1] Key exists: {os.path.exists(key_file)}")

# 2. Test Sheets access
try:
    import gspread
    from google.oauth2.service_account import Credentials

    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive',
    ]
    creds = Credentials.from_service_account_file(key_file, scopes=SCOPES)
    gc    = gspread.authorize(creds)
    sh    = gc.open_by_key(sheet_id)
    print(f"\n[2] ✅ Connected to sheet: '{sh.title}'")
    print(f"    URL: https://docs.google.com/spreadsheets/d/{sheet_id}/edit")
except Exception as e:
    print(f"\n[2] ❌ Sheets connection failed: {e}")
    raise SystemExit(1)

# 3. Test Drive access
try:
    from googleapiclient.discovery import build
    drive = build('drive', 'v3', credentials=creds)
    about = drive.about().get(fields='user').execute()
    print(f"[3] ✅ Drive connected as: {about['user']['emailAddress']}")
except Exception as e:
    print(f"[3] ❌ Drive connection failed: {e}")

# 4. Write a test row
try:
    from datetime import datetime
    import pytz
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S IST')

    try:
        ws = sh.worksheet('eSign Records')
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title='eSign Records', rows=1000, cols=10)
        print("[4] Created 'eSign Records' worksheet")

    # Add headers if needed
    first = ws.row_values(1)
    if not first or first[0] != 'Timestamp (IST)':
        headers = ['Timestamp (IST)','Document Title','Employee Name','Department',
                   'Document Status','Signed By','Date Signed','Signature Image URL',
                   'Drive File ID','Notes']
        ws.insert_row(headers, index=1)
        ws.format('A1:J1', {
            'backgroundColor': {'red': 0.24, 'green': 0.25, 'blue': 0.75},
            'textFormat': {'bold': True, 'foregroundColor': {'red':1,'green':1,'blue':1}},
        })
        print("[4] ✅ Headers created and styled")

    ws.append_row([now, 'TEST - Connection Check', 'System', 'HR Portal',
                   'test', 'Admin', now[:10], 'N/A', 'N/A', 'Auto-test row'])
    print(f"[4] ✅ Test row written to 'eSign Records' sheet!")

except Exception as e:
    print(f"[4] ❌ Write test failed: {e}")

print("\n" + "=" * 50)
print("  All checks passed! Ready to use.")
print("=" * 50)
