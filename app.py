import os
import logging
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

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


if __name__ == '__main__':
    # On Render, PORT is injected automatically.
    port  = int(os.environ.get('PORT', 5050))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
