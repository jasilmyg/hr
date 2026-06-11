import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from dotenv import load_dotenv

load_dotenv()

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

# ── ROUTES ──
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    debug = os.environ.get('FLASK_DEBUG', 'true').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
