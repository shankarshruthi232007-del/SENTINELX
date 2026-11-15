from flask import Flask, render_template, request, jsonify, session, send_file, redirect, url_for
from datetime import datetime, timedelta, timezone
from pathlib import Path
from io import BytesIO
from urllib.parse import urlencode, quote
import csv, hashlib, hmac, json, os, re, secrets, urllib.request, urllib.error

ROOT = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'public'), static_url_path='/public')
SESSION_SECRET = os.getenv('SESSION_SECRET', '')
app.secret_key = SESSION_SECRET or 'local-demo-secret-change-before-deploy'
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=bool(os.getenv('VERCEL')),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=3),
)

SUPABASE_URL = os.getenv('SUPABASE_URL', '').rstrip('/')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')
PERSISTENT = bool(SUPABASE_URL and SUPABASE_KEY)
DEPLOY_CONFIG_ERRORS = []
if os.getenv('VERCEL') and not SESSION_SECRET: DEPLOY_CONFIG_ERRORS.append('SESSION_SECRET')
if os.getenv('VERCEL') and not PERSISTENT: DEPLOY_CONFIG_ERRORS.append('SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY')
if os.getenv('VERCEL') and not os.getenv('ADMIN_PASSWORD'): DEPLOY_CONFIG_ERRORS.append('ADMIN_PASSWORD')

ORG_TYPES = {
    'banking': {'label': 'Banking & Finance', 'name': 'Northstar Bank', 'icon': '◈'},
    'healthcare': {'label': 'Healthcare', 'name': 'Carewell Health', 'icon': '✚'},
    'education': {'label': 'Education', 'name': 'Summit University', 'icon': '⌂'},
    'corporate': {'label': 'Corporate', 'name': 'Apex Corporation', 'icon': '▦'},
    'general': {'label': 'General Organisation', 'name': 'Demo Organisation', 'icon': '◉'},
}

RESOURCE_SETS = {
    'banking': [
        ('Financial_Report_2026.csv', 'FINANCE', 'CONFIDENTIAL', 'Synthetic quarterly financial summary.'),
        ('Customer_Records_Demo.csv', 'CUSTOMER', 'RESTRICTED', 'Entirely fictional customer records.'),
        ('Transaction_Audit_Sample.csv', 'AUDIT', 'CONFIDENTIAL', 'Synthetic transaction audit sample.'),
        ('Executive_Strategy_Demo.txt', 'STRATEGY', 'RESTRICTED', 'Fictional strategic planning notes.'),
    ],
    'healthcare': [
        ('Patient_Records_Demo.csv', 'PATIENT', 'RESTRICTED', 'Synthetic patient records; no real health data.'),
        ('Clinical_Report_Sample.txt', 'CLINICAL', 'CONFIDENTIAL', 'Fictional clinical operations summary.'),
        ('Hospital_Audit_Demo.csv', 'AUDIT', 'CONFIDENTIAL', 'Synthetic hospital audit sample.'),
        ('Care_Strategy_Demo.txt', 'STRATEGY', 'RESTRICTED', 'Fictional care strategy notes.'),
    ],
    'education': [
        ('Student_Records_Demo.csv', 'STUDENT', 'RESTRICTED', 'Synthetic student records; no real student data.'),
        ('Examination_Report_Sample.csv', 'EXAM', 'CONFIDENTIAL', 'Fictional examination summary.'),
        ('Campus_Audit_Demo.txt', 'AUDIT', 'CONFIDENTIAL', 'Synthetic campus audit notes.'),
        ('Academic_Strategy_Demo.txt', 'STRATEGY', 'RESTRICTED', 'Fictional academic planning notes.'),
    ],
    'corporate': [
        ('Employee_Directory_Demo.csv', 'EMPLOYEE', 'RESTRICTED', 'Synthetic employee directory.'),
        ('Business_Forecast_2026.csv', 'FINANCE', 'CONFIDENTIAL', 'Fictional business forecast.'),
        ('Internal_Audit_Sample.txt', 'AUDIT', 'CONFIDENTIAL', 'Synthetic internal audit notes.'),
        ('Executive_Strategy_Demo.txt', 'STRATEGY', 'RESTRICTED', 'Fictional executive planning notes.'),
    ],
    'general': [
        ('Customer_Master_Demo.csv', 'CUSTOMER', 'RESTRICTED', 'Synthetic customer records.'),
        ('Q4_Financial_Model.csv', 'FINANCE', 'CONFIDENTIAL', 'Fictional quarterly financial model.'),
        ('Security_Architecture_Demo.txt', 'SECURITY', 'CONFIDENTIAL', 'Fictional security architecture notes.'),
        ('Executive_Strategy_Demo.txt', 'STRATEGY', 'RESTRICTED', 'Synthetic strategy summary.'),
    ],
}


WORKSPACE_FILES = [
    {'name': 'Employee_Handbook.txt', 'category': 'POLICY', 'description': 'General employee information for the demo workspace.'},
    {'name': 'Team_Updates_Sample.csv', 'category': 'TEAM', 'description': 'Synthetic team updates and project status.'},
    {'name': 'Public_Annual_Summary.csv', 'category': 'REPORT', 'description': 'Fictional high-level annual summary.'},
]


# Local-only fallback. Vercel deployments should configure Supabase for durable shared state.
LOCAL = {'events': [], 'sessions': {}, 'attempts': {}, 'contained': set(), 'next_id': 1}

DEMO_ACCOUNTS = {
    'employee': {'password': os.getenv('EMPLOYEE_PASSWORD', 'Employee@2026'), 'role': 'employee'},
    'analyst': {'password': os.getenv('ANALYST_PASSWORD', 'Sentinel@2026'), 'role': 'deception'},
    'socadmin': {'password': os.getenv('ADMIN_PASSWORD', 'Admin@2026'), 'role': 'admin'},
}
if os.getenv('VERCEL') and not os.getenv('ADMIN_PASSWORD'):
    DEMO_ACCOUNTS['socadmin']['password'] = None


def slugify(value):
    value = re.sub(r'[^a-zA-Z0-9]+', '-', (value or '').strip().lower()).strip('-')
    return (value[:48] or 'demo-organisation')


def org_context():
    slug = session.get('org_slug', 'general-demo')
    sector = session.get('sector', 'general')
    name = session.get('org_name', ORG_TYPES.get(sector, ORG_TYPES['general'])['name'])
    return slug, sector, name


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def _sb(method, table, query='', payload=None, prefer=None):
    if not PERSISTENT:
        return None
    url = f"{SUPABASE_URL}/rest/v1/{table}" + (f"?{query}" if query else '')
    body = None if payload is None else json.dumps(payload).encode()
    headers = {'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}', 'Content-Type': 'application/json'}
    if prefer:
        headers['Prefer'] = prefer
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            raw = response.read().decode()
            return json.loads(raw) if raw else []
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors='replace')[:300]
        app.logger.error('Supabase request failed (%s): %s', exc.code, detail)
        raise RuntimeError('Persistent database request failed. Check the Supabase schema and environment variables.')
    except Exception as exc:
        app.logger.error('Supabase connection failed: %s', exc)
        raise RuntimeError('Could not reach the persistent database. Please try again.')


def make_event(session_id, event_type, detail, contribution=0, severity=None, username=None, org_slug=None):
    org_slug = org_slug or org_context()[0]
    username = username or session.get('username', 'unknown')
    if PERSISTENT:
        existing = _sb('GET', 'sx_sessions', f'session_id=eq.{session_id}&select=risk', None) or []
        current = int(existing[0].get('risk', 0)) if existing else 0
        score = min(100, current + contribution)
        event = {'org_slug': org_slug, 'session_id': session_id, 'username': username,
                 'event_type': event_type, 'detail': detail[:500], 'risk': score,
                 'severity': severity or risk_level(score), 'created_at': iso_now()}
        inserted = _sb('POST', 'sx_events', '', event, 'return=representation') or [event]
        _sb('POST', 'sx_sessions', 'on_conflict=session_id', {
            'session_id': session_id, 'org_slug': org_slug, 'username': username,
            'risk': score, 'status': 'CONTAINED' if is_contained(session_id, org_slug) else 'ACTIVE',
            'updated_at': iso_now()
        }, 'resolution=merge-duplicates,return=minimal')
        return inserted[0]
    score = min(100, int(LOCAL['sessions'].get(session_id, {}).get('risk', 0)) + contribution)
    event = {'id': LOCAL['next_id'], 'org_slug': org_slug, 'session_id': session_id, 'username': username,
             'event_type': event_type, 'detail': detail[:500], 'risk': score,
             'severity': severity or risk_level(score), 'created_at': iso_now()}
    LOCAL['next_id'] += 1
    LOCAL['events'].append(event)
    LOCAL['sessions'][session_id] = {'session_id': session_id, 'org_slug': org_slug, 'username': username,
                                     'risk': score, 'status': 'CONTAINED' if session_id in LOCAL['contained'] else 'ACTIVE',
                                     'updated_at': iso_now()}
    return event


def risk_level(score):
    return 'CRITICAL' if score >= 85 else 'HIGH' if score >= 60 else 'MEDIUM' if score >= 30 else 'LOW'


def get_events(org_slug, limit=200):
    if PERSISTENT:
        rows = _sb('GET', 'sx_events', f'org_slug=eq.{quote(str(org_slug), safe="")}&select=*&order=id.desc&limit={limit}') or []
        return list(reversed(rows))
    return [e for e in LOCAL['events'] if e['org_slug'] == org_slug][-limit:]


def get_sessions(org_slug):
    if PERSISTENT:
        return _sb('GET', 'sx_sessions', f'org_slug=eq.{quote(str(org_slug), safe="")}&select=*&order=updated_at.desc&limit=100') or []
    return [s for s in LOCAL['sessions'].values() if s['org_slug'] == org_slug]


def is_contained(sid, org_slug=None):
    org_slug = org_slug or org_context()[0]
    if PERSISTENT:
        rows = _sb('GET', 'sx_contained_sessions', f'session_id=eq.{quote(str(sid), safe="")}&org_slug=eq.{quote(str(org_slug), safe="")}&select=session_id&limit=1') or []
        return bool(rows)
    return sid in LOCAL['contained']


def client_key():
    raw = request.headers.get('X-Forwarded-For', request.remote_addr or 'local').split(',')[0].strip()
    return hashlib.sha256((app.secret_key + raw).encode()).hexdigest()[:32]


def get_attempt(org_slug, username, ip_key):
    if PERSISTENT:
        rows = _sb('GET', 'sx_login_attempts', f'org_slug=eq.{quote(str(org_slug), safe="")}&username=eq.{quote(str(username), safe="")}&ip_hash=eq.{quote(str(ip_key), safe="")}&select=*&limit=1') or []
        return rows[0] if rows else {'count': 0, 'locked_until': None}
    return LOCAL['attempts'].get((org_slug, username, ip_key), {'count': 0, 'locked_until': None})


def save_attempt(org_slug, username, ip_key, count, locked_until):
    row = {'org_slug': org_slug, 'username': username, 'ip_hash': ip_key, 'count': count, 'locked_until': locked_until}
    if PERSISTENT:
        _sb('POST', 'sx_login_attempts', 'on_conflict=org_slug,username,ip_hash', row, 'resolution=merge-duplicates,return=minimal')
    else:
        LOCAL['attempts'][(org_slug, username, ip_key)] = row


def reset_attempt(org_slug, username, ip_key):
    if PERSISTENT:
        _sb('DELETE', 'sx_login_attempts', f'org_slug=eq.{quote(str(org_slug), safe="")}&username=eq.{quote(str(username), safe="")}&ip_hash=eq.{quote(str(ip_key), safe="")}')
    else:
        LOCAL['attempts'].pop((org_slug, username, ip_key), None)


def org_resources(sector):
    return [{'name': n, 'category': c, 'classification': cl, 'description': d} for n, c, cl, d in RESOURCE_SETS.get(sector, RESOURCE_SETS['general'])]


def resource_content(filename, sector):
    if filename.endswith('.csv'):
        if 'Customer' in filename or 'Patient' in filename or 'Student' in filename or 'Employee' in filename:
            return 'RecordID,DisplayName,Category\nDEMO-001,Sample Person,FICTIONAL\nDEMO-002,Example Record,FICTIONAL\n'
        return 'Reference,Metric,Value\nDEMO-Q4,Sample Metric,125000\nDEMO-Q4,Illustrative Cost,78000\n'
    return f"SENTINELX CLASSROOM DECOY RESOURCE\nOrganisation sector: {sector}\nAll contents are synthetic and fictional.\nNo real organisational information is stored here.\n"


def create_session_id():
    return 'SX-' + datetime.now().strftime('%Y%m%d') + '-' + secrets.token_hex(3).upper()


@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    return response



@app.route('/style.css')
def public_stylesheet():
    return send_file(ROOT / 'public' / 'style.css', mimetype='text/css')

@app.route('/login.js')
def public_login_script():
    return send_file(ROOT / 'public' / 'login.js', mimetype='application/javascript')

@app.route('/portal.js')
def public_portal_script():
    return send_file(ROOT / 'public' / 'portal.js', mimetype='application/javascript')

@app.route('/soc.js')
def public_soc_script():
    return send_file(ROOT / 'public' / 'soc.js', mimetype='application/javascript')

@app.route('/workspace.js')
def public_workspace_script():
    return send_file(ROOT / 'public' / 'workspace.js', mimetype='application/javascript')

@app.route('/')
def index():
    if session.get('role') == 'admin': return redirect(url_for('soc'))
    if session.get('role') == 'deception': return redirect(url_for('deception'))
    if session.get('role') == 'employee': return redirect(url_for('workspace'))
    return redirect(url_for('login'))


@app.route('/login')
def login():
    return render_template('login.html', org_types=ORG_TYPES, is_vercel=bool(os.getenv('VERCEL')))


@app.route('/api/login', methods=['POST'])
def api_login():
    if DEPLOY_CONFIG_ERRORS:
        return jsonify({'ok': False, 'message': 'Deployment setup incomplete. Configure the required Vercel environment variables and redeploy.'}), 503
    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip().lower()[:64]
    password = str(data.get('password', ''))[:256]
    sector = data.get('sector', 'general')
    if sector not in ORG_TYPES: sector = 'general'
    org_name = re.sub(r'[<>\x00-\x1f]', '', str(data.get('org_name') or ORG_TYPES[sector]['name']).strip())[:80]
    org_slug = slugify(data.get('org_slug') or org_name)
    ip_hash = client_key()
    attempt = get_attempt(org_slug, username, ip_hash)
    locked_until = attempt.get('locked_until')
    if locked_until:
        try:
            lock_expiry = datetime.fromisoformat(locked_until.replace('Z', '+00:00'))
            if lock_expiry > datetime.now(timezone.utc):
                return jsonify({'ok': False, 'locked': True, 'message': 'This account is temporarily locked. The organisation owner has been notified.'}), 429
            # A fresh three-attempt window begins after the temporary lockout expires.
            attempt = {'count': 0, 'locked_until': None}
            save_attempt(org_slug, username, ip_hash, 0, None)
        except Exception: pass
    account = DEMO_ACCOUNTS.get(username)
    configured_password = account.get('password') if account else None
    if not configured_password or not hmac.compare_digest(configured_password, password):
        count = int(attempt.get('count', 0)) + 1
        lock_until = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat() if count >= 3 else None
        save_attempt(org_slug, username, ip_hash, count, lock_until)
        sid = session.get('sid') if session.get('org_slug') == org_slug else None
        sid = sid or create_session_id()
        session['sid'] = sid
        session['org_slug'] = org_slug
        session['sector'] = sector
        session['org_name'] = org_name
        make_event(sid, 'AUTH_FAILURE', f'Invalid sign-in for account label "{username or "blank"}" · attempt {count}', 8 if count < 3 else 28,
                   'HIGH' if count >= 3 else 'MEDIUM', username, org_slug)
        if count >= 3:
            make_event(sid, 'ACCOUNT_TEMPORARILY_LOCKED', 'Three consecutive failed attempts · 15-minute lockout applied · owner notification created', 20, 'CRITICAL', username, org_slug)
            return jsonify({'ok': False, 'locked': True, 'message': 'Three failed attempts. This account is temporarily locked for 15 minutes. The organisation owner has been notified.'}), 429
        return jsonify({'ok': False, 'message': f'Invalid credentials. Attempt {count} of 3.'}), 401

    prior_failures = int(attempt.get('count', 0))
    reset_attempt(org_slug, username, ip_hash)
    session.clear()
    session.permanent = True
    session['sid'] = create_session_id()
    session['username'] = username
    session['role'] = account['role']
    session['org_slug'] = org_slug
    session['sector'] = sector
    session['org_name'] = org_name
    if account['role'] == 'admin':
        make_event(session['sid'], 'SOC_ADMIN_LOGIN', 'Authorised SOC administrator signed in', 0, 'LOW', username, org_slug)
        destination = '/soc'
    elif account['role'] == 'employee':
        make_event(session['sid'], 'AUTH_SUCCESS', 'Demo employee credentials accepted', min(24, prior_failures * 7), 'MEDIUM' if prior_failures else 'LOW', username, org_slug)
        if prior_failures:
            make_event(session['sid'], 'RISK_BASED_REVIEW', f'Valid credentials followed {prior_failures} failed attempt(s) · review recommended', 12, 'HIGH' if prior_failures >= 2 else 'MEDIUM', username, org_slug)
        if prior_failures >= 2:
            session['role'] = 'deception'
            make_event(session['sid'], 'DECEPTION_REDIRECT', 'Risk-based routing to isolated deception environment after repeated failed sign-in signals', 12, 'HIGH', username, org_slug)
            destination = '/deception'
        else:
            destination = '/workspace'
    else:
        make_event(session['sid'], 'AUTH_SUCCESS', 'Demo credential accepted · session assigned to isolated deception environment', 8 + min(24, prior_failures * 7), 'HIGH' if prior_failures >= 2 else 'MEDIUM', username, org_slug)
        if prior_failures:
            make_event(session['sid'], 'RISK_BASED_REVIEW', f'Valid credentials followed {prior_failures} failed attempt(s) · review recommended', 12, 'HIGH' if prior_failures >= 2 else 'MEDIUM', username, org_slug)
        destination = '/deception'
    return jsonify({'ok': True, 'redirect': destination})


@app.route('/deception')
def deception():
    if session.get('role') != 'deception': return redirect(url_for('login'))
    if is_contained(session.get('sid')): return render_template('contained.html', org_name=session.get('org_name'))
    return render_template('deception.html', org_name=session.get('org_name'), username=session.get('username'), resources=org_resources(session.get('sector', 'general')))


@app.route('/workspace')
def workspace():
    if session.get('role') != 'employee': return redirect(url_for('login'))
    return render_template('workspace.html', org_name=session.get('org_name'), username=session.get('username'))


@app.route('/soc')
def soc():
    if session.get('role') != 'admin': return redirect(url_for('login'))
    return render_template('soc.html', org_name=session.get('org_name'), sector=session.get('sector'), persistent=PERSISTENT)


@app.route('/api/events')
def api_events():
    if session.get('role') != 'admin': return jsonify({'error': 'Authorised SOC administrator required.'}), 403
    org_slug = org_context()[0]
    events = get_events(org_slug)
    sessions = get_sessions(org_slug)
    return jsonify({'events': events, 'sessions': sessions, 'persistent': PERSISTENT,
                    'summary': {'failed': sum(e['event_type'] in ('AUTH_FAILURE', 'ACCOUNT_TEMPORARILY_LOCKED') for e in events),
                                'file_events': sum(e['event_type'] in ('FILE_VIEW', 'DOWNLOAD_ATTEMPT') for e in events),
                                'restricted': sum(e['event_type'] == 'RESTRICTED_ATTEMPT' for e in events),
                                'high_risk': sum(e.get('risk', 0) >= 60 for e in sessions)}})


@app.route('/api/workspace-action', methods=['POST'])
def api_workspace_action():
    if session.get('role') != 'employee': return jsonify({'error': 'Access denied.'}), 403
    sid = session.get('sid')
    if is_contained(sid): return jsonify({'ok': False, 'blocked': True, 'message': 'SESSION UNAVAILABLE · Please contact your organisation administrator.'}), 403
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    target = str(data.get('target', ''))[:120]
    if action == 'search':
        make_event(sid, 'WORKSPACE_SEARCH', f'Authorised workspace search: {target or "all"}', 2)
        matches = [f for f in WORKSPACE_FILES if target.lower() in (f['name'] + ' ' + f['category']).lower()]
        if not target or target.lower() in ('all', '*', 'list'): matches = WORKSPACE_FILES
        return jsonify({'ok': True, 'results': matches})
    if action in ('view', 'download'):
        item = next((f for f in WORKSPACE_FILES if f['name'] == target), None)
        if not item: return jsonify({'error': 'Resource not found.'}), 404
        make_event(sid, 'WORKSPACE_FILE_VIEW' if action == 'view' else 'WORKSPACE_DOWNLOAD',
                   f'{"Viewed" if action == "view" else "Requested download of"} {target} in authorised workspace', 3 if action == 'view' else 5)
        events = [e for e in get_events(org_context()[0]) if e['session_id'] == sid]
        searches = sum(e['event_type'] == 'WORKSPACE_SEARCH' for e in events)
        views = sum(e['event_type'] == 'WORKSPACE_FILE_VIEW' for e in events)
        downloads = sum(e['event_type'] == 'WORKSPACE_DOWNLOAD' for e in events)
        suspicious_sequence = (searches >= 3 and (downloads >= 1 or views >= 2)) or (downloads >= 2 and views >= 1)
        if suspicious_sequence:
            make_event(sid, 'DECEPTION_REDIRECT', 'Unusual resource-discovery and file-access sequence · moved to isolated deception environment', 30, 'HIGH')
            session['role'] = 'deception'
            return jsonify({'ok': True, 'redirect': '/deception', 'message': 'Additional security checks are required. Opening the secure resource environment.'})
        return jsonify({'ok': True, 'url': f'/workspace-download/{target}' if action == 'download' else None,
                        'preview': f'SENTINELX AUTHORISED DEMO RESOURCE\n{target}\nAll contents are synthetic demonstration data.' if action == 'view' else None})
    if action == 'restricted':
        make_event(sid, 'WORKSPACE_RESTRICTED_ATTEMPT', f'Restricted workspace resource requested: {target or "ADMIN_CONTROL_PANEL"}', 25, 'HIGH')
        make_event(sid, 'DECEPTION_REDIRECT', 'Restricted resource request triggered risk-based deception routing', 18, 'CRITICAL')
        session['role'] = 'deception'
        return jsonify({'ok': True, 'redirect': '/deception', 'message': 'Additional security checks are required. Opening the secure resource environment.'})
    return jsonify({'error': 'Unknown action.'}), 400


@app.route('/workspace-download/<path:filename>')
def workspace_download(filename):
    if session.get('role') != 'employee': return 'Session unavailable', 403
    if filename not in [f['name'] for f in WORKSPACE_FILES]: return 'Not found', 404
    content = f'SENTINELX AUTHORISED DEMO RESOURCE\n{filename}\nAll contents are synthetic demonstration data.\n'
    return send_file(BytesIO(content.encode()), as_attachment=True, download_name=filename, mimetype='text/plain')


@app.route('/api/action', methods=['POST'])
def api_action():
    if session.get('role') != 'deception': return jsonify({'error': 'Access denied.'}), 403
    sid = session.get('sid')
    if is_contained(sid): return jsonify({'ok': False, 'blocked': True, 'message': 'SESSION UNAVAILABLE · Please contact your organisation administrator.'}), 403
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    target = str(data.get('target', ''))[:120]
    resources = org_resources(session.get('sector', 'general'))
    if action == 'search':
        make_event(sid, 'RESOURCE_SEARCH', f'Resource index queried: {target or "all"}', 5)
        matches = [r for r in resources if target.lower() in (r['name'] + ' ' + r['category']).lower()]
        if not target or target.lower() in ('all', '*', 'list'): matches = resources
        return jsonify({'ok': True, 'results': matches})
    if action in ('view', 'download'):
        item = next((r for r in resources if r['name'] == target), None)
        if not item: return jsonify({'error': 'Resource not found.'}), 404
        contribution = 8 if action == 'view' else 12
        make_event(sid, 'FILE_VIEW' if action == 'view' else 'DOWNLOAD_ATTEMPT',
                   f'{"Viewed" if action == "view" else "Requested download of"} {target} · {item["classification"]}', contribution)
        # A repeated download sequence is a stronger signal than a single file interaction.
        events = [e for e in get_events(org_context()[0]) if e['session_id'] == sid]
        if action == 'download' and sum(e['event_type'] == 'DOWNLOAD_ATTEMPT' for e in events) >= 2:
            make_event(sid, 'DOWNLOAD_SEQUENCE', 'Repeated download sequence detected · possible data staging indicator', 14, 'HIGH')
        return jsonify({'ok': True, 'url': f'/download/{target}' if action == 'download' else None,
                        'preview': resource_content(target, session.get('sector', 'general')) if action == 'view' else None})
    if action == 'restricted':
        make_event(sid, 'RESTRICTED_ATTEMPT', f'Restricted decoy resource interaction: {target or "ADMIN_CONTROL_PANEL"}', 25, 'CRITICAL')
        return jsonify({'ok': False, 'message': 'Access denied. This interaction has been recorded.'}), 403
    return jsonify({'error': 'Unknown action.'}), 400


@app.route('/download/<path:filename>')
def download(filename):
    if session.get('role') != 'deception' or is_contained(session.get('sid')): return 'Session unavailable', 403
    allowed = {r['name'] for r in org_resources(session.get('sector', 'general'))}
    if filename not in allowed: return 'Not found', 404
    content = resource_content(filename, session.get('sector', 'general'))
    return send_file(BytesIO(content.encode()), as_attachment=True, download_name=filename, mimetype='text/csv' if filename.endswith('.csv') else 'text/plain')


@app.route('/api/contain', methods=['POST'])
def contain():
    if session.get('role') != 'admin': return jsonify({'error': 'Authorised SOC administrator required.'}), 403
    data = request.get_json(silent=True) or {}
    sid = str(data.get('session_id', ''))
    org_slug = org_context()[0]
    if not sid: return jsonify({'error': 'Select a session first.'}), 400
    if not any(str(item.get('session_id')) == sid for item in get_sessions(org_slug)):
        return jsonify({'error': 'That session is not part of this organisation.'}), 404
    if PERSISTENT:
        _sb('POST', 'sx_contained_sessions', 'on_conflict=session_id', {'session_id': sid, 'org_slug': org_slug, 'contained_at': iso_now()}, 'resolution=merge-duplicates,return=minimal')
        _sb('PATCH', 'sx_sessions', f'session_id=eq.{quote(str(sid), safe="")}&org_slug=eq.{quote(str(org_slug), safe="")}', {'status': 'CONTAINED', 'updated_at': iso_now()}, 'return=minimal')
    else:
        LOCAL['contained'].add(sid)
        if sid in LOCAL['sessions']: LOCAL['sessions'][sid]['status'] = 'CONTAINED'
    make_event(sid, 'SESSION_CONTAINED', 'SOC administrator contained this session · further decoy actions blocked', 0, 'CRITICAL', 'socadmin', org_slug)
    return jsonify({'ok': True, 'message': f'Session {sid} contained.'})


@app.route('/api/reset', methods=['POST'])
def reset():
    if session.get('role') != 'admin': return jsonify({'error': 'Authorised SOC administrator required.'}), 403
    org_slug = org_context()[0]
    if PERSISTENT:
        for table in ('sx_events', 'sx_sessions', 'sx_login_attempts', 'sx_contained_sessions'):
            _sb('DELETE', table, f'org_slug=eq.{quote(str(org_slug), safe="")}')
    else:
        LOCAL['events'] = [e for e in LOCAL['events'] if e['org_slug'] != org_slug]
        LOCAL['sessions'] = {k:v for k,v in LOCAL['sessions'].items() if v['org_slug'] != org_slug}
        LOCAL['attempts'] = {k:v for k,v in LOCAL['attempts'].items() if k[0] != org_slug}
        LOCAL['contained'] = {sid for sid in LOCAL['contained'] if sid in LOCAL['sessions']}
    return jsonify({'ok': True})


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True, 'redirect': '/login'})


@app.route('/api/health')
def health():
    return jsonify({'ok': True, 'service': 'SENTINELX', 'database': 'persistent' if PERSISTENT else 'local-memory',
                    'vercel': bool(os.getenv('VERCEL')), 'configuration_ready': not DEPLOY_CONFIG_ERRORS,
                    'missing_environment': DEPLOY_CONFIG_ERRORS})


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.getenv('PORT', '5000')), debug=False)
