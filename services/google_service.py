"""
Google Services — Sheets Integration + Catbox.moe Image Hosting
  - Uploads signature PNG to catbox.moe (free, no API key, permanent URLs)
  - Also saves locally to static/signatures/
  - Writes eSign record to Google Sheets with =IMAGE() formula
"""

import os
import io
import base64
import logging
import urllib.request
import urllib.parse
from datetime import datetime
import pytz
import gspread
from google.oauth2.service_account import Credentials

# Project root = parent of this services/ folder
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ──────────────────────────────────────────────────────────────
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

SHEET_HEADERS = [
    'Timestamp (IST)',
    'Document Title',
    'Employee Name',
    'Department',
    'Document Status',
    'Signed By',
    'Date Signed',
    'Signature Image',
    'Image URL',
    'Notes',
]


def _get_credentials():
    """
    Load Google credentials.
    - On Render (production): reads from GOOGLE_SERVICE_ACCOUNT_JSON env var (JSON string)
    - Locally: reads from service_account.json file
    """
    import json

    # ── Try env var first (Render / production) ──
    json_str = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON', '').strip()
    if json_str:
        try:
            info = json.loads(json_str)
            return Credentials.from_service_account_info(info, scopes=SCOPES)
        except Exception as e:
            raise ValueError(f"Invalid GOOGLE_SERVICE_ACCOUNT_JSON: {e}")

    # ── Fall back to local file ──
    key_filename = os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE', 'service_account.json')
    if not os.path.isabs(key_filename):
        key_filename = os.path.join(PROJECT_ROOT, key_filename)
    if not os.path.exists(key_filename):
        raise FileNotFoundError(
            f"No credentials found. Set GOOGLE_SERVICE_ACCOUNT_JSON env var "
            f"(on Render) or place service_account.json at: {key_filename}"
        )
    return Credentials.from_service_account_file(key_filename, scopes=SCOPES)


# ──────────────────────────────────────────────────────────────
# Save PNG locally to static/signatures/
# ──────────────────────────────────────────────────────────────
def _save_locally(base64_data: str, filename: str) -> bytes:
    """Save signature PNG locally and return the raw bytes."""
    raw = base64_data.split(',', 1)[1] if ',' in base64_data else base64_data
    img_bytes = base64.b64decode(raw)

    sig_dir = os.path.join(PROJECT_ROOT, 'static', 'signatures')
    os.makedirs(sig_dir, exist_ok=True)
    with open(os.path.join(sig_dir, filename), 'wb') as f:
        f.write(img_bytes)

    logging.info(f"[SIG] Saved locally: {filename}")
    return img_bytes


# ──────────────────────────────────────────────────────────────
# Upload PNG bytes to catbox.moe — free, no API key needed
# Returns a permanent public URL like https://files.catbox.moe/abc123.png
# ──────────────────────────────────────────────────────────────
def _upload_to_catbox(img_bytes: bytes, filename: str) -> str:
    """
    Upload image to catbox.moe using multipart form-data.
    No account or API key required. Files are permanent.
    """
    boundary = b'----CatboxBoundary7MA4YWxkTrZu0gW'

    body = (
        b'--' + boundary + b'\r\n'
        b'Content-Disposition: form-data; name="reqtype"\r\n\r\n'
        b'fileupload\r\n'
        b'--' + boundary + b'\r\n' +
        b'Content-Disposition: form-data; name="fileToUpload"; filename="' + filename.encode() + b'"\r\n'
        b'Content-Type: image/png\r\n\r\n' +
        img_bytes + b'\r\n'
        b'--' + boundary + b'--\r\n'
    )

    req = urllib.request.Request(
        'https://catbox.moe/user/api.php',
        data=body,
        headers={
            'Content-Type': f'multipart/form-data; boundary={boundary.decode()}',
            'User-Agent': 'HR-Portal/1.0',
        },
        method='POST',
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        url = resp.read().decode('utf-8').strip()

    if not url.startswith('https://'):
        raise RuntimeError(f"Catbox upload failed: {url}")

    logging.info(f"[CATBOX] Uploaded: {url}")
    return url


# ──────────────────────────────────────────────────────────────
# Ensure correct headers on the worksheet
# ──────────────────────────────────────────────────────────────
def _ensure_headers(worksheet):
    try:
        first_row = worksheet.row_values(1)
    except Exception:
        first_row = []

    if not first_row or first_row[0] != SHEET_HEADERS[0]:
        worksheet.insert_row(SHEET_HEADERS, index=1)
        worksheet.format('A1:J1', {
            'backgroundColor': {'red': 0.24, 'green': 0.25, 'blue': 0.75},
            'textFormat': {
                'bold': True,
                'foregroundColor': {'red': 1, 'green': 1, 'blue': 1},
            },
        })
        logging.info("[SHEETS] Headers created.")


# ──────────────────────────────────────────────────────────────
# Main: upload image → write sheet row with =IMAGE() formula
# ──────────────────────────────────────────────────────────────
def save_esign_to_sheet(
    doc_title:     str,
    employee_name: str,
    department:    str,
    status:        str,
    signed_by:     str,
    signature_b64: str,
    notes:         str = ''
) -> dict:

    sheet_id = os.environ.get('GOOGLE_SHEET_ID', '')
    if not sheet_id or sheet_id == 'your_google_sheet_id_here':
        raise ValueError("GOOGLE_SHEET_ID is not configured in .env")

    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    timestamp_str = now.strftime('%Y-%m-%d %H:%M:%S IST')
    date_str      = now.strftime('%d %b %Y')

    safe_name    = employee_name.replace(' ', '_').replace('/', '_')
    safe_doc     = doc_title.replace(' ', '_').replace('/', '_')
    sig_filename = f"sig_{safe_name}_{safe_doc}_{now.strftime('%Y%m%d_%H%M%S')}.png"

    # ── 1. Save locally + upload to Catbox ──
    img_url     = ''
    img_formula = ''
    try:
        img_bytes = _save_locally(signature_b64, sig_filename)
        img_url   = _upload_to_catbox(img_bytes, sig_filename)
        img_formula = f'=IMAGE("{img_url}")'
        logging.info(f"[ESIGN] Image live at: {img_url}")
    except Exception as e:
        logging.error(f"[ESIGN] Image upload error: {e}")
        img_url = f'Upload error: {str(e)[:60]}'

    # ── 2. Write to Google Sheets ──
    creds = _get_credentials()
    gc    = gspread.authorize(creds)
    sh    = gc.open_by_key(sheet_id)

    try:
        worksheet = sh.worksheet('eSign Records')
    except gspread.WorksheetNotFound:
        worksheet = sh.add_worksheet(
            title='eSign Records', rows=1000, cols=len(SHEET_HEADERS)
        )

    _ensure_headers(worksheet)

    row = [
        timestamp_str,
        doc_title,
        employee_name,
        department,
        status,
        signed_by,
        date_str,
        img_formula if img_formula else img_url,   # col H: =IMAGE() or error
        img_url,                                    # col I: raw URL
        notes,
    ]
    worksheet.append_row(row, value_input_option='USER_ENTERED')

    # ── 3. Increase row height so image is visible ──
    if img_formula:
        try:
            last_row = len(worksheet.get_all_values())
            sh.batch_update({
                'requests': [{
                    'updateDimensionProperties': {
                        'range': {
                            'sheetId': worksheet.id,
                            'dimension': 'ROWS',
                            'startIndex': last_row - 1,
                            'endIndex': last_row,
                        },
                        'properties': {'pixelSize': 90},
                        'fields': 'pixelSize',
                    }
                }]
            })
        except Exception:
            pass  # non-critical

    logging.info(f"[SHEETS] Saved — {employee_name} / {doc_title}")

    return {
        'success':   True,
        'timestamp': timestamp_str,
        'img_url':   img_url,
        'filename':  sig_filename,
        'sheet_url': f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
        'sheet_id':  sheet_id,
    }
