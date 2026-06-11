"""
Google Services — Sheets Integration
Signature images are saved to Flask's static/signatures/ folder
and served via the app's own URL (works on Render deployment).
No external image hosting needed.
"""

import os
import io
import base64
import logging
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
    'Image Filename',
    'Notes',
]

# ──────────────────────────────────────────────────────────────
def _get_credentials():
    # Always resolve relative to project root, not CWD
    key_filename = os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE', 'service_account.json')
    if not os.path.isabs(key_filename):
        key_filename = os.path.join(PROJECT_ROOT, key_filename)
    if not os.path.exists(key_filename):
        raise FileNotFoundError(
            f"Service account file not found at: {key_filename}\n"
            "Place service_account.json in the project root folder."
        )
    return Credentials.from_service_account_file(key_filename, scopes=SCOPES)


# ──────────────────────────────────────────────────────────────
# Save base64 PNG to static/signatures/ and return its filename
# ──────────────────────────────────────────────────────────────
def save_signature_locally(base64_data: str, filename: str) -> str:
    """Save signature PNG to static/signatures/ inside the project root."""
    sig_dir = os.path.join(PROJECT_ROOT, 'static', 'signatures')
    os.makedirs(sig_dir, exist_ok=True)

    # Strip data URL prefix
    if ',' in base64_data:
        base64_data = base64_data.split(',', 1)[1]

    img_bytes = base64.b64decode(base64_data)
    filepath   = os.path.join(sig_dir, filename)
    with open(filepath, 'wb') as f:
        f.write(img_bytes)

    logging.info(f"[SIG] Saved signature: {filepath}")
    return filename


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
# Main: save image locally + write sheet row with =IMAGE()
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

    # App base URL — set APP_BASE_URL in .env on Render
    base_url = os.environ.get('APP_BASE_URL', '').rstrip('/')

    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    timestamp_str = now.strftime('%Y-%m-%d %H:%M:%S IST')
    date_str      = now.strftime('%d %b %Y')

    safe_name    = employee_name.replace(' ', '_').replace('/', '_')
    safe_doc     = doc_title.replace(' ', '_').replace('/', '_')
    sig_filename = f"sig_{safe_name}_{safe_doc}_{now.strftime('%Y%m%d_%H%M%S')}.png"

    # ── 1. Save signature image file locally ──
    saved_filename = ''
    img_formula    = ''
    img_url        = ''

    try:
        saved_filename = save_signature_locally(signature_b64, sig_filename)
        if base_url:
            img_url     = f"{base_url}/static/signatures/{saved_filename}"
            img_formula = f'=IMAGE("{img_url}")'
            logging.info(f"[ESIGN] Image URL: {img_url}")
        else:
            # No public URL yet — store filename, formula set after deploy
            img_url     = f"[Deploy to Render — /static/signatures/{saved_filename}]"
            img_formula = ''
            logging.info("[ESIGN] APP_BASE_URL not set — storing filename only")
    except Exception as e:
        logging.error(f"[ESIGN] Signature save error: {e}")
        saved_filename = 'save_error'

    # ── 2. Write to Sheets ──
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
        img_formula if img_formula else img_url,
        saved_filename,
        notes,
    ]
    worksheet.append_row(row, value_input_option='USER_ENTERED')

    # ── 3. Increase row height for image visibility ──
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
            pass

    logging.info(f"[SHEETS] Saved — {employee_name} / {doc_title}")

    return {
        'success':    True,
        'timestamp':  timestamp_str,
        'img_url':    img_url,
        'filename':   saved_filename,
        'sheet_url':  f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
        'sheet_id':   sheet_id,
    }
