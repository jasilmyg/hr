import os
import logging
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from dotenv import load_dotenv

# Use absolute path so .env is found regardless of where gunicorn is launched from
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_BASE_DIR, '.env'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# Ensure signatures folder exists on startup
os.makedirs(os.path.join('static', 'signatures'), exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'hr-dev-secret')

# ── Demo session (no real auth needed for demo) ──
@app.before_request
def auto_login():
    if request.endpoint not in ('static',):
        session.setdefault('logged_in', True)
        session.setdefault('user_name', 'Jasil')
        session.setdefault('user_role', 'HR Manager')
        session.setdefault('user_initials', 'JM')

# ────────────────────────────────────────────────
# PAGE ROUTES
# ────────────────────────────────────────────────
@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html', active='dashboard')

@app.route('/employees')
def employees():
    return render_template('employees.html', active='employees')

@app.route('/leave')
def leave():
    return render_template('leave.html', active='leave')

@app.route('/payroll')
def payroll():
    return render_template('payroll.html', active='payroll')

@app.route('/esign')
def esign():
    return render_template('esign.html', active='esign')

# Serve saved signature images (used in Google Sheets =IMAGE() formula)
@app.route('/static/signatures/<path:filename>')
def serve_signature(filename):
    return send_from_directory(os.path.join('static', 'signatures'), filename)

# ────────────────────────────────────────────────
# API — Save eSign record to Google Sheets + Drive
# ────────────────────────────────────────────────
@app.route('/api/esign/save', methods=['POST'])
def api_esign_save():
    """
    Expects JSON body:
    {
        "doc_title":     "Appointment Letter",
        "employee_name": "Rajesh Kumar",
        "department":    "HR Dept",
        "status":        "signed",
        "notes":         "optional",
        "signature_b64": "data:image/png;base64,iVBORw0KGgo..."
    }
    """
    try:
        data = request.get_json(force=True)

        doc_title     = data.get('doc_title', '').strip()
        employee_name = data.get('employee_name', '').strip()
        department    = data.get('department', 'HR Dept').strip()
        status        = data.get('status', 'signed')
        notes         = data.get('notes', '')
        signature_b64 = data.get('signature_b64', '')
        signed_by     = session.get('user_name', 'HR Manager')

        if not doc_title or not employee_name:
            return jsonify({'success': False, 'error': 'doc_title and employee_name are required'}), 400

        if not signature_b64:
            return jsonify({'success': False, 'error': 'No signature provided'}), 400

        # Import here so missing env vars don't crash the app on startup
        from services.google_service import save_esign_to_sheet

        result = save_esign_to_sheet(
            doc_title=doc_title,
            employee_name=employee_name,
            department=department,
            status=status,
            signed_by=signed_by,
            signature_b64=signature_b64,
            notes=notes,
        )

        return jsonify(result), 200

    except ValueError as ve:
        logging.error(f"[API] Config error: {ve}")
        return jsonify({'success': False, 'error': str(ve)}), 500

    except FileNotFoundError as fe:
        logging.error(f"[API] Service account missing: {fe}")
        return jsonify({'success': False, 'error': str(fe)}), 500

    except Exception as e:
        logging.exception(f"[API] Unexpected error saving eSign: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ────────────────────────────────────────────────
# API — Health check
# ────────────────────────────────────────────────
@app.route('/api/health')
def api_health():
    return jsonify({'status': 'ok', 'service': 'HR Portal'}), 200


# ────────────────────────────────────────────────
# API — Debug credentials (safe — no key exposed)
# ────────────────────────────────────────────────
@app.route('/api/debug/credentials')
def api_debug_credentials():
    """Check what credentials/env vars are configured on this server."""
    import json, base64 as b64mod

    b64_str   = os.environ.get('GOOGLE_SERVICE_ACCOUNT_B64', '')
    json_str  = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON', '')
    sheet_id  = os.environ.get('GOOGLE_SHEET_ID', '')

    info = {
        'GOOGLE_SHEET_ID':                   sheet_id[:20] + '...' if sheet_id else 'NOT SET',
        'GOOGLE_SERVICE_ACCOUNT_B64_set':    bool(b64_str),
        'GOOGLE_SERVICE_ACCOUNT_B64_len':    len(b64_str),
        'GOOGLE_SERVICE_ACCOUNT_JSON_set':   bool(json_str),
        'GOOGLE_SERVICE_ACCOUNT_JSON_len':   len(json_str),
    }

    if b64_str:
        try:
            decoded = b64mod.b64decode(b64_str).decode('utf-8')
            parsed  = json.loads(decoded)
            info['B64_decode'] = 'OK'
            info['client_email'] = parsed.get('client_email', 'missing')
        except Exception as e:
            info['B64_decode'] = f'FAILED: {e}'

    # Try actual credentials load
    try:
        from services.google_service import _get_credentials
        creds = _get_credentials()
        info['credentials_loaded'] = 'OK'
        info['sa_email'] = getattr(creds, 'service_account_email', 'unknown')
    except Exception as e:
        info['credentials_loaded'] = f'FAILED: {str(e)[:200]}'

    return jsonify(info), 200


if __name__ == '__main__':
    # On Render, PORT is injected automatically.
    port  = int(os.environ.get('PORT', 5050))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
