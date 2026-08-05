"""Final integration test for NaijaRomance — run with: python run_tests.py"""
import json
import datetime

from app import app, db, User, Profile

# ── Disable CSRF globally for tests ───────────────────────────────────────────
app.config['WTF_CSRF_ENABLED'] = False

# ── DB setup (inside app_context, no client calls here) ───────────────────────
with app.app_context():
    for uname in ('_testA', '_testB'):
        u = User.query.filter_by(username=uname).first()
        if u:
            db.session.delete(u)
            db.session.commit()

    uA = User(username='_testA', email='_testA@x.com')
    uA.set_password('pass123')
    db.session.add(uA)
    db.session.flush()
    db.session.add(Profile(
        user_id=uA.id, first_name='Temi', gender='Female', state='Lagos',
        about_me='Test user A', date_of_birth=datetime.date(1995, 3, 10),
        profile_complete=True, interests='Music,Football'
    ))

    uB = User(username='_testB', email='_testB@x.com')
    uB.set_password('pass123')
    db.session.add(uB)
    db.session.flush()
    db.session.add(Profile(
        user_id=uB.id, first_name='Emeka', gender='Male', state='Enugu',
        about_me='Test user B', date_of_birth=datetime.date(1993, 7, 20),
        profile_complete=True, interests='Tech,Gaming'
    ))
    db.session.commit()

    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(username='admin', email='admin@nr.com')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.flush()
        db.session.add(Profile(
            user_id=admin.id, first_name='Admin', gender='Male', state='Lagos',
            about_me='Admin', date_of_birth=datetime.date(1985, 1, 1), profile_complete=True
        ))
        db.session.commit()

    uid_A     = uA.id
    uid_B     = uB.id
    uid_admin = admin.id

# ── Create clients OUTSIDE app_context ────────────────────────────────────────
cA = app.test_client(use_cookies=True)
with app.app_context():
    with cA.session_transaction() as sess:
        sess['_user_id'] = str(uid_A)
        sess['_fresh'] = True

cAdmin = app.test_client(use_cookies=True)
with app.app_context():
    with cAdmin.session_transaction() as sess:
        sess['_user_id'] = str(uid_admin)
        sess['_fresh'] = True

anon = app.test_client(use_cookies=True)

errors = []

def chk(client, method, route, expected=(200,), data=None, json_body=None):
    kw = {}
    if json_body:
        kw = {'data': json.dumps(json_body), 'content_type': 'application/json'}
    elif data:
        kw = {'data': data}
    r = client.get(route, follow_redirects=False) if method == 'GET' \
        else client.post(route, follow_redirects=False, **kw)
    if r.status_code not in expected:
        errors.append(f'{method} {route}: expected {expected}, got {r.status_code}')
        print(f'  FAIL {r.status_code} {method} {route}')
    else:
        print(f'  PASS {r.status_code} {method} {route}')
    return r

# ── Anonymous ─────────────────────────────────────────────────────────────────
print('\n--- ANONYMOUS ROUTES ---')
for route in ['/', '/login', '/register', '/terms', '/privacy', '/contact', '/forgot-password']:
    r = anon.get(route, follow_redirects=False)
    ok = r.status_code in (200, 302)
    if not ok:
        errors.append(f'ANON {route}: {r.status_code}')
    print(f'  {"PASS" if ok else "FAIL"} {r.status_code} {route}')

# ── Browse & Search ───────────────────────────────────────────────────────────
print('\n--- BROWSE & SEARCH ---')
chk(cA, 'GET', '/browse')
chk(cA, 'GET', '/browse?state=Lagos&sort=new')
chk(cA, 'GET', '/browse?gender=Male&goal=Marriage')
chk(cA, 'GET', '/search')
chk(cA, 'GET', '/search?q=Emeka')
chk(cA, 'GET', '/search?state=Enugu')

# ── Profiles & Account ────────────────────────────────────────────────────────
print('\n--- PROFILES & ACCOUNT ---')
chk(cA, 'GET', '/profile/_testA')
chk(cA, 'GET', '/profile/_testB')
chk(cA, 'GET', '/profile/edit')
chk(cA, 'GET', '/dashboard')
chk(cA, 'GET', '/settings')
chk(cA, 'GET', '/blocked')
chk(cA, 'GET', '/profile/viewers')

# ── Social Features ───────────────────────────────────────────────────────────
print('\n--- SOCIAL FEATURES ---')
chk(cA, 'GET', '/likes')
chk(cA, 'GET', '/winks')
chk(cA, 'GET', '/matches')
chk(cA, 'GET', '/online')
chk(cA, 'GET', '/notifications')

# ── Messages ──────────────────────────────────────────────────────────────────
print('\n--- MESSAGES ---')
chk(cA, 'GET', '/messages')
chk(cA, 'GET', '/messages/_testB')
chk(cA, 'GET', '/messages/_testB/poll?since=0')
chk(cA, 'GET', f'/report/{uid_B}')

# ── API Endpoints ─────────────────────────────────────────────────────────────
print('\n--- API ENDPOINTS ---')
chk(cA, 'GET', '/api/unread-counts')
chk(cA, 'GET', '/api/site-stats')
chk(cA, 'GET', '/api/online-count')
chk(cA, 'GET', '/api/trending-states')
chk(anon, 'GET', '/api/check-username?username=hello')
chk(anon, 'GET', '/api/check-username?username=_testA')
chk(cA, 'GET', '/notifications/json')

# ── POST/Action Routes ────────────────────────────────────────────────────────
print('\n--- POST/ACTION ROUTES ---')
r = chk(cA, 'POST', f'/like/{uid_B}')
if r.status_code == 200:
    d = json.loads(r.data)
    ok = d.get('status') == 'liked'
    print(f'  {"PASS" if ok else "FAIL"} like payload: {d}')
    if not ok:
        errors.append(f'like payload: {d}')

r = chk(cA, 'POST', f'/like/{uid_B}')
if r.status_code == 200:
    d = json.loads(r.data)
    ok = d.get('status') == 'unliked'
    print(f'  {"PASS" if ok else "FAIL"} unlike payload: {d}')
    if not ok:
        errors.append(f'unlike payload: {d}')

r = chk(cA, 'POST', f'/wink/{uid_B}')
if r.status_code == 200:
    d = json.loads(r.data)
    ok = d.get('status') in ('sent', 'already_sent')
    print(f'  {"PASS" if ok else "FAIL"} wink payload: {d}')
    if not ok:
        errors.append(f'wink payload: {d}')

chk(cA, 'POST', '/api/typing/_testB')
chk(cA, 'GET',  '/api/typing/_testB')

# ── HTML Content Checks ───────────────────────────────────────────────────────
print('\n--- HTML CONTENT CHECKS ---')
r = cA.get('/profile/edit')
html = r.data.decode('utf-8', errors='replace')
for name, ok in {
    'interests-picker div':  'id="interestsPicker"' in html,
    'interestsHidden input': 'id="interestsHidden"' in html,
    'interest-pick-tag btn': 'interest-pick-tag' in html,
    'Music tag present':     'data-interest="Music"' in html,
    'JS picker IIFE':        'interestsPicker' in html,
}.items():
    if not ok:
        errors.append(f'HTML edit_profile: {name}')
    print(f'  {"PASS" if ok else "FAIL"} {name}')

r = anon.get('/register')
html = r.data.decode('utf-8', errors='replace')
for name, ok in {
    'AJAX check-username': 'check-username' in html,
    'togglePw function':   'togglePw' in html,
    'usernameStatus span': 'usernameStatus' in html,
}.items():
    if not ok:
        errors.append(f'HTML register: {name}')
    print(f'  {"PASS" if ok else "FAIL"} {name}')

r = cA.get('/search?q=test')
ok = r.status_code == 200 and 'NaijaRomance' in r.data.decode()
print(f'  {"PASS" if ok else "FAIL"} search page renders')
if not ok:
    errors.append('search page render failed')

# ── Error Pages ───────────────────────────────────────────────────────────────
print('\n--- ERROR PAGES ---')
r = cA.get('/nonexistent-xyz-page')
ok1 = r.status_code == 404
print(f'  {"PASS" if ok1 else "FAIL"} 404 status: {r.status_code}')
if not ok1:
    errors.append(f'404 status: {r.status_code}')
html = r.data.decode('utf-8', errors='replace')
ok2 = '404' in html and 'NaijaRomance' in html
print(f'  {"PASS" if ok2 else "FAIL"} 404 page content')
if not ok2:
    errors.append('404 content missing')

# ── Admin Routes ──────────────────────────────────────────────────────────────
print('\n--- ADMIN ROUTES ---')
for route in ['/admin', '/admin/users', '/admin/reports',
              '/admin/reports?status=reviewed', '/api/admin/growth']:
    r = cAdmin.get(route, follow_redirects=False)
    ok = r.status_code == 200
    if not ok:
        errors.append(f'ADMIN {route}: {r.status_code}')
    print(f'  {"PASS" if ok else "FAIL"} {r.status_code} GET {route}')

# ── JSON Shape Validation ─────────────────────────────────────────────────────
print('\n--- JSON SHAPE VALIDATION ---')
json_checks = [
    (cA,     '/api/unread-counts',               ['messages', 'notifications', 'winks']),
    (anon,   '/api/site-stats',                   ['members', 'online', 'likes', 'messages']),
    (cA,     '/api/online-count',                 ['count']),
    (anon,   '/api/check-username?username=xyz',  ['available', 'message']),
    (cA,     '/notifications/json',               ['count', 'items']),
    (cAdmin, '/api/admin/growth',                 None),   # list
]
for client, route, keys in json_checks:
    r = client.get(route)
    try:
        data = json.loads(r.data)
        if keys:
            missing = [k for k in keys if k not in data]
            ok = not missing
            if not ok:
                errors.append(f'JSON {route}: missing keys {missing}')
            print(f'  {"PASS" if ok else "FAIL"} {route}')
        else:
            ok = isinstance(data, list)
            if not ok:
                errors.append(f'JSON {route}: expected list, got {type(data).__name__}')
            print(f'  {"PASS" if ok else "FAIL"} {route} ({len(data) if ok else "?"} items)')
    except Exception as e:
        errors.append(f'JSON {route}: {e}')
        print(f'  FAIL {route}: {e}')

# ── Teardown ──────────────────────────────────────────────────────────────────
with app.app_context():
    for uname in ('_testA', '_testB'):
        u = User.query.filter_by(username=uname).first()
        if u:
            db.session.delete(u)
    db.session.commit()

app.config['WTF_CSRF_ENABLED'] = True

# ── Summary ───────────────────────────────────────────────────────────────────
print()
if errors:
    print(f'RESULT: {len(errors)} FAILURE(S):')
    for e in errors:
        print(f'  ✗ {e}')
else:
    print('RESULT: ALL TESTS PASSED - OK')
