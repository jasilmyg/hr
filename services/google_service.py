"""
Google Services — Sheets + Drive Integration
Handles:
  - Uploading signature images (base64 PNG) to Google Drive
  - Writing eSign records to Google Sheets
"""

import os
import io
import base64
import logging
from datetime import datetime
import pytz

# Google libraries
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ──────────────────────────────────────────────────────────────
# SCOPES
# ──────────────────────────────────────────────────────────────
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]

# ──────────────────────────────────────────────────────────────
# Google Sheet Column Headers
# (These will be created automatically if the sheet is empty)
# ──────────────────────────────────────────────────────────────
SHEET_HEADERS = [
    'Timestamp (IST)',
    'Document Title',
    'Employee Name',
    'Department',
    'Document Status',
    'Signed By',
    'Date Signed',
    'Signature Image URL',
    'Drive File ID',
    'Notes',
]

# ──────────────────────────────────────────────────────────────
# Build credentials from service account JSON file
# ──────────────────────────────────────────────────────────────
def _get_credentials():
    key_file = os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE', 'service_account.json')
    if not os.path.exists(key_file):
        raise FileNotFoundError(
            f"Service account file '{key_file}' not found. "
            "Download it from Google Cloud Console and place it in the project root."
        )
    creds = Credentials.from_service_account_file(key_file, scopes=SCOPES)
    return creds


# ──────────────────────────────────────────────────────────────
# Upload base64 signature PNG to Google Drive
# Returns: (shareable_url, file_id)
# ──────────────────────────────────────────────────────────────
def upload_signature_to_drive(base64_data: str, filename: str) -> tuple[str, str]:
    """
    Accepts a base64-encoded PNG (data:image/png;base64,... or raw base64)
    Uploads it to the Google Drive folder and returns a public view URL.
    """
    try:
        creds = _get_credentials()
        drive_service = build('drive', 'v3', credentials=creds)
        folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID', '')

        # Strip data URL prefix if present
        if ',' in base64_data:
            base64_data = base64_data.split(',', 1)[1]

        # Decode base64 → bytes
        image_bytes = base64.b64decode(base64_data)
        file_stream = io.BytesIO(image_bytes)

        # File metadata
        file_metadata = {
            'name': filename,
            'mimeType': 'image/png',
        }
        if folder_id:
            file_metadata['parents'] = [folder_id]

        media = MediaIoBaseUpload(file_stream, mimetype='image/png', resumable=False)

        # Upload file
        uploaded = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, webViewLink'
        ).execute()

        file_id = uploaded.get('id')

        # Make it publicly readable (anyone with link can view)
        drive_service.permissions().create(
            fileId=file_id,
            body={'role': 'reader', 'type': 'anyone'},
        ).execute()

        # Get shareable thumbnail URL (direct image link for Sheets)
        view_url      = uploaded.get('webViewLink', '')
        thumbnail_url = f"https://drive.google.com/thumbnail?id={file_id}&sz=w400"

        logging.info(f"[DRIVE] Uploaded signature: {filename} → {view_url}")
        return thumbnail_url, file_id

    except Exception as e:
        logging.error(f"[DRIVE] Upload failed: {e}")
        raise


# ──────────────────────────────────────────────────────────────
# Ensure the Google Sheet has the correct header row
# ──────────────────────────────────────────────────────────────
def _ensure_headers(worksheet):
    try:
        first_row = worksheet.row_values(1)
    except Exception:
        first_row = []

    if not first_row or first_row[0] != SHEET_HEADERS[0]:
        worksheet.insert_row(SHEET_HEADERS, index=1)

        # Style the header row (bold + background)
        worksheet.format('A1:J1', {
            'backgroundColor': {'red': 0.24, 'green': 0.25, 'blue': 0.75},
            'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
        })
        logging.info("[SHEETS] Header row created.")


# ──────────────────────────────────────────────────────────────
# Append a signed document record to the Google Sheet
# ──────────────────────────────────────────────────────────────
def save_esign_to_sheet(
    doc_title:      str,
    employee_name:  str,
    department:     str,
    status:         str,
    signed_by:      str,
    signature_b64:  str,
    notes:          str = ''
) -> dict:
    """
    Main function called from Flask route.
    1. Uploads the signature image to Google Drive
    2. Appends a row to the Google Sheet
    Returns a dict with the result.
    """

    sheet_id  = os.environ.get('GOOGLE_SHEET_ID', '')
    if not sheet_id or sheet_id == 'your_google_sheet_id_here':
        raise ValueError("GOOGLE_SHEET_ID is not configured in .env")

    # ── 1. Upload signature image to Drive ──
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    timestamp_str = now.strftime('%Y-%m-%d %H:%M:%S IST')
    date_str      = now.strftime('%d %b %Y')

    safe_name    = employee_name.replace(' ', '_').replace('/', '_')
    safe_doc     = doc_title.replace(' ', '_').replace('/', '_')
    sig_filename = f"sig_{safe_name}_{safe_doc}_{now.strftime('%Y%m%d_%H%M%S')}.png"

    sig_url, file_id = '', ''
    if signature_b64:
        try:
            sig_url, file_id = upload_signature_to_drive(signature_b64, sig_filename)
        except Exception as e:
            logging.warning(f"[ESIGN] Signature upload failed, saving without image: {e}")
            sig_url = 'Upload failed'

    # ── 2. Write row to Google Sheet ──
    creds     = _get_credentials()
    gc        = gspread.authorize(creds)
    sh        = gc.open_by_key(sheet_id)

    # Use first sheet (or create "eSign Records" tab)
    try:
        worksheet = sh.worksheet('eSign Records')
    except gspread.WorksheetNotFound:
        worksheet = sh.add_worksheet(title='eSign Records', rows=1000, cols=len(SHEET_HEADERS))

    _ensure_headers(worksheet)

    row = [
        timestamp_str,
        doc_title,
        employee_name,
        department,
        status,
        signed_by,
        date_str,
        sig_url,       # Thumbnail / view URL
        file_id,       # Drive file ID
        notes,
    ]
    worksheet.append_row(row, value_input_option='USER_ENTERED')

    # ── If image URL exists, embed it as an IMAGE() formula ──
    if sig_url and sig_url != 'Upload failed':
        last_row = len(worksheet.get_all_values())
        sig_col  = SHEET_HEADERS.index('Signature Image URL') + 1  # 1-indexed
        cell     = gspread.utils.rowcol_to_a1(last_row, sig_col)
        worksheet.update(
            [[f'=IMAGE("{sig_url}")']],
            cell,
            value_input_option='USER_ENTERED'
        )

    logging.info(f"[SHEETS] Row added for {employee_name} — {doc_title}")

    return {
        'success': True,
        'timestamp': timestamp_str,
        'signature_url': sig_url,
        'file_id': file_id,
        'sheet_id': sheet_id,
        'sheet_url': f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
    }
